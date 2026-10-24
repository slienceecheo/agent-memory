"""追踪层协议。

设计意图：代码只依赖 `Tracer` 协议，不依赖 Langfuse SDK。
JSONL 是主路径（可提交、可 CI 校验），Langfuse 是展示层（C7 再接）。
"""

from __future__ import annotations

from contextlib import AbstractContextManager
from typing import Protocol, runtime_checkable


class Span(Protocol):
    """一个阶段的可变记录。字段语义见 tests/test_tracer.py 的 JSON Schema。"""

    prompt_tokens: int
    completion_tokens: int
    reasoning_tokens: int
    error: str | None

    def add_network_call(self) -> None: ...

    def duration_hint(self, seconds: float) -> None: ...


@runtime_checkable
class Tracer(Protocol):
    def span(
        self, stage: str, *, sample_id: str | None = None, network_calls: int = 0
    ) -> AbstractContextManager[Span]: ...
