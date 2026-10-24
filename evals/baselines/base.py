"""基线的公共部分。

`answer()` 是三条基线**唯一**的生成入口。这是刻意的：
如果每条基线自己拼 prompt，分数差异就无法归因到"上下文构造方式"。
"""

from __future__ import annotations

import time
from collections.abc import Sequence
from typing import Literal

from evals.types import SampleResult
from memory.tracing.base import Tracer

Strategy = Literal["none", "full", "rag"]

SYSTEM_PROMPT = (
    "You answer questions using only the provided facts. "
    "Reply with the answer only, no explanation."
)


def render_context(facts: Sequence[str], *, strategy: Strategy) -> str:
    """把事实列表渲染成上下文。这是三条基线唯一的差别所在。"""
    if strategy == "none":
        return ""
    if strategy == "full":
        return "\n".join(facts)
    raise ValueError(f"rag 策略需要检索器，不能直接调用 render_context( strategy={strategy!r} )")


def build_user_prompt(question: str, context: str) -> str:
    if not context:
        return f"Question: {question}"
    return f"Facts:\n{context}\n\nQuestion: {question}"


def answer(
    llm: object,
    *,
    question: str,
    context: str,
) -> tuple[str, int, int, int, int]:
    """调用模型并返回 (正文, prompt_tokens, completion_tokens, reasoning_tokens, retries)。"""
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": build_user_prompt(question, context)},
    ]
    result = llm.complete(messages)  # type: ignore[attr-defined]
    return (
        result.content,
        result.usage.prompt_tokens,
        result.usage.completion_tokens,
        result.usage.reasoning_tokens,
        result.retries,
    )


class Baseline:
    """所有基线的共同骨架：决定上下文 → 调用共用 answer() → 记录结果。"""

    name: str = "base"
    strategy: Strategy = "none"

    def __init__(self, *, llm: object, tracer: Tracer, **_: object) -> None:
        self._llm = llm
        self._tracer = tracer

    def _context(self, question: str, facts: Sequence[str]) -> str:
        return render_context(facts, strategy=self.strategy)

    def run(
        self,
        *,
        question: str,
        facts: Sequence[str],
        sample_id: str,
        gold: str = "",
    ) -> SampleResult:
        from memory.eval.metrics import substring_exact_match

        started = time.perf_counter()
        try:
            with self._tracer.span("generate", sample_id=sample_id) as span:
                context = self._context(question, facts)
                prediction, prompt_tokens, completion_tokens, reasoning_tokens, retries = (
                    answer(self._llm, question=question, context=context)
                )
                span.prompt_tokens = prompt_tokens
                span.completion_tokens = completion_tokens
                span.reasoning_tokens = reasoning_tokens
                span.add_network_call()
                if retries:
                    span.network_calls += retries
        except Exception as exc:
            return SampleResult(
                sample_id=sample_id,
                question=question,
                gold=gold,
                prediction="",
                correct=False,
                error=f"{type(exc).__name__}: {exc}",
            )

        correct = substring_exact_match(gold, prediction) if gold.strip() else False
        elapsed_ms = (time.perf_counter() - started) * 1000
        _ = elapsed_ms  # 时长由 tracer 记录，这里保留便于将来做样本级延迟统计
        return SampleResult(
            sample_id=sample_id,
            question=question,
            gold=gold,
            prediction=prediction,
            correct=correct,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            reasoning_tokens=reasoning_tokens,
            error=None,
        )
