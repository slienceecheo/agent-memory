"""门禁必须能发现所有分区的产物（tasks 1.x / 2.x / 3.x）。

**为什么需要**：实测 v3 签名产物放进 `results/v3/`（spec 规定的位置）后：

| 情形 | F20 | F24 |
|---|---|---|
| 放 `results/v3/` | 失败（找不到） | **`passed=True`** |
| 放顶层 + 改名 `v2-` | 通过 | 失败（真的执行了） |

**违反分区反而能读到，遵守分区反而读不到。**

根因：`glob("v2-*")` 写死顶层 + 文件名前缀。

**第二条**：`F24` 的 `passed = data_side_problem is None and result_side_problem is None`
里，"没找到文件"与"找到了且没问题"都是 `None`——前者得到 `passed=True`，
**门禁没跑却报告通过**。
"""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data" / "retrieval-v2"


def _ids(subject: str = "sample") -> list[str]:
    from evals.datasets.retrieval_v2 import load_dataset

    return [q.query_id for q in load_dataset(DATA / subject).queries]


def _v3_ablation(subject: str = "sample") -> dict:
    """v3 签名：两轴逐条 rank 相同。"""
    ranks = {qid: 1 for qid in _ids(subject)}
    return {
        "with_condition": ranks,
        "without_condition": dict(ranks),
        "drop": 0.0,
        "threshold": 0.30,
        "axis_a_seh1_with": 1.0,
        "axis_a_seh1_without": 1.0,
    }


def _v3_run(subject: str = "sample") -> dict:
    """v3 签名的 per_case 结果，且 A 轴全命中。"""
    from evals.datasets.retrieval_v2 import Axis, load_dataset

    ds = load_dataset(DATA / subject)
    return {
        "per_case": [
            {
                "case_id": q.query_id,
                "has_gold": True,
                "features": {"base": 1.0, "authority": 1.0, "status": 1.0},
                "condition_score": None,
                "rank_after_rerank": 1,
            }
            for q in ds.queries
            if q.axis is Axis.A
        ],
        "code_version": "9999999-dirty",
        "code_diff_hash": "a" * 64,
    }


