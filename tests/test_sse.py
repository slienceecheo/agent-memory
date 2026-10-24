"""SSE 收拢的行为契约。

真实网关即使 `stream=false` 也只返回分块。这些测试锁定四种形态，
其中"中断"必须报错——截断正文会让抽取静默产出半句话。
"""

from __future__ import annotations

import pytest

from memory.llm.sse import IncompleteStreamError, collect


def _chunk(payload: str, *, prefix: str = "data:") -> str:
    return f"{prefix}{payload}\n\n"


def test_single_complete_chunk() -> None:
    """只返一个完整分块时也要能解析，不能假定一定有多块。"""
    raw = _chunk('{"choices":[{"delta":{"content":"PONG"}}]}') + _chunk("[DONE]")

    result = collect(raw)

    assert result.content == "PONG"


def test_multiple_chunks_are_concatenated() -> None:
    """漏掉拼接会让正文只剩最后一段。"""
    raw = (
        _chunk('{"choices":[{"delta":{"content":"Hel"}}]}')
        + _chunk('{"choices":[{"delta":{"content":"lo"}}]}')
        + _chunk("[DONE]")
    )

    assert collect(raw).content == "Hello"


def test_reasoning_content_is_separated_from_content() -> None:
    """把推理混进正文会污染下游抽取结果。"""
    raw = (
        _chunk('{"choices":[{"delta":{"reasoning_content":"想一想"}}]}')
        + _chunk('{"choices":[{"delta":{"reasoning_content":"再想想"}}]}')
        + _chunk('{"choices":[{"delta":{"content":"答案"}}]}')
        + _chunk("[DONE]")
    )

    result = collect(raw)

    assert result.content == "答案"
    assert result.reasoning == "想一想再想想"


def test_usage_is_captured_from_final_chunk() -> None:
    """丢掉 usage 就无法报告 token 成本与推理浪费比例。"""
    raw = (
        _chunk('{"choices":[{"delta":{"content":"x"}}]}')
        + _chunk(
            '{"choices":[{"delta":{},"finish_reason":"stop"}],'
            '"usage":{"prompt_tokens":10,"completion_tokens":2,"total_tokens":12,'
            '"completion_tokens_details":{"reasoning_tokens":7}}}'
        )
        + _chunk("[DONE]")
    )

    result = collect(raw)

    assert result.usage.prompt_tokens == 10
    assert result.usage.completion_tokens == 2
    assert result.usage.reasoning_tokens == 7


def test_finish_reason_is_captured() -> None:
    """没有 finish_reason 就无法区分正常结束与被截断。"""
    raw = (
        _chunk('{"choices":[{"delta":{"content":"x"},"finish_reason":"length"}]}')
        + _chunk("[DONE]")
    )

    assert collect(raw).finish_reason == "length"


def test_stream_without_done_marker_raises() -> None:
    """中断若被当成正常结束，正文会被静默截断。"""
    raw = _chunk('{"choices":[{"delta":{"content":"半个句"}}]}')

    with pytest.raises(IncompleteStreamError, match="结束标记"):
        collect(raw)


def test_blank_lines_and_comment_lines_are_ignored() -> None:
    """SSE 允许心跳注释，解析器不能因此报错。"""
    raw = (
        ": keep-alive\n\n"
        + _chunk('{"choices":[{"delta":{"content":"ok"}}]}')
        + _chunk("[DONE]")
    )

    assert collect(raw).content == "ok"


def test_malformed_json_chunk_raises_readable_error() -> None:
    """抛出裸 JSONDecodeError 会让人无法定位是哪个分块坏了。"""
    raw = _chunk("{not json") + _chunk("[DONE]")

    with pytest.raises(IncompleteStreamError, match="无法解析"):
        collect(raw)


def test_empty_delta_is_tolerated() -> None:
    """首个分块常常是空 delta，不能因此中断。"""
    raw = (
        _chunk('{"choices":[{"delta":{}}]}')
        + _chunk('{"choices":[{"delta":{"content":"x"}}]}')
        + _chunk("[DONE]")
    )

    assert collect(raw).content == "x"


def test_tool_calls_are_aggregated() -> None:
    """工具调用参数是分片下发的，漏拼会得到残缺 JSON。"""
    raw = (
        _chunk(
            '{"choices":[{"delta":{"tool_calls":[{"index":0,"id":"call_1",'
            '"type":"function","function":{"name":"record","arguments":""}}]}}]}'
        )
        + _chunk('{"choices":[{"delta":{"tool_calls":[{"index":0,'
        '"function":{"arguments":"{\\"a\\":"}}]}}]}')
        + _chunk('{"choices":[{"delta":{"tool_calls":[{"index":0,'
        '"function":{"arguments":"1}"}}]}}]}')
        + _chunk("[DONE]")
    )

    result = collect(raw)

    assert len(result.tool_calls) == 1
    assert result.tool_calls[0].name == "record"
    assert result.tool_calls[0].arguments == '{"a":1}'
