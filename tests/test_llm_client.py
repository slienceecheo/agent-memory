"""LLM 客户端的行为契约。

断言的是客户端自身：发了什么请求、怎么处理推理内容、错误如何分类与重试。
用 `httpx.MockTransport` 替代网络，但断言目标是真实组件的可观察行为。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx
import pytest

from memory.config import Settings
from memory.llm.client import LLMClient, ReasoningOnlyError, RetryExhaustedError

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


def _sse(*events: dict[str, Any], done: bool = True) -> bytes:
    lines = [f"data:{json.dumps(event)}\n\n" for event in events]
    if done:
        lines.append("data:[DONE]\n\n")
    return "".join(lines).encode()


def _delta(content: str = "", reasoning: str = "") -> dict[str, Any]:
    payload: dict[str, Any] = {}
    if content:
        payload["content"] = content
    if reasoning:
        payload["reasoning_content"] = reasoning
    return {"choices": [{"index": 0, "delta": payload}]}


def _usage(prompt: int, completion: int, reasoning: int) -> dict[str, Any]:
    return {
        "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
        "usage": {
            "prompt_tokens": prompt,
            "completion_tokens": completion,
            "total_tokens": prompt + completion,
            "completion_tokens_details": {"reasoning_tokens": reasoning},
        },
    }


class _Server:
    def __init__(self, responses: list[httpx.Response]) -> None:
        self._responses = responses
        self.requests: list[dict[str, Any]] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(json.loads(request.content))
        if not self._responses:
            raise AssertionError("收到超出预期的额外请求")
        return self._responses.pop(0)


def _client(cache_dir: Path, server: _Server, *, retries: int = 2) -> LLMClient:
    return LLMClient(
        settings=_settings(cache_dir),
        client=httpx.Client(transport=httpx.MockTransport(server)),
        max_retries=retries,
        backoff_seconds=0.0,
    )


def test_forced_stream_is_collected_into_full_text(tmp_path: Path) -> None:
    """若客户端假定普通 JSON，网关的强制分块会让它拿到空正文。"""
    server = _Server(
        [httpx.Response(200, content=_sse(_delta("PO"), _delta("NG"), _usage(5, 2, 0)))]
    )
    client = _client(tmp_path, server)

    result = client.complete([{"role": "user", "content": "hi"}])

    assert result.content == "PONG"


def test_client_always_requests_streaming(tmp_path: Path) -> None:
    """既然服务端总是返回分块，客户端就应显式按流式解析，避免依赖假设。"""
    server = _Server([httpx.Response(200, content=_sse(_delta("x"), _usage(1, 1, 0)))])
    client = _client(tmp_path, server)

    client.complete([{"role": "user", "content": "hi"}])

    assert server.requests[0]["stream"] is True


def test_reasoning_tokens_are_reported_and_content_excludes_reasoning(tmp_path: Path) -> None:
    """推理内容若混进正文会污染抽取；若不统计就无法报告浪费比例。"""
    server = _Server(
        [
            httpx.Response(
                200,
                content=_sse(_delta(reasoning="想一想"), _delta("答案"), _usage(10, 20, 15)),
            )
        ]
    )
    client = _client(tmp_path, server)

    result = client.complete([{"role": "user", "content": "hi"}])

    assert result.content == "答案"
    assert result.usage.reasoning_tokens == 15
    assert result.reasoning_waste_ratio == pytest.approx(15 / 20)


def test_no_reasoning_yields_zero_waste(tmp_path: Path) -> None:
    """把缺失当成"有推理"会虚报成本。"""
    server = _Server([httpx.Response(200, content=_sse(_delta("答案"), _usage(10, 4, 0)))])
    client = _client(tmp_path, server)

    result = client.complete([{"role": "user", "content": "hi"}])

    assert result.reasoning_waste_ratio == 0.0


def test_reasoning_only_response_raises(tmp_path: Path) -> None:
    """只有推理没有正文时若返回空串，抽取层会静默产出空事实。"""
    server = _Server(
        [httpx.Response(200, content=_sse(_delta(reasoning="想了很久"), _usage(10, 20, 20)))]
    )
    client = _client(tmp_path, server)

    with pytest.raises(ReasoningOnlyError, match="正文为空"):
        client.complete([{"role": "user", "content": "hi"}])


def test_reasoning_only_error_keeps_reasoning_for_debugging(tmp_path: Path) -> None:
    """排查时需要看到模型到底想了什么，否则无从定位。"""
    server = _Server(
        [httpx.Response(200, content=_sse(_delta(reasoning="想了很久"), _usage(10, 20, 20)))]
    )
    client = _client(tmp_path, server)

    with pytest.raises(ReasoningOnlyError) as excinfo:
        client.complete([{"role": "user", "content": "hi"}])

    assert "想了很久" in str(excinfo.value)


def test_rate_limit_is_retried(tmp_path: Path) -> None:
    """把 429 当致命错误会让整批评测在限流时全灭。"""
    server = _Server(
        [
            httpx.Response(429, json={"error": {"message": "slow down"}}),
            httpx.Response(200, content=_sse(_delta("ok"), _usage(1, 1, 0))),
        ]
    )
    client = _client(tmp_path, server)

    result = client.complete([{"role": "user", "content": "hi"}])

    assert result.content == "ok"
    assert result.retries == 1


def test_server_error_is_retried(tmp_path: Path) -> None:
    """5xx 多为瞬时故障，不重试会显著降低评测吞吐。"""
    server = _Server(
        [
            httpx.Response(503, text="unavailable"),
            httpx.Response(200, content=_sse(_delta("ok"), _usage(1, 1, 0))),
        ]
    )
    client = _client(tmp_path, server)

    assert client.complete([{"role": "user", "content": "hi"}]).retries == 1


def test_auth_error_is_not_retried(tmp_path: Path) -> None:
    """401 重试只是浪费配额，且会掩盖配置错误。"""
    server = _Server([httpx.Response(401, json={"error": {"message": "bad key"}})])
    client = _client(tmp_path, server, retries=3)

    with pytest.raises(httpx.HTTPStatusError):
        client.complete([{"role": "user", "content": "hi"}])

    assert len(server.requests) == 1


def test_bad_request_is_not_retried(tmp_path: Path) -> None:
    """参数非法重试也不会变好。"""
    server = _Server([httpx.Response(400, json={"error": {"message": "bad param"}})])
    client = _client(tmp_path, server, retries=3)

    with pytest.raises(httpx.HTTPStatusError):
        client.complete([{"role": "user", "content": "hi"}])

    assert len(server.requests) == 1


def test_retry_exhausted_reports_attempts(tmp_path: Path) -> None:
    """重试耗尽若只抛原始错误，无法判断是配置问题还是服务故障。"""
    server = _Server([httpx.Response(503, text="x") for _ in range(3)])
    client = _client(tmp_path, server, retries=2)

    with pytest.raises(RetryExhaustedError) as excinfo:
        client.complete([{"role": "user", "content": "hi"}])

    assert "3" in str(excinfo.value)
    assert len(server.requests) == 3


def test_tool_calls_are_returned(tmp_path: Path) -> None:
    """抽取层依赖工具调用；返回空列表会让它退化成纯文本解析。"""
    tool_event = {
        "choices": [
            {
                "index": 0,
                "delta": {
                    "tool_calls": [
                        {
                            "index": 0,
                            "id": "call_1",
                            "type": "function",
                            "function": {"name": "record", "arguments": '{"a":1}'},
                        }
                    ]
                },
            }
        ]
    }
    server = _Server([httpx.Response(200, content=_sse(tool_event, _usage(5, 5, 0)))])
    client = _client(tmp_path, server)

    result = client.complete([{"role": "user", "content": "hi"}])

    assert result.tool_calls[0].name == "record"
    assert result.tool_calls[0].arguments == '{"a":1}'


def test_network_call_counter_tracks_requests(tmp_path: Path) -> None:
    """A3 的门禁依赖这个计数器；不准就无法断言"第二次为 0"。"""
    server = _Server([httpx.Response(200, content=_sse(_delta("x"), _usage(1, 1, 0)))])
    client = _client(tmp_path, server)

    client.complete([{"role": "user", "content": "hi"}])

    assert client.network_calls == 1
