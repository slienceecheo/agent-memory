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
    """**v3 的判据是 `ratio > baseline`，不是"不满分"。**

    构造全部命中（ratio=1.0）：
    - 旧判据 `ratio < 0.9999` -> **红**（满分）
    - 新判据 `ratio > baseline` -> **绿**（1.0 > 0.2778）

    **这个方向的差异是 v3 判据的核心**：满分在 v3 里意味着"排序有效"。
    """
    import evals.tools.check_v2_dataset as module
    from evals.metrics.v2_baselines import axis_baseline_derived
    from evals.tools.check_v2_dataset import check_f24_axis_a_not_saturated

    ds = _ds("billing")
    baseline = axis_baseline_derived(ds)["relation_within"]

    monkeypatch.setattr(module, "ROOT", tmp_path)
    _write(tmp_path, _v3_run(hit_rank=1))

    check = check_f24_axis_a_not_saturated(ds)
    assert check.passed, (
        f"ratio=1.0 > baseline={baseline:.4f}，应通过：{check.detail}"
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
