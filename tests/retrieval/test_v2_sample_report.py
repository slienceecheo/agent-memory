"""v2 样例报告与可复算结果的一致性。

**为什么需要**：`docs/reports/v2-sample-validation.md` 曾被写成
"L6b ✅ 12/12"，而代码里 `embedding=` 出现 0 次。报告与代码对不上，
两份都"看起来对"——这正是 C4 缺陷 6 的同型。

本文件把报告里每一个数字钉到 `results/v2-sample-gates.json` 与实时计算上。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from evals.datasets.retrieval_v2 import Axis, load_dataset
from evals.metrics.v2_baselines import axis_baseline, competing_set

ROOT = Path(__file__).resolve().parents[2]
SAMPLE = ROOT / "data" / "retrieval-v2" / "sample"
GATES = ROOT / "results" / "v2-sample-gates.json"
REPORT = ROOT / "docs" / "reports" / "v2-sample-validation.md"


@pytest.fixture(scope="module")
def dataset():
    if not SAMPLE.exists():
        pytest.skip("样例数据集尚未生成")
    return load_dataset(SAMPLE)


def test_report_exists() -> None:
    assert REPORT.exists()


def test_gates_result_exists_and_matches_report() -> None:
    """报告里写的"12/16"必须能从 JSON 复算。"""
    if not GATES.exists():
        pytest.skip("门禁结果缺失")

    results = json.loads(GATES.read_text(encoding="utf-8"))
    passed = sum(1 for r in results if r["passed"])
    text = REPORT.read_text(encoding="utf-8")

    assert f"{passed}/{len(results)}" in text, (
        f"报告与实际不一致：实际 {passed}/{len(results)}"
    )


def test_four_gates_fail_and_are_named() -> None:
    """L6a/L6b/L7-L8/F6 必须在报告里被明确标为未通过。

    若有人偷偷把它们改成 ✅ 而不修代码，这里会失败。
    """
    if not GATES.exists():
        pytest.skip("门禁结果缺失")

    results = {r["code"]: r["passed"] for r in json.loads(GATES.read_text(encoding="utf-8"))}

    assert results["L6a"] is False, "三路召回现在都调用了？请更新报告与协议"
    assert results["L6b"] is False, "池构造开始写向量了？请更新报告与协议"
    assert results["L7/L8"] is False, "dedup 入参修好了？请更新报告与协议"
    assert results["F6"] is False


def test_report_marks_l6b_as_not_done() -> None:
    """报告不得把 L6b 写成已完成——代码里没有 embedding 调用。"""
    source = (ROOT / "evals" / "tools" / "sample_pool_check.py").read_text(encoding="utf-8")
    dataset_source = (ROOT / "evals" / "datasets" / "retrieval_v2.py").read_text(encoding="utf-8")

    assert "embedding=" not in source
    assert "embedding=" not in dataset_source

    text = REPORT.read_text(encoding="utf-8")
    assert "L6b" in text
    assert "❌" in text


def test_report_query_ids_match_data(dataset) -> None:
    """报告里的 query_id 必须真实存在。

    之前那份报告写的是 `q-oncall-night`、`q-style-implicit`，
    而数据里是 `ledger-q1`…`ledger-q12`。报告与数据对不上时，
    读者无从核对任何一个数字。
    """
    text = REPORT.read_text(encoding="utf-8")
    actual = {q.query_id for q in dataset.queries}

    referenced = {
        token.strip("`*| ")
        for token in text.replace("`", " ").split()
        if token.startswith("ledger-q")
    }
    assert referenced, "报告里没有引用任何 query_id"
    unknown = {r for r in referenced if r.rstrip("|*") not in actual}
    assert not unknown, f"报告引用了不存在的 query_id：{sorted(unknown)}"


def test_report_axis_baselines_match_computation(dataset) -> None:
    """报告里 A/C 轴的随机基线必须与精确计算一致。"""
    text = REPORT.read_text(encoding="utf-8")
    a = axis_baseline(dataset, Axis.A)
    c = axis_baseline(dataset, Axis.C)

    assert f"{a.seh_at_k:.4f}" in text
    assert f"{a.seh_at_1:.4f}" in text
    assert f"{c.seh_at_k:.4f}" in text
    assert f"{c.seh_at_1:.4f}" in text


def test_report_states_axis_a_saturation_is_geometric(dataset) -> None:
    """报告必须说明 A 轴饱和是几何必然，不是"数据不够多"。"""
    text = REPORT.read_text(encoding="utf-8")

    assert "恒等于" in text or "恒为" in text
    assert "6" in text  # required_pool_size_for(5, 0.95) == 6
    baseline = axis_baseline(dataset, Axis.A)
    assert baseline.saturates_at_k


def test_implicit_ratio_uses_axis_a_denominator(dataset) -> None:
    """F13 的分母是 A 轴查询，不是全部查询。

    样例在 A 轴分母下是 40.0%（达标），在全部查询分母下是 33.3%（不达标）。
    口径必须在冻结前钉死，否则事后可以挑好看的那个。
    """
    a_queries = [q for q in dataset.queries if q.axis is Axis.A]
    a_implicit = sum(1 for q in a_queries if q.cue_type.value == "implicit")
    all_implicit = sum(1 for q in dataset.queries if q.cue_type.value == "implicit")

    assert a_implicit / len(a_queries) == pytest.approx(0.40)
    assert all_implicit / len(dataset.queries) < 0.40

    text = REPORT.read_text(encoding="utf-8")
    assert "A 轴查询" in text and "分母" in text


def test_competing_set_sizes_match_report(dataset) -> None:
    """竞争集大小必须与报告里的 3–4（A 轴）一致。"""
    a_sizes = {
        len(competing_set(dataset, q)) for q in dataset.queries if q.axis is Axis.A
    }

    assert a_sizes == {3, 4}
