"""C3 报告与结果 JSON 的一致性检查。

报告是手写的，JSON 是程序产出的。两者不一致时报告就是错的，
而错误的数字比没有数字更糟。

本文件还锁定报告里三个**不能漂移**的论断：
1. 四个组合都是满分（若有人改坏了实现，这里会先失败）
2. 模型调用 17 次但差异为 0（这是"100% 不可信"的核心证据）
3. 规则覆盖率只有 3/20（决定模型兜底是否必需）
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from evals.datasets.conflict_set import load_conflict_set

from memory.resolver.change_marker import detect_by_rules

ROOT = Path(__file__).resolve().parents[2]
RESULTS = ROOT / "results"
REPORT = ROOT / "docs" / "reports" / "c3-resolver.md"


def _load(name: str) -> dict[str, object]:
    path = RESULTS / f"{name}.json"
    if not path.exists():
        pytest.skip(f"结果文件缺失：{path}")
    return json.loads(path.read_text(encoding="utf-8"))


def test_report_exists() -> None:
    assert REPORT.exists()


@pytest.mark.parametrize(
    "name",
    [
        "conflict-test-full",
        "conflict-test-no-llm",
        "conflict-dev-full",
        "conflict-dev-no-llm",
    ],
)
def test_all_four_combinations_are_full_marks(name: str) -> None:
    """报告声称四个组合都是满分。若实现被改坏，这条先失败。"""
    payload = _load(name)

    assert payload["macro_f1"] == pytest.approx(1.0), (
        f"{name} 的 macro-F1 不再是 1.0，报告的第 0 节需要重写"
    )


def test_llm_makes_no_difference_on_test_split() -> None:
    """这是"100% 不可信"的核心证据；若差异出现，说明场景或规则变了。"""
    full = _load("conflict-test-full")
    no_llm = _load("conflict-test-no-llm")

    assert full["macro_f1"] == no_llm["macro_f1"]


def test_rule_coverage_is_three_of_twenty() -> None:
    """规则覆盖率只有 3/20 —— 决定模型兜底是否必需的关键数字。"""
    dataset = load_conflict_set(ROOT / "data" / "conflict-set" / "test.jsonl")

    hits = sum(1 for case in dataset.cases if detect_by_rules(case.text) is not None)

    assert hits == 3, f"规则命中数实际为 {hits}，报告写的是 3"


def test_llm_call_count_is_seventeen() -> None:
    """17 次调用但结论从未改变结果。"""
    class _Counting:
        def __init__(self) -> None:
            self.calls = 0

        def complete(self, messages: object, **kwargs: object) -> object:
            from memory.llm.client import LLMResult
            from memory.llm.sse import Usage

            self.calls += 1
            return LLMResult(
                content='{"is_new_state": true}', usage=Usage(), finish_reason="stop"
            )

    from memory.resolver.change_marker import detect_change

    dataset = load_conflict_set(ROOT / "data" / "conflict-set" / "test.jsonl")
    llm = _Counting()
    for case in dataset.cases:
        detect_change(case.text, llm=llm, allow_llm=True)

    assert llm.calls == 17, f"模型调用数实际为 {llm.calls}，报告写的是 17"


def test_label_confirmation_progress_matches_report() -> None:
    """报告声称 60/60 已确认。若进度变了，报告需要更新。"""
    dev = load_conflict_set(ROOT / "data" / "conflict-set" / "dev.jsonl")
    test = load_conflict_set(ROOT / "data" / "conflict-set" / "test.jsonl")

    confirmed = len(dev.confirmed()) + len(test.confirmed())

    assert confirmed == 60, (
        f"已确认数实际为 {confirmed}，报告写的是 60。"
        "若标签有变动，请更新报告并重跑评测。"
    )


def test_annotation_copies_are_fully_confirmed() -> None:
    """两份副本都必须标完，否则 κ 的样本量不完整。"""
    for name in ("test.alice.jsonl", "test.bob.jsonl"):
        path = ROOT / "data" / "conflict-set" / name
        if not path.exists():
            pytest.skip(f"{name} 不存在")
        dataset = load_conflict_set(path)
        assert len(dataset.confirmed()) == len(dataset) == 20, (
            f"{name} 有 {len(dataset.confirmed())}/{len(dataset)} 条已确认"
        )


def test_kappa_between_annotators() -> None:
    """报告声称三对 κ 都是 1.000。若标签变动，这里先失败。"""
    from evals.tools.label import kappa_from_files

    data = ROOT / "data" / "conflict-set"
    pairs = [
        (data / "test.jsonl", data / "test.alice.jsonl"),
        (data / "test.jsonl", data / "test.bob.jsonl"),
        (data / "test.alice.jsonl", data / "test.bob.jsonl"),
    ]
    for left, right in pairs:
        if not (left.exists() and right.exists()):
            pytest.skip(f"{left.name} 或 {right.name} 不存在")
        result = kappa_from_files(left, right)
        assert result.kappa == pytest.approx(1.0), (
            f"{left.name} vs {right.name} 的 κ 为 {result.kappa:.3f}，报告写的是 1.000"
        )


def test_report_states_the_independence_caveat() -> None:
    """κ = 1.000 必须附带"同源复核"的保留意见，否则会被当成独立双标注。"""
    text = REPORT.read_text(encoding="utf-8")

    assert "同源复核" in text
    assert "非零分歧" in text


def test_conflict_pairs_are_not_merge_candidates() -> None:
    """CONFLICT 的一对值不能被规则判成 MERGE。

    注意不能简单断言"两个值互不为子串"：中文里否定词会让短串成为长串的子串
    （"能吃海鲜" 是 "不能吃海鲜" 的子串），但语义上它们是互斥的。
    正确的检查是**跑一遍规则**，确认它不是 MERGE。
    """
    from memory.resolver.rules import Candidate, ExistingSnapshot, decide_by_rules

    for split in ("dev", "test"):
        dataset = load_conflict_set(ROOT / "data" / "conflict-set" / f"{split}.jsonl")
        for case in dataset.cases:
            if case.expected.value != "CONFLICT":
                continue
            decision = decide_by_rules(
                Candidate(
                    subject=case.subject,
                    relation=case.relation,
                    value=case.candidate_value,
                    condition=case.condition,
                    authority=case.authority,  # type: ignore[arg-type]
                ),
                existing=ExistingSnapshot(
                    id="seed",
                    subject=case.subject,
                    relation=case.relation,
                    value=case.existing_value or "",
                    condition=case.existing_condition,
                ),
            )
            assert decision.kind.value == "CONFLICT", (
                f"{case.id} 被判成 {decision.kind.value}（规则 {decision.rule}），"
                "不是 CONFLICT"
            )


def test_report_documents_the_conflict_repair() -> None:
    """修正记录必须留在报告与实现文档里，否则下次还会犯同样的错。"""
    report = REPORT.read_text(encoding="utf-8")
    design_doc = (ROOT / "docs" / "resolver.md").read_text(encoding="utf-8")

    for doc in (report, design_doc):
        assert "dev-conf-01" in doc
        assert "互斥" in doc


def test_report_states_the_caveat() -> None:
    """报告必须同时写出"自写集 100% 不可信"与"独立集才是真实位置"。"""
    text = REPORT.read_text(encoding="utf-8")

    assert "循环论证" in text
    assert "50.0%" in text, "报告必须给出独立集的实际分数"
    assert "held-out" in text
    assert "自写" in text


def test_normalized_false_is_zero_after_alias_fix() -> None:
    """补了 dietary_restriction 别名后，归一化失败应为 0。"""
    payload = _load("conflict-test-no-llm")

    assert payload["normalized_false"] == 0, (
        "仍有输入未走别名表，需要补充词表或说明原因"
    )
