"""`minimum_hits_to_beat` 的返回值语义，以及 C 轴为何不判通过/失败。

**两种 `None` 必须分开**：

| 情形 | 行为 | 含义 |
|---|---|---|
| `n == 0` | 抛 `ValueError` | 参数非法：没有分母 |
| `n ≥ 1` 无解 | 返回 `None` | 该 `n` 下不可达（全中也过不了） |

早先两者都返回 `None`，调用方无法区分"参数错了"和"这个量级永远过不了"。

**C 轴的例外**：基线低 3–4 倍（0.083–0.111 vs 0.29–0.33），
所以 `1/2` 就能通过 Wilson。而 `n=2` 的样本不支撑任何统计结论。
"""

from __future__ import annotations

import pytest

from memory.eval.wilson import minimum_hits_to_beat, wilson_interval

A_AXIS_BASELINE = 1 / 3       # 竞争集 3 条
C_AXIS_BASELINE = 1 / 12      # 竞争集 12 条（ledger）


# ---------- 两种 None 分开 ----------


def test_zero_n_raises() -> None:
    """`n=0` 必须抛错，不能返回 `None`。"""
    with pytest.raises(ValueError, match="n=0"):
        minimum_hits_to_beat(A_AXIS_BASELINE, 0)


def test_n_one_returns_none_because_unreachable() -> None:
    """`n=1` 返回 `None`——是"不可达"，不是"参数非法"。

    `1/1` 的 Wilson 下界是 0.2065 < 0.3333，所以没有命中数能通过。
    """
    assert minimum_hits_to_beat(A_AXIS_BASELINE, 1) is None
    assert wilson_interval(1, 1).low < A_AXIS_BASELINE


def test_baseline_out_of_range_raises() -> None:
    with pytest.raises(ValueError, match="baseline"):
        minimum_hits_to_beat(1.5, 10)
    with pytest.raises(ValueError, match="baseline"):
        minimum_hits_to_beat(-0.1, 10)


# ---------- C 轴：基线低导致判据变松 ----------


def test_c_axis_passes_with_just_one_of_two() -> None:
    """**C 轴的关键问题**：`1/2` 就能通过 Wilson 判据。

    基线 0.0833，而 `1/2` 的下界是 0.2065。
    这说明"C 轴 2/2 通过"不支撑任何结论——连 1/2 都能过。
    """
    assert minimum_hits_to_beat(C_AXIS_BASELINE, 2) == 1
    assert wilson_interval(1, 2).low > C_AXIS_BASELINE


def test_same_wilson_low_means_different_things_per_axis() -> None:
    """同一个下界，在 A 轴不够、在 C 轴远超。"""
    low = wilson_interval(2, 2).low  # 0.3424

    assert low > A_AXIS_BASELINE   # 勉强过
    assert low > C_AXIS_BASELINE   # 远超
    # 但差距完全不同
    assert low - A_AXIS_BASELINE < 0.02
    assert low - C_AXIS_BASELINE > 0.25


def test_c_axis_n2_is_more_permissive_than_a_axis_n9() -> None:
    """C 轴 n=2 的门槛（1/2 = 50%）低于 A 轴 n=9 的门槛（6/9 = 67%）。"""
    c_need = minimum_hits_to_beat(C_AXIS_BASELINE, 2)
    a_need = minimum_hits_to_beat(A_AXIS_BASELINE, 9)

    assert c_need is not None and a_need is not None
    assert c_need / 2 < a_need / 9, (
        f"C 轴 {c_need}/2 = {c_need / 2:.0%} 应当低于 A 轴 {a_need}/9 = {a_need / 9:.0%}"
    )


def test_c_axis_need_per_n() -> None:
    """C 轴各 n 下的最小命中数必须与文档一致。"""
    expected = {
        1: 1,   # 满分
        2: 1,   # 1/2 = 50%
        3: 2,
        6: 2,   # 2/6 = 33%
    }
    for n, want in expected.items():
        assert minimum_hits_to_beat(C_AXIS_BASELINE, n) == want, f"n={n}"


def test_handoff_records_c_axis_exception() -> None:
    """HANDOFF 必须写明 C 轴不判通过/失败及其两条理由。"""
    from pathlib import Path

    handoff = Path(__file__).resolve().parents[2] / "docs" / "HANDOFF.md"
    if not handoff.exists():
        pytest.skip("HANDOFF 缺失")

    text = handoff.read_text(encoding="utf-8")
    section = text.split("### C 轴：不判通过/失败")[1].split("### v3 的数据纪律")[0]

    assert "基线低" in section
    assert "n" in section and "小" in section
    # 必须给出 1/2 这个反例
    assert "1/2" in section
    # 必须给出"只报数字"的结论
    assert "只报数字" in section
