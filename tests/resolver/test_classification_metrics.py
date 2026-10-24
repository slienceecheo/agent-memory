"""分类质量指标的行为契约。

为什么不能只报总体准确率：六类里 CONFLICT 只有 6 条，
即使全判错，总体准确率也只掉 10 个百分点，完全被掩盖。
macro-F1 让每个类别等权，稀有类的失败会直接反映出来。
"""

from __future__ import annotations

import pytest
from evals.metrics.classification import (
    confusion_matrix,
    macro_f1,
    per_class_f1,
)

from memory.resolver.rules import DecisionKind

KINDS = list(DecisionKind)


def test_perfect_classification() -> None:
    gold = [kind.value for kind in KINDS for _ in range(2)]
    pred = list(gold)

    report = macro_f1(gold, pred)

    assert report.value == pytest.approx(1.0)
    assert report.classes_evaluated == 6


def test_confusion_matrix_orientation() -> None:
    """行=期望，列=预测。搞反会让报告误导读者。"""
    gold = ["NOOP", "ADD"]
    pred = ["NOOP", "MERGE"]

    matrix = confusion_matrix(gold, pred)

    assert matrix["NOOP"]["NOOP"] == 1
    assert matrix["ADD"]["MERGE"] == 1
    assert matrix["ADD"]["ADD"] == 0


def test_rare_class_failure_drags_macro_f1() -> None:
    """这是 macro-F1 存在的理由：稀有类的失败不能被多数类淹没。

    构造：CONFLICT 只出现 3 次且全判错，其余全对。
    总体准确率会很高（>0.8），但 macro-F1 应显著更低。
    """
    gold: list[str] = []
    pred: list[str] = []
    for kind in KINDS:
        count = 3 if kind is DecisionKind.CONFLICT else 30
        gold.extend([kind.value] * count)
        predicted = "NOOP" if kind is DecisionKind.CONFLICT else kind.value
        pred.extend([predicted] * count)

    accuracy = sum(1 for g, p in zip(gold, pred, strict=True) if g == p) / len(gold)
    report = macro_f1(gold, pred)

    assert accuracy > 0.8
    assert report.value < 0.85
    assert report.value < accuracy


def test_absent_class_is_excluded_from_macro() -> None:
    """某类没有样本时不能当成 0 分拉低整体，也不能算作满分。

    正确做法是从分母里排除。
    """
    gold = ["NOOP"] * 4 + ["ADD"] * 4
    pred = ["NOOP"] * 4 + ["ADD"] * 4

    report = macro_f1(gold, pred)

    assert report.classes_evaluated == 2
    assert report.value == pytest.approx(1.0)
    assert DecisionKind.CONFLICT in report.absent_classes


def test_two_of_three_present_classes() -> None:
    gold = ["NOOP", "NOOP", "ADD", "ADD"]
    pred = ["NOOP", "ADD", "ADD", "ADD"]

    report = macro_f1(gold, pred)

    # NOOP: TP=1 FP=0 FN=1 → P=1.0 R=0.5 F1=0.667
    # ADD: TP=2 FP=1 FN=0 → P=0.667 R=1.0 F1=0.8
    assert per_class_f1(gold, pred)["NOOP"] == pytest.approx(2 / 3, rel=1e-3)
    assert per_class_f1(gold, pred)["ADD"] == pytest.approx(0.8, rel=1e-3)
    assert report.value == pytest.approx((2 / 3 + 0.8) / 2, rel=1e-3)


def test_empty_input_raises() -> None:
    with pytest.raises(ValueError, match="空"):
        macro_f1([], [])


def test_length_mismatch_raises() -> None:
    with pytest.raises(ValueError, match="长度"):
        macro_f1(["NOOP"], ["NOOP", "ADD"])


def test_unknown_label_raises() -> None:
    with pytest.raises(ValueError, match="MAYBE"):
        macro_f1(["MAYBE"], ["NOOP"])


def test_class_support_is_reported() -> None:
    """样本数必须随分数一起报，否则读者无法判断区间可信度。"""
    gold = ["NOOP"] * 5 + ["CONFLICT"] * 2
    pred = list(gold)

    report = macro_f1(gold, pred)

    assert report.support[DecisionKind.NOOP] == 5
    assert report.support[DecisionKind.CONFLICT] == 2


def test_single_sample_class_has_perfect_f1() -> None:
    """单样本类判对时 F1=1，但样本数会被单独提示。"""
    gold = ["NOOP"] * 10 + ["MERGE"]
    pred = list(gold)

    report = macro_f1(gold, pred)

    assert report.support[DecisionKind.MERGE] == 1
    assert report.low_support_classes == (DecisionKind.MERGE,)