def _write(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


# ---------- 1.1 / 1.3 发现分区产物 ----------


def test_gate_finds_zone_products(tmp_path: Path, monkeypatch) -> None:
    """**核心**：`results/v3/` 里的 v3 签名产物必须被 `F20` 发现并执行。

    文件名带 `v3-` 前缀（不是 `v2-`），所以旧的 glob 匹配不到。
    """
    import evals.tools.check_v2_dataset as module
    from evals.datasets.retrieval_v2 import load_dataset
    from evals.tools.check_v2_dataset import check_f20_condition_contributes

    monkeypatch.setattr(module, "ROOT", tmp_path)
    _write(
        tmp_path / "results" / "v3" / "v3-sample-condition-ablation.json",
        _v3_ablation(),
    )

    ds = load_dataset(DATA / "sample")
    check = check_f20_condition_contributes(ds)

    assert check.applicable, f"v3 分区产物未被发现：{check.detail}"
    assert check.passed, check.detail
    assert "0.0000" in check.detail, f"应执行 v3 分支：{check.detail}"


def test_f24_finds_zone_products(tmp_path: Path, monkeypatch) -> None:
    """`F24` 同样必须能发现 `results/v3/` 的产物。

    **这条只验证"发现并执行"**，不验证判据结果——判据方向见
    `test_f24_derived_axis.py`（下限 `> baseline`、上限 `< ceiling`）。

    v3 下 A 轴 10/10 满分会被**上限**判红（"数据太容易"），
    所以这里断言的是"真的执行了"，不是"通过/失败"。
    """
    import evals.tools.check_v2_dataset as module
    from evals.datasets.retrieval_v2 import load_dataset
    from evals.tools.check_v2_dataset import check_f24_axis_a_not_saturated

    monkeypatch.setattr(module, "ROOT", tmp_path)
    _write(
        tmp_path / "results" / "v3" / "v3-sample-lexical-vector-adjacency.json",
        _v3_run(),
    )

    ds = load_dataset(DATA / "sample")
    check = check_f24_axis_a_not_saturated(ds)

    assert check.applicable, f"v3 分区产物未被发现：{check.detail}"
    # 真的执行了：detail 里有实测值与派生基线
    assert "实测 10/10=1.0000" in check.detail, check.detail
    assert "派生 within 基线" in check.detail, check.detail
    # 满分在 v3 下被上限判红
    assert not check.passed
    assert "太容易" in check.detail
    assert "1.0000" in check.detail


# ---------- 2.1 空分区 ----------


def test_empty_zone_is_not_applicable(tmp_path: Path, monkeypatch) -> None:
    """**v3 分区为空 -> `applicable=False`，MUST NOT 是 `passed=True`。**

    "这代还没数据"不是失败，是"不适用"。
    而现在 `F24` 把它报成 `passed=True`——门禁没跑却显示通过。
    """
    import evals.tools.check_v2_dataset as module
    from evals.datasets.retrieval_v2 import load_dataset
    from evals.tools.check_v2_dataset import (
        check_f20_condition_contributes,
        check_f24_axis_a_not_saturated,
    )

    monkeypatch.setattr(module, "ROOT", tmp_path)
    (tmp_path / "results" / "v3").mkdir(parents=True)  # 存在但为空

    ds = load_dataset(DATA / "sample")

    f20 = check_f20_condition_contributes(ds)
    assert not f20.applicable, f"F20: 空分区应不适用，实际 {f20.detail}"
    assert not f20.passed

    f24 = check_f24_axis_a_not_saturated(ds)
    assert not f24.applicable, f"F24: 空分区应不适用，实际 {f24.detail}"
    assert not f24.passed, (
        "F24 把'没找到文件'报成了通过——门禁没跑却显示 passed=True"
    )


# ---------- 2.2 有文件但不匹配 ----------


def test_mismatched_files_are_config_error(tmp_path: Path, monkeypatch) -> None:
    """有文件但都不含本数据集的查询 -> `passed=False`，且说明是配置问题。

    **与"空分区"分开**：前者去查路径，后者去造数据。
    现在两者被压成同一句"没有覆盖本数据集的消融结果"。
    """
    import evals.tools.check_v2_dataset as module
    from evals.datasets.retrieval_v2 import load_dataset
    from evals.tools.check_v2_dataset import check_f20_condition_contributes

    monkeypatch.setattr(module, "ROOT", tmp_path)
    # 造一个只含 billing 查询的文件，却用 sample 数据集去跑
    _write(
        tmp_path / "results" / "v3" / "v3-billing-condition-ablation.json",
        _v3_ablation("billing"),
    )

    ds = load_dataset(DATA / "sample")
    check = check_f20_condition_contributes(ds)

    assert check.applicable, "这不是跨装置，是配置问题"
    assert not check.passed, (
        "有文件但不匹配本数据集，应判失败——"
        "否则'放错文件'会被静默当成'没有产物'"
    )
    assert "不匹配" in check.detail or "不含" in check.detail, (
        f"detail 应说明是配置问题：{check.detail}"
    )


# ---------- 3.1 F24 的"未跑" ----------


def test_f24_not_run_is_not_passed(tmp_path: Path, monkeypatch) -> None:
    """**`F24` 完全没有结果文件时，`passed` MUST 为 False。**

    现状：`result_side_problem = None`（没有文件时不设 problem），
    而 `passed = data_side_ok and result_side_problem is None` -> **True**。
    """
    import evals.tools.check_v2_dataset as module
    from evals.datasets.retrieval_v2 import load_dataset
    from evals.tools.check_v2_dataset import check_f24_axis_a_not_saturated

    monkeypatch.setattr(module, "ROOT", tmp_path)
    (tmp_path / "results").mkdir(parents=True)  # 空目录，没有任何文件

    ds = load_dataset(DATA / "sample")
    check = check_f24_axis_a_not_saturated(ds)

    assert not check.passed, (
        f"没有任何结果文件却 passed=True：{check.detail}。"
        "这是'门禁没跑却报告通过'。"
    )


# ---------- 1.4 分区清单一致 ----------


def test_zone_lists_match() -> None:
    """生产代码扫的分区必须是测试清单的**子集**，且不能缺已有的分区。

    **不能要求完全相等**：测试清单里有 `archive`（历史对照物，故意不扫）
    与 `features`（预留，尚不存在）。生产清单只扫**当前该扫的**。

    判据：

    1. 生产清单的每一项都在测试清单里（防拼错）
    2. `archive` 不在生产清单里（历史对照物不参与）
    3. 测试清单里**实际存在**的分区，除 `archive` 外都必须在生产清单里
    """
    from evals.tools.check_v2_dataset import ZONE_NAMES

    from tests.retrieval.test_results_zones import ZONES

    test_zones = {z for z in ZONES if z != "."}

    # 1. 拼写一致
    assert set(ZONE_NAMES) <= test_zones, (
        f"生产清单有测试清单里没有的分区：{set(ZONE_NAMES) - test_zones}"
    )

    # 2. archive 不参与
    assert "archive" not in ZONE_NAMES

    # 3. 实际存在的分区必须被扫（除 archive）
    results = ROOT / "results"
    existing = {
        d.name
        for d in results.iterdir()
        if d.is_dir() and d.name in test_zones and d.name != "archive"
    }
    missing = existing - set(ZONE_NAMES)
    assert not missing, (
        f"这些分区存在但生产代码没扫：{sorted(missing)}。"
        "它们里面的产物会被静默忽略。"
    )


def test_archive_is_not_scanned() -> None:
    """`archive/` 必须**不在**扫描范围内——它是历史对照物，故意不参与。"""
    from evals.tools.check_v2_dataset import ZONE_NAMES

    assert "archive" not in ZONE_NAMES, (
        "archive 是历史对照物，不该被当前门禁当成产物来源"
    )
