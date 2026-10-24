"""真实网关冒烟测试。

默认被排除。手动运行：
    uv run pytest tests/test_llm_live.py -q -m network

它验证的是"我们的收拢逻辑与真实网关对得上"，以及推理浪费比例确实可观。
"""

from __future__ import annotations

import pytest

from memory.config import Settings
from memory.llm.client import LLMClient


@pytest.fixture
def live_client() -> LLMClient:
    return LLMClient(settings=Settings.load(), max_retries=1, backoff_seconds=0.0)


@pytest.mark.network
def test_non_streaming_request_still_returns_text(live_client: LLMClient) -> None:
    """网关无视 stream=false；若客户端不自行收拢，这里会拿到空正文。"""
    result = live_client.complete([{"role": "user", "content": "只回复：PONG"}])

    assert "PONG" in result.content.upper()


@pytest.mark.network
def test_reasoning_tokens_are_observed(live_client: LLMClient) -> None:
    """实测推理 token 占大头；若统计不到，说明字段名对不上。"""
    result = live_client.complete(
        [{"role": "user", "content": "9.11 和 9.9 哪个大？只回复答案。"}]
    )

    assert result.usage.completion_tokens > 0
    assert 0.0 <= result.reasoning_waste_ratio <= 1.0


@pytest.mark.network
def test_tool_calling_works(live_client: LLMClient) -> None:
    """抽取层依赖工具调用；这里只验证通道可用，不验证选择质量。"""
    tools = [
        {
            "type": "function",
            "function": {
                "name": "record_memory",
                "description": "记录一条记忆事实",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "subject": {"type": "string"},
                        "relation": {"type": "string"},
                        "value": {"type": "string"},
                    },
                    "required": ["subject", "relation", "value"],
                },
            },
        }
    ]
    result = live_client.complete(
        [{"role": "user", "content": "记录一下：这个仓库从今天起改用 npm。"}],
        tools=tools,
    )

    assert result.tool_calls, "网关未返回工具调用"
    assert result.tool_calls[0].name == "record_memory"
