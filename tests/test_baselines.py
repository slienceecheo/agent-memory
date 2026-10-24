"""三条基线的行为契约。

最关键的约束：三条基线只在"给模型看什么上下文"上不同，生成与匹配逻辑完全共用。
否则分数差异无法归因。
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path

import pytest
from evals.baselines import BASELINES, UnknownBaselineError, build_baseline
from evals.baselines.base import render_context
from evals.types import BaselineResult, SampleResult

from memory.llm.client import LLMResult
from memory.llm.sse import Usage
from memory.tracing.jsonl import JsonlTracer

FACTS = [
    "0. Amy Winehouse died in the city of Camden Town.",
    "1. Hines Ward plays the position of wide receiver.",
    "2. Amy Winehouse died in the city of London.",
]


class _RecorderLLM:
    """记录每次请求的 messages，返回固定答案。"""

    def __init__(self, answer_text: str = "London") -> None:
        self.answer_text = answer_text
        self.calls: list[list[dict[str, str]]] = []

    def complete(
        self,
        messages: Sequence[dict[str, str]] | Sequence[object],
        **_: object,
    ) -> LLMResult:
        normalized = [dict(message) for message in messages]  # type: ignore[arg-type]
        self.calls.append(normalized)
        return LLMResult(
            content=self.answer_text,
            usage=Usage(prompt_tokens=10, completion_tokens=2, total_tokens=12),
            finish_reason="stop",
        )


def test_render_context_includes_all_facts_for_full_context() -> None:
    """full-context 必须把所有事实都塞进去，否则它就不是上界基线。"""
    rendered = render_context(FACTS, strategy="full")

    for fact in FACTS:
        assert fact in rendered


def test_render_context_empty_for_no_memory() -> None:
    """no-memory 给空上下文；若偷偷塞了事实，它就不再是下界基线。"""
    assert render_context(FACTS, strategy="none") == ""


def test_three_baselines_share_the_same_answer_function(tmp_path: Path) -> None:
    """若各基线自己实现生成逻辑，分数差异就无法归因到上下文构造。"""
    llm = _RecorderLLM("London")

    tracer = JsonlTracer(tmp_path / "events.jsonl", run_id="r")
    outcomes = [
        build_baseline(name, llm=llm, tracer=tracer).run(
            question="Where did Amy Winehouse die?",
            facts=FACTS,
            sample_id="s1",
        )
        for name in BASELINES
    ]

    assert {outcome.prediction for outcome in outcomes} == {"London"}
    # 三次调用都走同一个 prompt 模板：系统提示词与问题部分应完全一致
    system_prompts = {call[0]["content"] for call in llm.calls}
    assert len(system_prompts) == 1


def test_system_prompt_does_not_leak_the_conflict_rule(tmp_path: Path) -> None:
    """提示词若告诉模型"编号大者更新"，等于把核心方法免费送给基线。

    这会直接摧毁"确定性 resolver 有价值"的论证——基线不该知道解法。
    """
    tracer = JsonlTracer(tmp_path / "events.jsonl", run_id="r")
    llm = _RecorderLLM()
    baseline = build_baseline("naive-rag", llm=llm, tracer=tracer, top_k=1)

    baseline.run(question="q", facts=FACTS, sample_id="s1", gold="London")

    system_prompt = llm.calls[0][0]["content"].lower()
    for leak in ("larger number", "newer", "most recent", "latest"):
        assert leak not in system_prompt, f"系统提示词泄露了解法：{leak!r}"


def test_no_memory_sends_no_facts(tmp_path: Path) -> None:
    """no-memory 的上下文必须是空的，否则它不是真正的下界。"""
    llm = _RecorderLLM()
    baseline = build_baseline(
        "no-memory", llm=llm, tracer=JsonlTracer(tmp_path / "events.jsonl", run_id="r")
    )

    baseline.run(question="q", facts=FACTS, sample_id="s1")

    user_prompt = llm.calls[0][1]["content"]
    assert "Camden Town" not in user_prompt


def test_full_context_includes_facts_in_user_prompt(tmp_path: Path) -> None:
    llm = _RecorderLLM()
    baseline = build_baseline(
        "full-context", llm=llm, tracer=JsonlTracer(tmp_path / "events.jsonl", run_id="r")
    )

    baseline.run(question="q", facts=FACTS, sample_id="s1")

    user_prompt = llm.calls[0][1]["content"]
    assert "Camden Town" in user_prompt
    assert "wide receiver" in user_prompt


def test_naive_rag_retrieves_subset_not_everything(tmp_path: Path) -> None:
    """naive-rag 若把所有事实都塞进去，就退化成 full-context，失去对照意义。"""
    llm = _RecorderLLM()
    baseline = build_baseline(
        "naive-rag",
        llm=llm,
        tracer=JsonlTracer(tmp_path / "events.jsonl", run_id="r"),
        top_k=1,
    )

    baseline.run(
        question="Which sport is Hines Ward associated with?", facts=FACTS, sample_id="s1"
    )

    user_prompt = llm.calls[0][1]["content"]
    assert "Hines Ward" in user_prompt
    assert "Camden Town" not in user_prompt


def test_unknown_baseline_lists_available_names(tmp_path: Path) -> None:
    """名字打错时列出可用项，比抛 KeyError 好查得多。"""
    with pytest.raises(UnknownBaselineError) as excinfo:
        build_baseline(
            "no-mem", llm=_RecorderLLM(), tracer=JsonlTracer(tmp_path / "events.jsonl", run_id="r")
        )

    message = str(excinfo.value)
    assert "no-mem" in message
    for name in BASELINES:
        assert name in message


def test_result_is_matched_with_substring_exact_match(tmp_path: Path) -> None:
    """匹配逻辑若被改动，基线与 C4/C5 的分数就不再可比。"""
    llm = _RecorderLLM("The answer is London.")
    baseline = build_baseline(
        "no-memory", llm=llm, tracer=JsonlTracer(tmp_path / "events.jsonl", run_id="r")
    )

    outcome = baseline.run(question="q", facts=[], sample_id="s1", gold="London")

    assert outcome.correct is True


def test_result_records_token_usage(tmp_path: Path) -> None:
    """没有 token 数就无法做成本分析，也无法证明不是靠堆算力赢。"""
    llm = _RecorderLLM()
    baseline = build_baseline(
        "no-memory", llm=llm, tracer=JsonlTracer(tmp_path / "events.jsonl", run_id="r")
    )

    outcome = baseline.run(question="q", facts=[], sample_id="s1", gold="London")

    assert outcome.prompt_tokens == 10
    assert outcome.completion_tokens == 2


def test_failed_sample_is_marked_not_dropped(tmp_path: Path) -> None:
    """失败样本若从结果里消失，准确率会被静默抬高。"""
    class _Boom:
        def complete(self, *_args: object, **_kwargs: object) -> LLMResult:
            raise RuntimeError("model exploded")

    baseline = build_baseline(
        "no-memory", llm=_Boom(), tracer=JsonlTracer(tmp_path / "e.jsonl", run_id="r")
    )

    outcome = baseline.run(question="q", facts=[], sample_id="s1", gold="London")

    assert outcome.correct is False
    assert outcome.error is not None
    assert "model exploded" in outcome.error


def test_baseline_result_serializes(tmp_path: Path) -> None:
    """结果要落盘给报告用，序列化失败会让整次运行白跑。"""
    result = BaselineResult(
        baseline="no-memory",
        benchmark="factconsolidation",
        subset="factconsolidation_sh_6k",
        samples=[
            SampleResult(
                sample_id="s1",
                question="q",
                gold="London",
                prediction="London",
                correct=True,
                prompt_tokens=10,
                completion_tokens=2,
                reasoning_tokens=0,
                error=None,
            )
        ],
    )

    payload = json.loads(result.model_dump_json())

    assert payload["baseline"] == "no-memory"
    assert payload["samples"][0]["correct"] is True
