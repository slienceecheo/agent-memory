"""`F24` 在 v3 下用派生轴，判据是"比随机好"（tasks 2.x）。

**两套轴口径**：

| 装置 | 数据侧基线 | 结果侧分组 | 结果侧判据 |
|---|---|---|---|
| v2 | `axis_baseline(dataset, Axis.A)`（标注） | 标注 A | `ratio < 0.9999`（不满分） |
| v3 | `axis_baseline_derived()["relation_within"]` | **派生 within** | **`ratio > baseline`** |

**v3 为什么换判据**："不满分"在 v3 下没有意义——
v2 里满分意味着"数据太简单"（坏），v3 里满分可能意味着"排序有效"（好）。
两个方向相反。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data" / "retrieval-v2"


def _ds(subject: str = "billing"):
    from evals.datasets.retrieval_v2 import load_dataset

    return load_dataset(DATA / subject)


def _v3_run(*, hit_rank: int | None) -> dict:
    """造一份 v3 签名的结果，所有派生 within 的 case 给同一个名次。"""
    from evals.metrics.v2_baselines import derived_axis_of

    ds = _ds("billing")
    within = [
        q for q in ds.queries if derived_axis_of(ds, q) == "relation_within"
    ]
    return {
        "per_case": [
            {
                "case_id": q.query_id,
                "has_gold": True,
                "features": {"base": 1.0, "authority": 1.0, "status": 1.0},
                "condition_score": None,
                "rank_after_rerank": hit_rank,
            }
            for q in within
        ],
        "code_version": "9999999-dirty",
        "code_diff_hash": "a" * 64,
    }


def _write(tmp_path: Path, payload: dict) -> None:
    results = tmp_path / "results"
    results.mkdir(exist_ok=True)
    (results / "v3-billing-lexical-vector-adjacency.json").write_text(
        json.dumps(payload, ensure_ascii=False), encoding="utf-8"
    )


def test_f24_uses_derived_baseline(tmp_path: Path, monkeypatch) -> None:
    """v3 下数据侧基线必须来自**派生**口径（`billing` 是 0.2778）。

    标注口径的 A 轴基线是 0.3333——两者不同，所以能区分。
    """
    import evals.tools.check_v2_dataset as module
    from evals.datasets.retrieval_v2 import Axis
    from evals.metrics.v2_baselines import axis_baseline, axis_baseline_derived
    from evals.tools.check_v2_dataset import check_f24_axis_a_not_saturated

    ds = _ds("billing")
    labeled = axis_baseline(ds, Axis.A).seh_at_1
    derived = axis_baseline_derived(ds)["relation_within"]
    assert labeled != pytest.approx(derived, abs=1e-4), (
        "前提不成立：两种口径的基线相同，这条测试无法区分它们"
    )

    monkeypatch.setattr(module, "ROOT", tmp_path)
    _write(tmp_path, _v3_run(hit_rank=1))  # 全部命中，ratio=1.0

    check = check_f24_axis_a_not_saturated(ds)
    assert check.applicable
    assert f"{derived:.4f}" in check.detail, (
        f"detail 未使用派生基线 {derived:.4f}：{check.detail}"
    )
    assert f"{labeled:.4f}" not in check.detail, (
        f"detail 仍出现标注基线 {labeled:.4f}：{check.detail}"
    )


def test_f24_v3_judges_against_baseline(tmp_path: Path, monkeypatch) -> None:
    """**v3 判据有下限也有上限**：`baseline < ratio < ceiling`。

    这条用"刚好过下限但不满分"的值（ratio=0.5）验证下限生效：
    - 0.5 > baseline 0.2778 -> 过下限
    - 0.5 < 0.9999 -> 过上限
    所以通过。

    **不能用 ratio=1.0**：满分在 v3 下被上限判红（"数据太容易"），
    那是 `test_f24_v3_has_no_upper_bound_gap` 覆盖的方向。
    """
    import evals.tools.check_v2_dataset as module
    from evals.metrics.v2_baselines import axis_baseline_derived, derived_axis_of
    from evals.tools.check_v2_dataset import check_f24_axis_a_not_saturated

    ds = _ds("billing")
    baseline = axis_baseline_derived(ds)["relation_within"]
    assert baseline is not None

    within = [q for q in ds.queries if derived_axis_of(ds, q) == "relation_within"]
    half = len(within) // 2
    payload = {
        "per_case": [
            {
                "case_id": q.query_id,
                "has_gold": True,
                "features": {"base": 1.0, "authority": 1.0, "status": 1.0},
                "condition_score": None,
                "rank_after_rerank": 1 if i < half else 99,
            }
            for i, q in enumerate(within)
        ],
        "code_version": "9999999-dirty",
        "code_diff_hash": "a" * 64,
    }

    monkeypatch.setattr(module, "ROOT", tmp_path)
    _write(tmp_path, payload)

    check = check_f24_axis_a_not_saturated(ds)
    assert check.passed, (
        f"ratio={half / len(within):.4f} > baseline={baseline:.4f} 且 < 上限，应通过："
        f"{check.detail}"
    )


def test_f24_v3_fails_below_baseline(tmp_path: Path, monkeypatch) -> None:
    """全部排最后 -> ratio=0.0 < baseline -> **必须红**。

    实测 `billing` 在 v3 下派生 within 的 SEH@1 是 0.0833，
    基线是 0.2778——低于基线，所以真实数据上它会红。**那个红是正确的。**
    """
    import evals.tools.check_v2_dataset as module
    from evals.metrics.v2_baselines import axis_baseline_derived
    from evals.tools.check_v2_dataset import check_f24_axis_a_not_saturated

    ds = _ds("billing")
    baseline = axis_baseline_derived(ds)["relation_within"]

    monkeypatch.setattr(module, "ROOT", tmp_path)
    _write(tmp_path, _v3_run(hit_rank=99))  # 全部不命中

    check = check_f24_axis_a_not_saturated(ds)
    assert check.applicable
    assert not check.passed, f"ratio=0 < baseline={baseline:.4f} 却通过"
    assert "不高于派生基线" in check.detail


def test_f24_v3_has_no_upper_bound_gap(tmp_path: Path, monkeypatch) -> None:
    """**v3 也要上限**：满分说明数据太容易，不是"排序有效"。

    v3 数据要求"每 subject 至少一个单值 relation"，而单值 relation
    意味着池可能很小（`n_competitors=1` -> 池 2），`ratio` 容易满分。
    **只有下限会放行"数据太简单"。**

    上限在 v3 下的语义是**数据难度**，不是装置语义——所以 `0.9999` 仍有效。
    """
    import evals.tools.check_v2_dataset as module
    from evals.metrics.v2_baselines import axis_baseline_derived
    from evals.tools.check_v2_dataset import check_f24_axis_a_not_saturated

    ds = _ds("billing")
    baseline = axis_baseline_derived(ds)["relation_within"]
    assert baseline is not None

    monkeypatch.setattr(module, "ROOT", tmp_path)
    _write(tmp_path, _v3_run(hit_rank=1))  # 全命中 ratio=1.0

    check = check_f24_axis_a_not_saturated(ds)
    assert not check.passed, (
        f"ratio=1.0 满分却通过——v3 的上限没生效：{check.detail}"
    )
    assert "太容易" in check.detail, check.detail


def test_f24_v3_data_side_is_vacuous() -> None:
    """**v3 的数据侧是恒真的**——必须被登记，否则读者以为两段都在验。

    派生 within 的池大小 `>= 2`，所以基线最大 `1/2 = 0.5`，
    永远小于 `0.9999`。

    这条断言的是"恒真这个事实"，不是"它有用"。
    若将来池大小退化成 1（`n_competitors` 全为 0），基线会变成 1.0，
    那时 `test_f24_...` 的数据侧才会红——它防的是那个形状退化。
    """
    from evals.metrics.v2_baselines import axis_baseline_derived, competing_set, derived_axis_of

    for subject in ("sample", "billing"):
        ds = _ds(subject)
        sizes = [
            len(competing_set(ds, q))
            for q in ds.queries
            if derived_axis_of(ds, q) == "relation_within"
        ]
        base = axis_baseline_derived(ds)["relation_within"]
        assert base is not None
        # 基线上限 = 1/最小池
        theoretical_max = 1 / min(sizes)
        assert base <= theoretical_max + 1e-9
        assert theoretical_max < 0.9999, (
            f"{subject}: 理论最大基线 {theoretical_max:.4f} 不小于 0.9999——"
            "数据侧不再恒真，这条登记要重核"
        )


def test_f24_v3_uses_derived_axis_grouping(tmp_path: Path, monkeypatch) -> None:
    """v3 的分母是**派生 within** 的 case，不是标注 A。

    `billing` 的派生 within 有 12 条，标注 A 只有 9 条。
    """
    import evals.tools.check_v2_dataset as module
    from evals.metrics.v2_baselines import derived_axis_of
    from evals.tools.check_v2_dataset import check_f24_axis_a_not_saturated

    ds = _ds("billing")
    n_derived = sum(
        1 for q in ds.queries if derived_axis_of(ds, q) == "relation_within"
    )
    n_labeled_a = sum(1 for q in ds.queries if q.axis.value == "A")
    assert n_derived != n_labeled_a, "前提不成立：两种分组条数相同"

    monkeypatch.setattr(module, "ROOT", tmp_path)
    _write(tmp_path, _v3_run(hit_rank=1))

    check = check_f24_axis_a_not_saturated(ds)
    assert f"/{n_derived}=" in check.detail, (
        f"分母不是派生 within 的 {n_derived} 条：{check.detail}"
    )
