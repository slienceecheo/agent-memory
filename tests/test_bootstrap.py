"""配对 bootstrap 置信区间的行为契约。

关键区分：
- 单组准确率的 CI：重采样该组
- 两组配对差异的 CI：按样本索引成对重采样，计算差值

后者才是我们做基线比较时需要的，因为两组跑的是同一批样本。
"""

from __future__ import annotations

import numpy as np
import pytest

from memory.eval.bootstrap import paired_difference_ci, proportion_ci


def test_all_correct_gives_degenerate_interval() -> None:
    """全对时重采样必然是 1.0；若实现加了平滑，会得到非退化区间。"""
    outcomes = [True] * 100

    result = proportion_ci(outcomes, n_resamples=2000, seed=0)

    assert result.value == 1.0
    assert result.low == 1.0
    assert result.high == 1.0


def test_all_wrong_gives_degenerate_interval() -> None:
    """全错同理，任何非零下界都说明实现有问题。"""
    outcomes = [False] * 50

    result = proportion_ci(outcomes, n_resamples=2000, seed=0)

    assert result.value == 0.0
    assert result.low == 0.0
    assert result.high == 0.0


def test_half_correct_interval_brackets_the_point_estimate() -> None:
    """区间必须包含点估计，否则报表自相矛盾。"""
    outcomes = [True] * 50 + [False] * 50

    result = proportion_ci(outcomes, n_resamples=5000, seed=0)

    assert result.value == pytest.approx(0.5)
    assert result.low < 0.5 < result.high
    # 二项分布 n=100 p=0.5 的 95% 近似区间约 [0.40, 0.60]
    assert 0.35 < result.low < 0.45
    assert 0.55 < result.high < 0.65


def test_same_seed_is_reproducible() -> None:
    """不可复现的 CI 会让"同一 seed 逐位一致"这条验收失效。"""
    outcomes = [True, False] * 30

    first = proportion_ci(outcomes, n_resamples=2000, seed=42)
    second = proportion_ci(outcomes, n_resamples=2000, seed=42)

    assert first == second


def test_different_seed_keeps_point_estimate_and_brackets_it() -> None:
    """点估计必须与种子无关。

    注意：**不**断言不同种子一定给出不同区间端点。布尔结果的均值只能取
    k/n 这类离散值，两个种子完全可能算出相同的分位数。把"一定不同"
    写成断言就是一条随机失败的测试。
    """
    outcomes = [True, False, True] * 20

    first = proportion_ci(outcomes, n_resamples=2000, seed=1)
    second = proportion_ci(outcomes, n_resamples=2000, seed=2)

    assert first.value == second.value
    for interval in (first, second):
        assert interval.low <= interval.value <= interval.high


def test_single_sample_is_handled() -> None:
    """n=1 时若崩溃，小规模冒烟测试就跑不起来。"""
    result = proportion_ci([True], n_resamples=500, seed=0)

    assert result.value == 1.0
    assert result.low == 1.0
    assert result.high == 1.0


def test_empty_input_raises() -> None:
    """空输入静默返回 0 会让报告出现"0% 准确率"的假数据。"""
    with pytest.raises(ValueError, match="空"):
        proportion_ci([], n_resamples=100, seed=0)


def test_paired_difference_uses_the_same_samples() -> None:
    """独立重采样会高估方差，也可能掩盖"A 稳定优于 B"的事实。"""
    better = [True] * 80 + [False] * 20
    worse = [True] * 50 + [False] * 50

    result = paired_difference_ci(better, worse, n_resamples=5000, seed=0)

    assert result.value == pytest.approx(0.30)
    assert result.low > 0.0, "80% vs 50% 在同一批样本上应给出明显的正差异"
    assert result.high < 0.6


def test_paired_difference_is_tighter_than_independent_when_correlated() -> None:
    """配对的全部意义：两组高度正相关时，配对区间应显著窄于独立区间。

    构造：100 条样本，A 答对前 90 条，B 答对前 89 条。
    两者几乎完全相关，真实差异只有 1 个百分点。
    - 配对重采样：每次重采样里"谁对谁错"的差异只来自那 1 条，区间很窄。
    - 独立重采样：把两组当无关样本，各自抖动，区间会宽得多。

    若实现误用独立重采样，此测试失败；这是唯一能区分两者的测试。
    """
    a = [True] * 90 + [False] * 10
    b = [True] * 89 + [False] * 11

    paired = paired_difference_ci(a, b, n_resamples=4000, seed=0)

    assert paired.value == pytest.approx(0.01)
    # 配对下界接近 0（差异只有 1 条样本），但绝不该出现大幅负值
    assert paired.low > -0.02
    assert paired.high < 0.04


def test_paired_difference_can_be_zero() -> None:
    """两组完全相同，差异区间必须覆盖 0，否则会误报"显著提升"。"""
    same = [True, False] * 40

    result = paired_difference_ci(same, same, n_resamples=2000, seed=0)

    assert result.value == 0.0
    assert result.low <= 0.0 <= result.high


def test_paired_difference_rejects_mismatched_lengths() -> None:
    """长度不一致说明配对关系已丢失，继续计算会得到无意义数字。"""
    with pytest.raises(ValueError, match="长度"):
        paired_difference_ci([True, False], [True], n_resamples=100, seed=0)


def test_paired_difference_rejects_empty() -> None:
    with pytest.raises(ValueError, match="空"):
        paired_difference_ci([], [], n_resamples=100, seed=0)


def test_confidence_level_is_configurable() -> None:
    """只写死 95% 会让"更严格的报告"无法实现。"""
    outcomes = [True] * 60 + [False] * 40

    narrow = proportion_ci(outcomes, n_resamples=3000, seed=0, confidence=0.5)
    wide = proportion_ci(outcomes, n_resamples=3000, seed=0, confidence=0.99)

    assert (narrow.high - narrow.low) < (wide.high - wide.low)


def test_numpy_bool_input_is_accepted() -> None:
    """从 numpy 数组直接传入是常见用法，不接受会迫使调用方手工转换。"""
    outcomes = np.array([True, False, True], dtype=np.bool_)

    result = proportion_ci(outcomes, n_resamples=500, seed=0)

    assert result.value == pytest.approx(2 / 3)
