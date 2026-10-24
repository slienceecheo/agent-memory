"""分类质量指标。

三条设计原则：

1. **不用总体准确率作为主指标**。六类里稀有类只占 10%，
   全判错时总体准确率仍能到 90%，完全掩盖问题。macro-F1 每类等权。

2. **无样本的类别从分母排除**，而不是记 0 分。
   记 0 分会让"这个类别本次没考"变成"这个类别考砸了"。

3. **样本数必须随分数一起报**。单样本类的 F1=1 毫无统计意义，
   报告必须能看出这一点。
"""

from __future__ import annotations

from dataclasses import dataclass

from memory.resolver.rules import DecisionKind

_LOW_SUPPORT_THRESHOLD = 3


@dataclass(frozen=True, slots=True)
class MacroF1Report:
    value: float
    classes_evaluated: int
    support: dict[DecisionKind, int]
    absent_classes: tuple[DecisionKind, ...]
    low_support_classes: tuple[DecisionKind, ...]


def _validate(gold: list[str], pred: list[str]) -> None:
    if not gold:
        raise ValueError("评估集为空，无法计算分类指标。")
    if len(gold) != len(pred):
        raise ValueError(f"gold 与 pred 长度不一致：{len(gold)} vs {len(pred)}")
    valid = {kind.value for kind in DecisionKind}
    for label in [*gold, *pred]:
        if label not in valid:
            raise ValueError(
                f"未知类别 {label!r}，可用值：{', '.join(sorted(valid))}"
            )


def confusion_matrix(gold: list[str], pred: list[str]) -> dict[str, dict[str, int]]:
    """行 = 期望类别，列 = 预测类别。"""
    _validate(gold, pred)
    matrix = {kind.value: {other.value: 0 for other in DecisionKind} for kind in DecisionKind}
    for expected, predicted in zip(gold, pred, strict=True):
        matrix[expected][predicted] += 1
    return matrix


def per_class_f1(gold: list[str], pred: list[str]) -> dict[str, float]:
    """逐类 F1。只返回在期望集中出现过的类别。"""
    _validate(gold, pred)
    result: dict[str, float] = {}

    for kind in DecisionKind:
        label = kind.value
        true_positive = sum(
            1 for expected, predicted in zip(gold, pred, strict=True)
            if expected == label and predicted == label
        )
        false_positive = sum(
            1 for expected, predicted in zip(gold, pred, strict=True)
            if expected != label and predicted == label
        )
        false_negative = sum(
            1 for expected, predicted in zip(gold, pred, strict=True)
            if expected == label and predicted != label
        )

        if true_positive + false_negative == 0:
            continue  # 该类别在评估集中没有样本

        precision = (
            true_positive / (true_positive + false_positive)
            if true_positive + false_positive
            else 0.0
        )
        recall = true_positive / (true_positive + false_negative)
        f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
        result[label] = f1

    return result


def macro_f1(gold: list[str], pred: list[str]) -> MacroF1Report:
    """六类等权的平均 F1，并附带支持度信息。"""
    scores = per_class_f1(gold, pred)
    if not scores:
        raise ValueError("没有任何类别参与评估。")

    value = sum(scores.values()) / len(scores)

    support = {kind: 0 for kind in DecisionKind}
    for label in gold:
        support[DecisionKind(label)] += 1

    absent = tuple(kind for kind, count in support.items() if count == 0)
    low_support = tuple(
        kind for kind, count in support.items() if 0 < count < _LOW_SUPPORT_THRESHOLD
    )

    return MacroF1Report(
        value=value,
        classes_evaluated=len(scores),
        support=support,
        absent_classes=absent,
        low_support_classes=low_support,
    )
