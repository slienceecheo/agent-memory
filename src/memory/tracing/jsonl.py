"""JSONL 追踪实现。

每行一个完整 JSON 对象，追加写入。字段固定，因为 C7 的 UI 与 Langfuse 导入
都依赖这个格式。
"""

from __future__ import annotations

import json
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from memory.tracing.base import Span

_STAGES = frozenset({"load", "embed", "generate", "score", "resolve"})


class _JsonlSpan(Span):
    def __init__(self, *, network_calls: int = 0) -> None:
        self.prompt_tokens = 0
        self.completion_tokens = 0
        self.reasoning_tokens = 0
        self.error: str | None = None
        self.network_calls = network_calls
        self._hint: float | None = None

    def add_network_call(self) -> None:
        self.network_calls += 1

    def duration_hint(self, seconds: float) -> None:
        self._hint = seconds


class JsonlTracer:
    def __init__(self, path: Path | str, *, run_id: str) -> None:
        self._path = Path(path)
        self._run_id = run_id
        self._path.parent.mkdir(parents=True, exist_ok=True)

    @contextmanager
    def span(
        self, stage: str, *, sample_id: str | None = None, network_calls: int = 0
    ) -> Iterator[_JsonlSpan]:
        if stage not in _STAGES:
            raise ValueError(
                f"未知 stage {stage!r}；可用值：{', '.join(sorted(_STAGES))}"
            )

        span = _JsonlSpan(network_calls=network_calls)
        started = time.perf_counter()
        try:
            yield span
        except Exception as exc:
            span.error = f"{type(exc).__name__}: {exc}"
            raise
        finally:
            if span._hint is not None:
                duration_ms = span._hint * 1000
            else:
                duration_ms = (time.perf_counter() - started) * 1000
            self._write(
                {
                    "run_id": self._run_id,
                    "sample_id": sample_id,
                    "stage": stage,
                    "duration_ms": round(duration_ms, 3),
                    "network_calls": span.network_calls,
                    "prompt_tokens": span.prompt_tokens,
                    "completion_tokens": span.completion_tokens,
                    "reasoning_tokens": span.reasoning_tokens,
                    "error": span.error,
                }
            )

    def _write(self, event: dict[str, object]) -> None:
        line = json.dumps(event, ensure_ascii=False)
        with self._path.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(line + "\n")
