"""`F24` 的 detail 必须报出 `ratio - baseline` 的差（不设目标区间）。

## 为什么报差值而不是定区间

**定区间会诱导造数据时调难度** ——
`ratio` 落不进 `(0.5, 0.9)` 时，人会去改数据让它落进去。
那是"为达标回头改数据"。

**"先造出来再看"也不行** ——
`ratio` 落进哪里都接受，那上限 `0.9999` 在数据上就没有约束力。

**正确的做法：如实报差值，让增益本身成为结论。**

| `ratio - baseline` | 结论 |
|---|---|
| ≈ 0 | 这份数据上 v3 排序没有增益 |
| 明显 > 0 | 有增益，数值就是增益大小 |
| < 0 | 排序比随机还差 |

**v2 的实测参考**（v3 装置跑 v2 数据）：

| subject | 派生 within baseline | v3 实测 ratio | 差 |
|---|---|---|---|
| `sample` | 0.3000 | 0.3000 | **+0.0000** |
| `billing` | 0.2778 | 0.0833 | **−0.1944** |

`sample` 的差正好为 0 —— 这本身就是一条结论：**v3 去掉 condition 加权后，
排序在这份数据上没有增益。** 若只报 `ratio=0.3000`，读者会误以为"比基线好"。

## 差值的两个作用

1. **可读性**：不需要手算 `0.3000 - 0.3000`
2. **可证伪**：`ratio ≈ baseline` 与 `ratio >> baseline` 在 detail 里一眼可分

后者更重要 —— 若 detail 只报 `ratio`，两种截然不同的结论会写成一模一样的句子。
"""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data" / "retrieval-v2"


def _ds(subject: str = "billing"):
    from evals.datasets.retrieval_v2 import load_dataset

    return load_dataset(DATA / subject)


def _write(tmp_path: Path, *, hits: int, total: int) -> float:
    """写一份 v3 签名产物，让 `hits/total` 条派生 within 命中。"""
    from evals.metrics.v2_baselines import derived_axis_of

    ds = _ds("billing")
    within = [q for q in ds.queries if derived_axis_of(ds, q) == "relation_within"]
    assert len(within) == total, f"派生 within 数变了：{len(within)} != {total}"

    payload = {
        "per_case": [
            {
                "case_id": q.query_id,
                "has_gold": True,
                "features": {"base": 1.0, "authority": 1.0, "status": 1.0},
                "condition_score": None,
                "rank_after_rerank": 1 if i < hits else 99,
            }
            for i, q in enumerate(within)
        ],
        "code_version": "9999999-dirty",
        "code_diff_hash": "a" * 64,
    }
    results = tmp_path / "results" / "v3"
    results.mkdir(parents=True, exist_ok=True)
    (results / "v3-billing-lexical-vector-adjacency.json").write_text(
        json.dumps(payload, ensure_ascii=False), encoding="utf-8"
    )
    return hits / total


def test_f24_reports_gain_in_detail(tmp_path: Path, monkeypatch) -> None:
    """**detail 必须同时含 `ratio`、`baseline`、以及两者的差。**

    只报 `ratio` 时，"ratio ≈ baseline"（无增益）与"ratio >> baseline"
    （有增益）会写成一模一样的句子——那是两种截然不同的结论。
    """
    import evals.tools.check_v2_dataset as module
    from evals.metrics.v2_baselines import axis_baseline_derived
    from evals.tools.check_v2_dataset import check_f24_axis_a_not_saturated

    ds = _ds("billing")
    baseline = axis_baseline_derived(ds)["relation_within"]
    assert baseline is not None

    monkeypatch.setattr(module, "ROOT", tmp_path)
    ratio = _write(tmp_path, hits=6, total=12)  # 0.5000 > baseline 0.2778
    gain = ratio - baseline

    check = check_f24_axis_a_not_saturated(ds)

    assert check.passed, f"0.5 应通过（有增益但不满分）：{check.detail}"
    assert f"{ratio:.4f}" in check.detail, f"缺 ratio：{check.detail}"
    assert f"{baseline:.4f}" in check.detail, f"缺 baseline：{check.detail}"
    assert f"{gain:+.4f}" in check.detail, (
        f"缺差值 {gain:+.4f}——detail 里必须能直接读出增益大小：{check.detail}"
    )


def test_f24_reports_gain_when_failing_upper_bound(
    tmp_path: Path, monkeypatch
) -> None:
    """**红了也要报差值**——"太容易"的红，增益是 `+0.7222`。

    若只在通过时报差值，红的时候读者仍要手算才能看出"这数据有多容易"。
    """
    import evals.tools.check_v2_dataset as module
    from evals.metrics.v2_baselines import axis_baseline_derived
    from evals.tools.check_v2_dataset import check_f24_axis_a_not_saturated

    ds = _ds("billing")
    baseline = axis_baseline_derived(ds)["relation_within"]
    assert baseline is not None

    monkeypatch.setattr(module, "ROOT", tmp_path)
    ratio = _write(tmp_path, hits=12, total=12)  # 1.0000
    gain = ratio - baseline

    check = check_f24_axis_a_not_saturated(ds)

    assert not check.passed
    assert "太容易" in check.detail
    assert f"{gain:+.4f}" in check.detail, (
        f"红的时候也要报差值 {gain:+.4f}：{check.detail}"
    )


def test_f24_reports_gain_when_below_baseline(tmp_path: Path, monkeypatch) -> None:
    """**低于基线时差值是负数**，必须能读出来。

    `billing` 在 v3 装置跑 v2 数据时就是这种形态（实测 −0.1944）。
    负值不能被格式化成"没有差"——`+.4f` 会给出 `-0.1944`。
    """
    import evals.tools.check_v2_dataset as module
    from evals.metrics.v2_baselines import axis_baseline_derived
    from evals.tools.check_v2_dataset import check_f24_axis_a_not_saturated

    ds = _ds("billing")
    baseline = axis_baseline_derived(ds)["relation_within"]
    assert baseline is not None

    monkeypatch.setattr(module, "ROOT", tmp_path)
    ratio = _write(tmp_path, hits=1, total=12)  # 0.0833 < baseline 0.2778
    gain = ratio - baseline
    assert gain < 0, "前提不成立：这个构造应该低于基线"

    check = check_f24_axis_a_not_saturated(ds)

    assert not check.passed, "低于基线必须红"
    assert f"{gain:+.4f}" in check.detail, (
        f"缺负差值 {gain:+.4f}：{check.detail}"
    )
    assert f"{gain:+.4f}".startswith("-"), "负号必须保留"


def test_f24_has_no_target_range() -> None:
    """**`F24` 不得引入目标区间**——只报差值。

    定区间会诱导造数据时为了落进区间而调难度（造数据纪律第 5 条禁止）。
    这条断言的是"没有区间"，防的是"为了更严格又加一条"。
    """
    import evals.tools.check_v2_dataset as module

    src = Path(module.__file__).read_text(encoding="utf-8")

    # 找 F24 的函数体
    start = src.find("def check_f24_axis_a_not_saturated")
    assert start >= 0
    end = src.find("\ndef ", start + 10)
    body = src[start:end if end > 0 else len(src)]

    # 目标区间会表现为"下限不只 baseline"或"上限不只 ceiling"
    for marker in ("target_low", "target_high", "TARGET_", "target_range"):
        assert marker not in body, (
            f"F24 里出现了 {marker}——那会把'报告增益'变成'凑区间'。"
            "定区间会诱导造数据时调难度。"
        )

    # 判据只允许 ceiling 与 baseline 两个阈值
    assert "ceiling" in body
    assert "baseline_seh1" in body
