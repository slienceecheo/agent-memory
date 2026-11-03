"""按派生轴分组算随机基线（tasks 1.x / 3.x）。

**核心**：`n_competitors` 与 `competing_set` 是两个量，而只有 A 轴上
`n_competitors + 1 == len(competing_set)`。

实测例外（全部是 C 轴）：

| 查询 | `n_competitors` | `competing_set` | `n+1` |
|---|---|---|---|
| `ledger-q11` / `q12` | 0 | **12** | 1 |
| `billing-c1` / `c2` / `c3` | 2 | **9** | 3 |

**按 `n+1` 推池大小会让 cross 基线变成 `1/1 = 1.0`（随机也满分），
与真值 `1/12 = 0.0833` 差 12 倍**——任何实测值都"不高于基线"，判据失效。
"""

from __future__ import annotations

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data" / "retrieval-v2"


def _ds(subject: str):
    from evals.datasets.retrieval_v2 import load_dataset

    return load_dataset(DATA / subject)


def _n_competitors(ds, q) -> int:
    from evals.run_retrieval import count_competitors

    gold = ds.memory(q.gold_memory_id)
    pool = [
        {"memory_id": m.memory_id, "relation": m.relation}
        for m in ds.memories
        if m.memory_id != gold.memory_id
    ]
    return count_competitors(
        pool=pool,
        gold={"memory_id": gold.memory_id, "relation": gold.relation},
    )


# ---------- 1.1 / 1.3 sample 的基线 ----------


def test_derived_baseline_sample() -> None:
    """`axis_baseline_derived(sample)` 必须给出两个轴各自的基线。

    期望：`{"relation_within": 0.3000, "relation_cross": 0.0833}`
    """
    from evals.metrics.v2_baselines import axis_baseline_derived

    ds = _ds("sample")
    got = axis_baseline_derived(ds)

    assert set(got) == {"relation_within", "relation_cross"}, got
    assert got["relation_within"] == pytest.approx(0.3000, abs=1e-4), got
    assert got["relation_cross"] == pytest.approx(0.0833, abs=1e-4), got


def test_cross_baseline_is_not_one() -> None:
    """**核心**：cross 基线必须是 `1/12`，不是 `1/1`。

    若实现用 `n_competitors + 1` 推池大小，`ledger-q11/q12` 会得到 `N=1`，
    基线 `1.0`——而真值是 `1/12 = 0.0833`。

    这条是唯一能抓住"两个池大小混用"的断言。
    """
    from evals.metrics.v2_baselines import axis_baseline_derived

    ds = _ds("sample")
    got = axis_baseline_derived(ds)

    assert got["relation_cross"] < 0.5, (
        f"cross 基线 {got['relation_cross']:.4f} 太高——"
        "疑似用了 n_competitors + 1（会得到 1.0）而不是竞争集大小（12）"
    )
    assert got["relation_cross"] == pytest.approx(1 / 12, abs=1e-9)


def test_billing_derived_baseline() -> None:
    """`billing` 的派生 within 基线是 **0.2778**，不是 0.3333。

    构成：9 条 `N=3`（`1/3`）+ 3 条 `N=9`（`1/9`）。

    **那 3 条是 C 标注**——它们在池结构上是 within，池大小是 9 不是 3。
    所以"派生轴"不是把标注改名，是真的按池结构重新分组。
    """
    from evals.metrics.v2_baselines import axis_baseline_derived

    ds = _ds("billing")
    got = axis_baseline_derived(ds)

    assert "relation_within" in got
    assert got["relation_within"] == pytest.approx(0.2778, abs=1e-4), got
    # 与标注口径不同——这正是"重新分组"
    from evals.datasets.retrieval_v2 import Axis
    from evals.metrics.v2_baselines import axis_baseline

    labeled = axis_baseline(ds, Axis.A).seh_at_1
    assert got["relation_within"] != pytest.approx(labeled, abs=1e-4), (
        f"派生基线 {got['relation_within']:.4f} 与标注基线 {labeled:.4f} 相同——"
        "若真按池结构重新分组，它们应当不同（billing 有 3 条标注错）"
    )


def test_billing_has_no_cross_axis() -> None:
    """`billing` 的派生 cross 轴为空——三个 relation 全多分支。

    **空组 MUST 返回 `None`，MUST NOT 返回 `0.0`**：

    `0.0` 作为基线意味着"随机命中率是 0"，于是任何实测值（哪怕也是 0）
    都会 `ratio <= baseline` -> 报红。**"没有数据"会被伪装成"基线是 0"。**
    """
    from evals.metrics.v2_baselines import axis_baseline_derived

    got = axis_baseline_derived(_ds("billing"))
    assert got["relation_cross"] is None, (
        f"空组返回了 {got['relation_cross']!r}，应为 None。"
        "0.0 会让下一个人拿它当基线用，然后得到'所有 cross 查询都不达标'的假红。"
    )


def test_cross_baseline_is_usable_when_present() -> None:
    """有对象时，cross 基线必须是**数值**而不是 None——反向确认。"""
    from evals.metrics.v2_baselines import axis_baseline_derived

    got = axis_baseline_derived(_ds("sample"))
    assert got["relation_cross"] is not None
    assert got["relation_cross"] == pytest.approx(1 / 12, abs=1e-9)


# ---------- 1.5 恒等式例外必须被登记 ----------


def test_pool_size_identity_exceptions() -> None:
    """`n_competitors + 1 == len(competing_set)` 的例外必须被登记。

    实测 5 条，全部是 C 轴：

    | 查询 | `n` | `cs` |
    |---|---|---|
    | `ledger-q11/q12` | 0 | 12 |
    | `billing-c1/c2/c3` | 2 | 9 |

    **这条把"两个量不同"写成可执行的事实**：若将来有人把
    `ranking_pool_size` 改成 `n_competitors + 1`，这条会红。
    """
    from evals.metrics.v2_baselines import competing_set

    expected = {
        "sample": {"ledger-q11": (0, 12), "ledger-q12": (0, 12)},
        "billing": {
            "billing-c1": (2, 9),
            "billing-c2": (2, 9),
            "billing-c3": (2, 9),
        },
    }

    for subject, want in expected.items():
        ds = _ds(subject)
        got = {}
        for q in ds.queries:
            n = _n_competitors(ds, q)
            cs = len(competing_set(ds, q))
            if n + 1 != cs:
                got[q.query_id] = (n, cs)
        assert got == want, (
            f"{subject} 的恒等式例外变了：{got}，期望 {want}。\n"
            "若例外消失，说明 competing_set 的定义改了——"
            "而那两个池大小的区分也要重核。"
        )


# ---------- 3.1 标注与派生不一致数 ----------


@pytest.mark.parametrize(
    ("subject", "expected_mismatch", "total"),
    [("sample", 0, 12), ("billing", 3, 12)],
)
def test_axis_label_mismatch_counts(
    subject: str, expected_mismatch: int, total: int
) -> None:
    """标注轴与派生轴的不一致数必须可复算。

    **可追溯性来自报告写不写这个数字，不来自门禁用哪套轴。**
    """
    from evals.metrics.v2_baselines import axis_label_mismatches

    got = axis_label_mismatches(_ds(subject))
    assert got["mismatch"] == expected_mismatch, got
    assert got["total"] == total, got
