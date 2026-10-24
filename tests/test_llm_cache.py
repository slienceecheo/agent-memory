"""LLM 响应缓存的行为契约。

这个缓存存在的理由与 embedding 缓存不同：不是因为上游不确定（虽然它也不确定），
而是因为**模型本身有随机性**。没有它，"两次运行逐位一致"这条验收不可能成立。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import httpx
import pytest

from memory.config import Settings
from memory.llm.cache import CachedResponse, ResponseCache, request_key
from memory.llm.client import LLMClient
from memory.llm.sse import ToolCall, Usage

BASE = "http://127.0.0.1:3211/api/open-platform-model/v1"


def _settings(cache_dir: Path) -> Settings:
    return Settings(
        llm_base_url=BASE,
        llm_api_key="local",
        llm_model="deepseek-v4.1-flash",
        dashscope_api_key="sk-test",
        embedding_base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        embedding_model="qwen3.7-text-embedding-flash",
        embedding_dims=1024,
        http_proxy=None,
        https_proxy=None,
        no_proxy="127.0.0.1,localhost",
        cache_dir=cache_dir,
    )


def _sse(content: str, reasoning: int = 0) -> bytes:
    import json

    event = {"choices": [{"index": 0, "delta": {"content": content}}]}
    usage = {
        "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
        "usage": {
            "prompt_tokens": 5,
            "completion_tokens": 3,
            "total_tokens": 8,
            "completion_tokens_details": {"reasoning_tokens": reasoning},
        },
    }
    return f"data:{json.dumps(event)}\n\ndata:{json.dumps(usage)}\n\ndata:[DONE]\n\n".encode()


class _Counter:
    def __init__(self, text: str = "answer", reasoning: int = 0) -> None:
        self.count = 0
        self.text = text
        self.reasoning = reasoning

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.count += 1
        return httpx.Response(200, content=_sse(self.text, self.reasoning))


def _client(cache_dir: Path, counter: _Counter) -> tuple[LLMClient, ResponseCache]:
    cache = ResponseCache(cache_dir / "responses.db")
    client = LLMClient(
        settings=_settings(cache_dir),
        client=httpx.Client(transport=httpx.MockTransport(counter)),
        response_cache=cache,
        max_retries=0,
        backoff_seconds=0.0,
    )
    return client, cache


# ---------- 键的语义 ----------


def test_request_key_ignores_stream_flag() -> None:
    """stream 只影响传输方式，不影响语义结果；纳入键会让缓存永不命中。"""
    base = {"model": "m", "messages": [{"role": "user", "content": "hi"}]}

    assert request_key({**base, "stream": True}) == request_key({**base, "stream": False})


def test_request_key_is_order_insensitive() -> None:
    """同一请求体的字段顺序不同不该产生不同键。"""
    a = {"model": "m", "temperature": 0.0, "messages": []}
    b = {"messages": [], "temperature": 0.0, "model": "m"}

    assert request_key(a) == request_key(b)


@pytest.mark.parametrize(
    "field,value",
    [
        ("model", "other-model"),
        ("temperature", 0.7),
        ("messages", [{"role": "user", "content": "different"}]),
        ("tools", [{"type": "function"}]),
    ],
)
def test_request_key_changes_with_semantic_fields(field: str, value: Any) -> None:
    """漏掉任一语义字段都会让不同请求共用一条缓存，产出错误答案。"""
    base = {"model": "m", "messages": [{"role": "user", "content": "hi"}], "temperature": 0.0}

    assert request_key(base) != request_key({**base, field: value})


# ---------- 存储 ----------


def test_store_and_load_roundtrip(tmp_path: Path) -> None:
    """usage 与 tool_calls 若丢失，缓存命中时无法重建完整结果。"""
    cache = ResponseCache(tmp_path / "r.db")
    original = CachedResponse(
        content="hello",
        usage=Usage(prompt_tokens=1, completion_tokens=2, total_tokens=3, reasoning_tokens=1),
        finish_reason="stop",
        tool_calls=(ToolCall(id="c1", name="f", arguments='{"a":1}'),),
    )

    cache.put("k1", original)
    loaded = cache.get("k1")

    assert loaded == original


def test_corrupt_row_is_treated_as_miss(tmp_path: Path) -> None:
    """一行坏数据不该让整次评测崩掉。"""
    import sqlite3

    db = tmp_path / "r.db"
    cache = ResponseCache(db)
    cache.put(
        "k1",
        CachedResponse(content="x", usage=Usage(), finish_reason=None, tool_calls=()),
    )
    conn = sqlite3.connect(str(db))
    with conn:
        conn.execute("UPDATE responses SET usage = 'not json' WHERE key = 'k1'")
    conn.close()

    assert cache.get("k1") is None
    assert "k1" in cache.corrupt_keys


# ---------- 与客户端集成 ----------


def test_second_call_hits_cache_and_makes_no_request(tmp_path: Path) -> None:
    """这是 A2 的核心：重跑必须零网络、结果完全一致。"""
    counter = _Counter("first-answer")
    client, _ = _client(tmp_path, counter)

    first = client.complete([{"role": "user", "content": "hi"}])
    calls_after_first = counter.count
    second = client.complete([{"role": "user", "content": "hi"}])

    assert calls_after_first == 1
    assert counter.count == 1, "第二次调用不应发起网络请求"
    assert second.content == first.content
    assert second.usage == first.usage


def test_cached_result_keeps_reasoning_tokens(tmp_path: Path) -> None:
    """推理 token 若在缓存路径上丢失，浪费比例会被报成 0。"""
    counter = _Counter("x", reasoning=7)
    client, _ = _client(tmp_path, counter)

    client.complete([{"role": "user", "content": "hi"}])
    cached = client.complete([{"role": "user", "content": "hi"}])

    assert cached.usage.reasoning_tokens == 7


def test_different_prompt_misses_cache(tmp_path: Path) -> None:
    """不同 prompt 若共用缓存，会返回完全不相干的答案。"""
    counter = _Counter()
    client, _ = _client(tmp_path, counter)

    client.complete([{"role": "user", "content": "a"}])
    client.complete([{"role": "user", "content": "b"}])

    assert counter.count == 2


def test_different_temperature_misses_cache(tmp_path: Path) -> None:
    """温度变化会改变输出分布，不能复用。"""
    counter = _Counter()
    client, _ = _client(tmp_path, counter)

    client.complete([{"role": "user", "content": "x"}], temperature=0.0)
    client.complete([{"role": "user", "content": "x"}], temperature=0.9)

    assert counter.count == 2


def test_cache_is_persisted_across_instances(tmp_path: Path) -> None:
    """进程内缓存无法满足"重跑一致"，必须落盘。"""
    counter = _Counter("persisted")
    first_client, _ = _client(tmp_path, counter)
    first_client.complete([{"role": "user", "content": "hi"}])

    second_client, _ = _client(tmp_path, counter)
    result = second_client.complete([{"role": "user", "content": "hi"}])

    assert counter.count == 1
    assert result.content == "persisted"


def test_failed_call_is_not_cached(tmp_path: Path) -> None:
    """把失败写进缓存会让一次偶发故障永久生效。"""

    class _Boom:
        count = 0

        def __call__(self, request: httpx.Request) -> httpx.Response:
            self.count += 1
            return httpx.Response(400, json={"error": {"message": "bad"}})

    counter = _Boom()
    cache = ResponseCache(tmp_path / "responses.db")
    client = LLMClient(
        settings=_settings(tmp_path),
        client=httpx.Client(transport=httpx.MockTransport(counter)),
        response_cache=cache,
        max_retries=0,
        backoff_seconds=0.0,
    )

    with pytest.raises(httpx.HTTPStatusError):
        client.complete([{"role": "user", "content": "hi"}])

    assert cache.stats()[0] == 0
