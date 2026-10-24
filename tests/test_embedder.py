"""DashScope embedder 的行为契约。

用假的 httpx 传输层替代网络，但我们断言的是 embedder 自身的行为：
它发了什么请求体、怎么分片、顺序如何、错误怎么传播。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx
import numpy as np
import pytest

from memory.config import Settings
from memory.embedding.cache import EmbeddingCache
from memory.embedding.dashscope import DashScopeEmbedder

DIMS = 4


def _settings(cache_dir: Path) -> Settings:
    return Settings(
        llm_base_url="http://127.0.0.1:3211/api/open-platform-model/v1",
        llm_api_key="local",
        llm_model="deepseek-v4.1-flash",
        dashscope_api_key="sk-test",
        embedding_base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        embedding_model="qwen3.7-text-embedding-flash",
        embedding_dims=DIMS,
        http_proxy=None,
        https_proxy=None,
        no_proxy="127.0.0.1,localhost",
        cache_dir=cache_dir,
    )


def _embedding_response(
    inputs: list[str], dims: int = DIMS, *, reverse: bool = False
) -> dict[str, Any]:
    """构造与真实服务同形状的响应（含 data/model/usage）。

    `reverse=True` 让 data 乱序返回：真实服务不保证按 index 顺序排列，
    实现必须自己按 index 归位，否则向量与文本错配。
    """
    entries = [
        {"object": "embedding", "index": i, "embedding": [float(i + 1)] * dims}
        for i in range(len(inputs))
    ]
    if reverse:
        entries.reverse()
    return {
        "object": "list",
        "model": "qwen3.7-text-embedding-flash",
        "data": entries,
        "usage": {"prompt_tokens": 10, "total_tokens": 10},
    }


class _Recorder:
    """记录每次请求的请求体，供断言分片与参数。"""

    def __init__(
        self, *, fail_on_call: int | None = None, dims: int = DIMS, reverse: bool = False
    ) -> None:
        self.bodies: list[dict[str, Any]] = []
        self.calls = 0
        self._fail_on_call = fail_on_call
        self._dims = dims
        self._reverse = reverse

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.calls += 1
        body = json.loads(request.content)
        self.bodies.append(body)
        if self._fail_on_call is not None and self.calls == self._fail_on_call:
            return httpx.Response(500, json={"error": {"message": "boom"}})
        return httpx.Response(
            200, json=_embedding_response(body["input"], self._dims, reverse=self._reverse)
        )


def _embedder(
    cache_dir: Path, recorder: _Recorder, *, max_batch: int = 10
) -> DashScopeEmbedder:
    transport = httpx.MockTransport(recorder)
    client = httpx.Client(transport=transport)
    return DashScopeEmbedder(
        settings=_settings(cache_dir),
        cache=EmbeddingCache(cache_dir / "cache.db"),
        client=client,
        max_batch=max_batch,
    )


def test_document_and_query_types_are_sent_separately(tmp_path: Path) -> None:
    """若实现不传 text_type，查询与文档会用同一空间编码——实测余弦仅 0.842。"""
    recorder = _Recorder()
    embedder = _embedder(tmp_path, recorder)

    embedder.embed_documents(["a"])
    embedder.embed_query("b")

    assert recorder.bodies[0]["text_type"] == "document"
    assert recorder.bodies[1]["text_type"] == "query"


def test_batch_is_split_by_max_batch_and_order_preserved(tmp_path: Path) -> None:
    """分片后顺序错位会让问题与向量错配，且完全不可见。"""
    recorder = _Recorder()
    embedder = _embedder(tmp_path, recorder, max_batch=2)

    vectors = embedder.embed_documents(["t0", "t1", "t2", "t3", "t4"])

    assert [body["input"] for body in recorder.bodies] == [
        ["t0", "t1"],
        ["t2", "t3"],
        ["t4"],
    ]
    assert len(vectors) == 5
    # 服务端按批内 index 返回 1.0/2.0，合并后必须回到输入顺序
    assert [vec[0] for vec in vectors] == [1.0, 2.0, 1.0, 2.0, 1.0]


def test_out_of_order_response_is_reassembled_by_index(tmp_path: Path) -> None:
    """真实服务不保证按 index 顺序返回 data。

    若实现跳过排序，向量会与文本错配：第一段文本拿到最后一条向量。
    """
    embedder = _embedder(tmp_path, _Recorder(reverse=True))

    vectors = embedder.embed_documents(["first", "second", "third"])

    # 服务端为 index i 生成 (i+1) 的常量向量；按输入顺序应是 1.0, 2.0, 3.0
    assert [vec[0] for vec in vectors] == [1.0, 2.0, 3.0]


def test_vectors_are_float32_and_have_requested_dims(tmp_path: Path) -> None:
    """维度或类型不符会让下游点积静默出错。"""
    embedder = _embedder(tmp_path, _Recorder())

    vectors = embedder.embed_documents(["a", "b"])

    assert all(vec.dtype == np.float32 for vec in vectors)
    assert all(vec.shape == (DIMS,) for vec in vectors)


def test_dimension_mismatch_from_server_raises(tmp_path: Path) -> None:
    """服务端返回错误维度时必须报错，而不是截断/补零。"""
    embedder = _embedder(tmp_path, _Recorder(dims=DIMS + 2))

    with pytest.raises(ValueError, match="维度"):
        embedder.embed_documents(["a"])


def test_invalid_text_type_is_rejected_before_network(tmp_path: Path) -> None:
    """非法模式若透传，错误会延迟到服务端且信息更差。"""
    recorder = _Recorder()
    embedder = _embedder(tmp_path, recorder)

    with pytest.raises(ValueError, match="text_type"):
        embedder.embed("a", text_type="hybrid")  # type: ignore[arg-type]

    assert recorder.calls == 0


def test_second_identical_call_hits_cache(tmp_path: Path) -> None:
    """若缓存未接入，第二次仍会发请求，A3 的门禁失效。"""
    recorder = _Recorder()
    embedder = _embedder(tmp_path, recorder)

    embedder.embed_documents(["same"])
    embedder.embed_documents(["same"])

    assert recorder.calls == 1
    assert embedder.network_calls == 1


def test_partial_cache_hit_only_requests_missing(tmp_path: Path) -> None:
    """若整批未命中就全量重发，缓存等于没有。"""
    recorder = _Recorder()
    embedder = _embedder(tmp_path, recorder)
    embedder.embed_documents(["a", "b"])

    recorder.calls = 0
    recorder.bodies.clear()
    embedder.embed_documents(["a", "c"])

    assert [body["input"] for body in recorder.bodies] == [["c"]]
    assert recorder.calls == 1


def test_query_and_document_do_not_share_cache_entries(tmp_path: Path) -> None:
    """共享条目会导致查询向量被当成文档向量使用。"""
    recorder = _Recorder()
    embedder = _embedder(tmp_path, recorder)

    embedder.embed_documents(["x"])
    embedder.embed_query("x")

    assert recorder.calls == 2


def test_one_failed_chunk_fails_the_whole_call(tmp_path: Path) -> None:
    """返回部分结果会让样本静默缺失，比报错更难查。"""
    recorder = _Recorder(fail_on_call=2)
    embedder = _embedder(tmp_path, recorder, max_batch=1)

    with pytest.raises(httpx.HTTPStatusError):
        embedder.embed_documents(["a", "b"])


def test_failed_chunk_does_not_poison_cache(tmp_path: Path) -> None:
    """失败批若写入半截数据，重试会命中空向量。"""
    recorder = _Recorder(fail_on_call=1)
    embedder = _embedder(tmp_path, recorder)

    with pytest.raises(httpx.HTTPStatusError):
        embedder.embed_documents(["a"])

    assert embedder.cache.stats().entries == 0
