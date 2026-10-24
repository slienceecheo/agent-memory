"""网络调用计数的行为契约。

A3 的验收标准是"第二次运行网络调用数为 0"。这要求计数准确，
并且能被汇总成"整次运行"的级别——而不是每个组件各自报自己的。
"""

from __future__ import annotations

import json
from pathlib import Path

import httpx

from memory.config import Settings
from memory.embedding.cache import EmbeddingCache
from memory.embedding.dashscope import DashScopeEmbedder
from memory.llm.client import LLMClient
from memory.tracing.jsonl import JsonlTracer


def _settings(cache_dir: Path) -> Settings:
    return Settings(
        llm_base_url="http://127.0.0.1:3211/api/open-platform-model/v1",
        llm_api_key="local",
        llm_model="deepseek-v4.1-flash",
        dashscope_api_key="sk-test",
        embedding_base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        embedding_model="qwen3.7-text-embedding-flash",
        embedding_dims=2,
        http_proxy=None,
        https_proxy=None,
        no_proxy="127.0.0.1,localhost",
        cache_dir=cache_dir,
    )


def _sse(content: str) -> bytes:
    event = {"choices": [{"index": 0, "delta": {"content": content}}]}
    usage = {
        "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
    }
    return (
        f"data:{json.dumps(event)}\n\ndata:{json.dumps(usage)}\n\ndata:[DONE]\n\n"
    ).encode()


class _Counter:
    def __init__(self) -> None:
        self.count = 0

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.count += 1
        if request.url.path.endswith("/embeddings"):
            body = json.loads(request.content)
            return httpx.Response(
                200,
                json={
                    "data": [
                        {"index": i, "embedding": [1.0] * 2}
                        for i in range(len(body["input"]))
                    ]
                },
            )
        return httpx.Response(200, content=_sse("ok"))


def _embedder(settings: Settings, counter: _Counter) -> DashScopeEmbedder:
    return DashScopeEmbedder(
        settings=settings,
        cache=EmbeddingCache(settings.cache_dir / "cache.db"),
        client=httpx.Client(transport=httpx.MockTransport(counter)),
    )


def _llm(settings: Settings, counter: _Counter) -> LLMClient:
    return LLMClient(
        settings=settings,
        client=httpx.Client(transport=httpx.MockTransport(counter)),
        max_retries=0,
        backoff_seconds=0.0,
    )


def test_embedder_counts_network_calls(tmp_path: Path) -> None:
    """计数若只统计成功调用，失败重试会被漏掉。"""
    settings = _settings(tmp_path)
    counter = _Counter()
    embedder = _embedder(settings, counter)

    embedder.embed_documents(["a"])
    embedder.embed_documents(["b"])

    assert embedder.network_calls == 2
    assert counter.count == 2


def test_warm_embedding_cache_makes_zero_network_calls(tmp_path: Path) -> None:
    """这是 A3 的核心断言：热缓存下必须一次网络都不打。"""
    settings = _settings(tmp_path)
    counter = _Counter()
    _embedder(settings, counter).embed_documents(["a", "b"])
    assert counter.count == 1

    warm = _embedder(settings, counter)
    warm.embed_documents(["a", "b"])

    assert warm.network_calls == 0
    assert counter.count == 1


def test_llm_client_counts_network_calls(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    counter = _Counter()
    llm = _llm(settings, counter)

    llm.complete([{"role": "user", "content": "hi"}])

    assert llm.network_calls == 1


def test_tracer_accumulates_calls_per_span(tmp_path: Path) -> None:
    """把两个组件的调用记进同一个 span，才能报告"这次样本打了几次网络"。"""
    settings = _settings(tmp_path)
    counter = _Counter()
    tracer = JsonlTracer(tmp_path / "events.jsonl", run_id="run-1")

    with tracer.span("embed", sample_id="s1") as span:
        _embedder(settings, counter).embed_documents(["a"])
        span.add_network_call()
        _llm(settings, counter).complete([{"role": "user", "content": "hi"}])
        span.add_network_call()

    event = json.loads((tmp_path / "events.jsonl").read_text(encoding="utf-8").strip())
    assert event["network_calls"] == 2


def test_span_with_no_calls_records_zero(tmp_path: Path) -> None:
    """漏记会报成 0 而看起来"没打网络"，必须靠真实计数器区分。"""
    tracer = JsonlTracer(tmp_path / "events.jsonl", run_id="run-1")

    with tracer.span("score", sample_id="s1"):
        pass

    event = json.loads((tmp_path / "events.jsonl").read_text(encoding="utf-8").strip())
    assert event["network_calls"] == 0
