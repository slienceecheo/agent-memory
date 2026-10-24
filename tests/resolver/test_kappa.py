"""Cohen's κ 的行为契约。

κ 的价值在于扣除"碰巧一致"。两个人各自随机标六类，
期望一致率约 1/6，κ 会把这个扣掉；单看一致率会高估。

边界必须覆盖：完全一致、完全相反、随机水平、单类别退化。
"""

from __future__ import annotations

import pytest
from evals.tools.label import cohen_kappa


def test_perfect_agreement() -> None:
    a = ["NOOP", "ADD", "MERGE", "SUPERSEDE"]
    b = list(a)

    assert cohen_kappa(a, b) == pytest.approx(1.0)


def test_complete_disagreement_is_negative() -> None:
    """完全相反时 κ 应为负，而不是 0。

    若实现用 `max(0, ...)` 把负值截断，会掩盖"标注口径根本不一致"这个事实。
    """
    a = ["NOOP", "NOOP", "ADD", "ADD"]
    b = ["ADD", "ADD", "NOOP", "NOOP"]

    assert cohen_kappa(a, b) < 0


def test_single_label_degenerate_case() -> None:
    """两边都只给同一个标签：期望一致率为 1，κ 定义为 1。"""
    a = ["NOOP"] * 5
    b = ["NOOP"] * 5

    assert cohen_kappa(a, b) == pytest.approx(1.0)


def test_one_side_constant_other_side_varies() -> None:
    """一边恒定、一边变化时，κ 应接近 0（碰巧一致被扣除）。"""
    a = ["NOOP"] * 10
    b = ["NOOP", "ADD"] * 5

    assert cohen_kappa(a, b) == pytest.approx(0.0, abs=0.05)


def test_partial_agreement() -> None:
    a = ["NOOP", "ADD", "MERGE", "SUPERSEDE"]
    b = ["NOOP", "ADD", "SUPERSEDE", "SUPERSEDE"]

    value = cohen_kappa(a, b)

    assert 0.0 < value < 1.0


def test_length_mismatch_raises() -> None:
    with pytest.raises(ValueError, match="长度"):
        cohen_kappa(["NOOP"], ["NOOP", "ADD"])


def test_empty_raises() -> None:
    with pytest.raises(ValueError, match="空"):
        cohen_kappa([], [])


def test_kappa_is_symmetric() -> None:
    """交换两名标注者不该改变结果。"""
    a = ["NOOP", "ADD", "MERGE", "SUPERSEDE", "BRANCH"]
    b = ["NOOP", "MERGE", "MERGE", "CONFLICT", "BRANCH"]

    assert cohen_kappa(a, b) == pytest.approx(cohen_kappa(b, a))
