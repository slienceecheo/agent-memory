"""SSE 分块收拢。

本地网关即使 `stream=false` 也只返回 `data:` 分块，所以必须自己拼装。
解析只依赖两个约定：`data:` 前缀与 `[DONE]` 结束标记，不依赖字段顺序。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field

_DONE_MARKER = "[DONE]"


class IncompleteStreamError(RuntimeError):
    """响应不完整或无法解析。绝不能被当成"正常结束"。"""


@dataclass(frozen=True, slots=True)
class Usage:
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    reasoning_tokens: int = 0


@dataclass(frozen=True, slots=True)
class ToolCall:
    id: str
    name: str
    arguments: str


@dataclass(slots=True)
class CollectedResponse:
    content: str = ""
    reasoning: str = ""
    finish_reason: str | None = None
    usage: Usage = field(default_factory=Usage)
    tool_calls: list[ToolCall] = field(default_factory=list)


def collect(raw: str) -> CollectedResponse:
    """把 SSE 原始文本收拢成一条完整响应。

    `finish_reason` 取最后一次非空值：网关常在同一响应里重复下发 stop。
    """
    response = CollectedResponse()
    partial_tool_calls: dict[int, dict[str, str]] = {}
    saw_done = False

    for line in raw.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith(":"):
            continue
        if not stripped.startswith("data:"):
            continue

        payload = stripped[len("data:") :].strip()
        if payload == _DONE_MARKER:
            saw_done = True
            continue

        try:
            event = json.loads(payload)
        except json.JSONDecodeError as exc:
            raise IncompleteStreamError(
                f"无法解析分块（前 80 字符）：{payload[:80]!r}"
            ) from exc

        _apply_event(event, response, partial_tool_calls)

    if not saw_done:
        raise IncompleteStreamError(
            "分块流在结束标记 [DONE] 出现前中断，正文可能被截断；已拒绝返回不完整结果。"
        )

    response.tool_calls = [
        ToolCall(id=item["id"], name=item["name"], arguments=item["arguments"])
        for _, item in sorted(partial_tool_calls.items())
    ]
    return response


def _apply_event(
    event: dict[str, object],
    response: CollectedResponse,
    partial_tool_calls: dict[int, dict[str, str]],
) -> None:
    choices = event.get("choices")
    if isinstance(choices, list):
        for choice in choices:
            if not isinstance(choice, dict):
                continue
            delta = choice.get("delta")
            if isinstance(delta, dict):
                content = delta.get("content")
                if isinstance(content, str):
                    response.content += content
                reasoning = delta.get("reasoning_content")
                if isinstance(reasoning, str):
                    response.reasoning += reasoning
                _accumulate_tool_calls(delta.get("tool_calls"), partial_tool_calls)
            finish_reason = choice.get("finish_reason")
            if isinstance(finish_reason, str) and finish_reason:
                response.finish_reason = finish_reason

    usage = event.get("usage")
    if isinstance(usage, dict):
        details = usage.get("completion_tokens_details")
        reasoning_tokens = 0
        if isinstance(details, dict):
            raw_reasoning = details.get("reasoning_tokens")
            if isinstance(raw_reasoning, int):
                reasoning_tokens = raw_reasoning
        response.usage = Usage(
            prompt_tokens=_as_int(usage.get("prompt_tokens")),
            completion_tokens=_as_int(usage.get("completion_tokens")),
            total_tokens=_as_int(usage.get("total_tokens")),
            reasoning_tokens=reasoning_tokens,
        )


def _accumulate_tool_calls(
    raw_calls: object, partial: dict[int, dict[str, str]]
) -> None:
    if not isinstance(raw_calls, list):
        return
    for raw in raw_calls:
        if not isinstance(raw, dict):
            continue
        index = raw.get("index")
        if not isinstance(index, int):
            continue
        slot = partial.setdefault(index, {"id": "", "name": "", "arguments": ""})
        raw_id = raw.get("id")
        if isinstance(raw_id, str) and raw_id:
            slot["id"] = raw_id
        function = raw.get("function")
        if isinstance(function, dict):
            name = function.get("name")
            if isinstance(name, str) and name:
                slot["name"] = name
            arguments = function.get("arguments")
            if isinstance(arguments, str):
                slot["arguments"] += arguments


def _as_int(value: object) -> int:
    return value if isinstance(value, int) else 0
