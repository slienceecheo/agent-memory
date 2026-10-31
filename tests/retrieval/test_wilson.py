"""Wilson 区间与"通过所需最小命中数"。

**为什么存在这个模块**：v3 的统计判据是"每轴 `SEH@1` 的 Wilson 95% 下界 >
该轴自己的随机基线"。而项目里已有的 `proportion_ci` 是**百分位 bootstrap**，
它在 `p≈0/1` 且 `n` 小时坍缩成零宽：

| 情形 | bootstrap | Wilson |
|---|---|---|
| `2/2` | `[1.0, 1.0]` 宽 0 | `[0.342, 1.0]` |
| `9/9` | `[1.0, 1.0]` 宽 0 | `[0.701, 1.0]` |
| `6/9` | `[0.333, 1.0]` ← 下界恰好等于基线 | `[0.354, 0.879]` |

`6/9` 是分水岭：bootstrap 判不通过、Wilson 判通过。而 bootstrap 的 `0.3333`
正是 `k/n` 网格的量化产物，不是统计事实。

**这是工具选型错，不是实现错**——`proportion_ci` 本身没问题，
百分位 bootstrap 不适合这种样本量与比例组合。
"""

from __future__ import annotations

import pytest
from evals.metrics.wilson import minimum_hits_to_beat, wilson_interval

from memory.eval.bootstrap import proportion_ci

BASELINE_BILLING = 1 / 3  # billing A 轴竞争集均值 3.00


def test_wilson_does_not_collapse_on_small_all_success() -> None:
    """`2/2` 不能报 `[1.0, 1.0]`——那等于"没有不确定性"。

    这正是 bootstrap 的行为，也是换工具的直接原因。
    """
    wilson = wilson_interval(2, 2)
    boot = proportion_ci([True, True], seed=0)

    assert wilson.low == pytest.approx(0.3424, abs=1e-3)
    assert wilson.high == pytest.approx(1.0, abs=1e-9)
    # 对照：bootstrap 坍缩
    assert boot.low == pytest.approx(1.0, abs=1e-9)
    assert boot.high == pytest.approx(1.0, abs=1e-9)


def test_wilson_does_not_collapse_on_all_success() -> None:
    """`9/9` 同样不能坍缩。"""
    wilson = wilson_interval(9, 9)
    assert wilson.low == pytest.approx(0.7008, abs=1e-3)
    assert wilson.high == pytest.approx(1.0, abs=1e-9)


def test_wilson_and_bootstrap_disagree_at_six_of_nine() -> None:
    """**关键对照**：`6/9` 在两种方法下给出相反结论。

    bootstrap 下界 = 0.3333（恰好等于基线，判不通过）
    Wilson 下界    = 0.3542（大于基线，判通过）
    """
    boot = proportion_ci([True] * 6 + [False] * 3, seed=0)
    wilson = wilson_interval(6, 9)

    assert boot.low == pytest.approx(BASELINE_BILLING, abs=1e-4)
    assert wilson.low > BASELINE_BILLING
    assert wilson.low == pytest.approx(0.3542, abs=1e-3)


def test_minimum_hits_table() -> None:
    """``n`` 与"通过所需最小命中数"的关系必须与文档一致。"""
    expected = {
        4: 4,    # 满分 —— 与 F24 冲突
        5: 4,
        6: 5,
        9: 6,
        10: 7,
        20: 11,
    }
    for n, want in expected.items():
        assert minimum_hits_to_beat(BASELINE_BILLING, n) == want, f"n={n}"


def test_n_four_needs_a_perfect_score() -> None:
    """`n=4` 需要 `4/4` 满分，与 F24 冲突——所以"通过且不满分"的最低 n 是 5。

    F23 要求 A 轴 ≥ 6，因此实际不会触发 `n=4`。
    """
    assert minimum_hits_to_beat(BASELINE_BILLING, 4) == 4
    assert minimum_hits_to_beat(BASELINE_BILLING, 5) == 4  # 4/5 不是满分


def test_interval_width_does_not_support_the_n10_claim() -> None:
    """**记录一个被推翻的依据**：`n=10` 时宽度并不总是 < 0.5。

    实测 `n=10`、`p=0.5` 时宽度是 0.527。若报告写"n=10 时宽度 < 0.5"，
    读者在 `p≈0.5` 的数据上会算出 0.527 并怀疑整个判据。
    """
    width_at_half = wilson_interval(5, 10).width
    assert width_at_half == pytest.approx(0.5268, abs=1e-3)
    assert width_at_half > 0.5


def test_empty_sample_reports_full_uncertainty() -> None:
    """`n=0` 时报 `[0, 1]`——"没有观测"不是"0%"。

    与本项目 `path_returns` 用 `null` 而非 `0` 是同一条原则。
    """
    empty = wilson_interval(0, 0)
    assert (empty.low, empty.high) == (0.0, 1.0)
    assert empty.n == 0


def test_invalid_inputs_raise() -> None:
    with pytest.raises(ValueError):
        wilson_interval(3, 2)   # hits > n
    with pytest.raises(ValueError):
        wilson_interval(-1, 2)  # hits < 0
    with pytest.raises(ValueError):
        wilson_interval(1, -1)  # n < 0
