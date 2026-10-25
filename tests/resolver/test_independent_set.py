"""独立场景集的加载与评测行为契约。

这批数据是 held-out，所以测试要锁住两件事：

1. **数据本身的完整性**：30 条、六类齐全、原作者的理由保留
2. **不允许被当成调参集**：基线分数被锁定，若有人改规则让分数上升，
   必须显式更新这条断言并说明理由——这等于强制"改规则要留痕"
"""

from __future__ import annotations

from pathlib import Path

import pytest
from evals.datasets.independent_set import (
    InvalidIndependentCase,
    load_independent_set,
    parse_independent_case,
)

from memory.resolver.rules import DecisionKind
from memory.store.models import Authority

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data" / "conflict-set" / "independent.jsonl"


def _row(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "id": "ind-x",
        "text": "测试",
        "subject": "user:default",
        "relation": "phone_number",
        "candidate_value": "new",
        "existing_value": "old",
        "expected": "SUPERSEDE",
        "authority": "user_direct",
        "existing_authority": "user_direct",
    }
    base.update(overrides)
    return base


# ---------- schema ----------


def test_missing_field_is_rejected() -> None:
    row = _row()
    del row["expected"]
    with pytest.raises(InvalidIndependentCase, match="expected"):
        parse_independent_case(row, where="test")


def test_invalid_expected_is_rejected() -> None:
    with pytest.raises(InvalidIndependentCase, match="expected"):
        parse_independent_case(_row(expected="MAYBE"), where="test")


def test_invalid_authority_is_rejected() -> None:
    with pytest.raises(InvalidIndependentCase, match="authority"):
        parse_independent_case(_row(authority="god"), where="test")


def test_invalid_confidence_is_rejected() -> None:
    """confidence 只允许"确定/不太确定"，这是原作者给出的两档。"""
    with pytest.raises(InvalidIndependentCase, match="confidence"):
        parse_independent_case(_row(confidence="也许"), where="test")


def test_empty_existing_becomes_none() -> None:
    case = parse_independent_case(_row(existing_value=""), where="test")
    assert case.existing_value is None


def test_existing_authority_is_required_and_preserved() -> None:
    """existing_authority 是这批数据的关键补充，不能被默认值吞掉。"""
    case = parse_independent_case(
        _row(authority="third_party", existing_authority="user_direct"), where="test"
    )
    assert case.authority is Authority.THIRD_PARTY
    assert case.existing_authority is Authority.USER_DIRECT


# ---------- 真实数据 ----------


def test_real_independent_set_loads() -> None:
    dataset = load_independent_set(DATA)

    assert len(dataset) == 30


def test_all_six_classes_present() -> None:
    """六类必须都有样本，否则 macro-F1 会跳过某些类。"""
    dataset = load_independent_set(DATA)
    counts = dataset.class_counts()

    for kind in DecisionKind:
        assert counts[kind] > 0, f"{kind.value} 在独立集中没有样本"


def test_rationale_is_preserved() -> None:
    """原作者的理由是这批数据最有价值的部分，不能丢。"""
    dataset = load_independent_set(DATA)

    assert all(case.rationale for case in dataset.cases)


def test_authority_is_not_all_user_direct() -> None:
    """如果权威全是 user_direct，说明结构化补充时丢掉了"谁说的"。

    这是此前评测的一个真实缺陷：existing 一律当 user_direct，
    导致"第三方 vs 第三方"被误判成"低 vs 高"。
    """
    dataset = load_independent_set(DATA)

    assert any(case.authority is not Authority.USER_DIRECT for case in dataset.cases)
    assert any(case.existing_authority is not Authority.USER_DIRECT for case in dataset.cases)


def test_condition_subset_is_four_branch_cases() -> None:
    """显式给出 condition 的只有 4 条 BRANCH。"""
    dataset = load_independent_set(DATA)
    subset = dataset.with_condition_extracted()

    assert len(subset) == 4
    assert all(case.expected is DecisionKind.BRANCH for case in subset.cases)


# ---------- held-out 纪律 ----------


def test_baseline_accuracy_is_locked() -> None:
    """基线分数被锁定：50.0%。

    这条断言的作用不是"防止分数下降"，而是**强制留痕**：
    任何人改规则让这个数字变化，都必须显式修改这里并说明理由。
    否则就会发生"悄悄在 held-out 上调参"。
    """
    from evals.run_independent import evaluate

    dataset = load_independent_set(DATA)
    result = evaluate(dataset, allow_llm=False)

    assert result["accuracy"] == pytest.approx(0.5, abs=0.0001), (
        f"独立集基线变了：{result['accuracy']:.4f}。"
        "若这是有意改规则带来的变化，请更新本断言并在报告中说明；"
        "若无意识变化，说明规则被改坏了。"
    )


def test_wrong_case_set_is_stable() -> None:
    """判错的条目集合被锁定，便于发现"修好一条又弄坏另一条"。"""
    from evals.run_independent import evaluate

    dataset = load_independent_set(DATA)
    result = evaluate(dataset, allow_llm=False)
    wrong = {case["id"] for case in result["per_case"] if not case["correct"]}

    assert wrong == {
        "ind-01", "ind-02", "ind-03", "ind-05", "ind-07", "ind-09",
        "ind-11", "ind-12", "ind-13", "ind-17", "ind-18", "ind-22",
        "ind-25", "ind-28", "ind-30",
    }


def test_all_branch_cases_are_correct() -> None:
    """4 条 BRANCH 全对——条件是人工给出的，说明判定逻辑本身可靠。

    这条是"分离两个问题"的关键：判定错 vs 条件抽取缺失。
    """

    from evals.run_independent import evaluate

    dataset = load_independent_set(DATA).with_condition_extracted()
    result = evaluate(dataset, allow_llm=False)

    assert result["accuracy"] == pytest.approx(1.0)


def test_confidence_field_distinguishes_sure_and_unsure() -> None:
    """原作者有两档把握程度，报告要能按它分层看错误分布。"""
    dataset = load_independent_set(DATA)
    unsure = [case for case in dataset.cases if case.confidence == "不太确定"]

    assert len(unsure) >= 3
