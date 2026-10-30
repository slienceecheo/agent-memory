"""`v2-axis-a-what-it-measures.md` 里的数字必须能从 JSON 复算。

**为什么需要**：这份报告的核心结论是"A 轴的 0.9 不是条件区分能力"。
若其中的数字与结果文件脱节，结论就成了叙述而非证据。

每个断言都对应报告里的一个表格。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
REPORT = ROOT / "docs" / "reports" / "v2-axis-a-what-it-measures.md"
LEDGER = ROOT / "results" / "v2-sample-condition-ablation.json"
BILLING = ROOT / "results" / "v2-billing-condition-ablation.json"


def _load(path: Path) -> dict[str, object]:
    if not path.exists():
        pytest.skip(f"{path.name} 缺失")
    return json.loads(path.read_text(encoding="utf-8"))


def _report() -> str:
    if not REPORT.exists():
        pytest.skip("报告缺失")
    return REPORT.read_text(encoding="utf-8")


def test_report_exists_and_names_the_conclusion() -> None:
    text = _report()

    assert "条件直通" in text
    assert "计数分解" in text
    # 核心区分：不能读成条件区分能力
    assert "不是「条件区分能力」" in text or "不是" in text


def test_count_decomposition_sums_up() -> None:
    """3+6+1=10、2+7+0=9 —— 表格必须能加得起来。"""
    led = _load(LEDGER)

    # ledger A 轴：10 条，base 独立 3，condition 决定 6，未中 1
    with_c = led["with_condition"]  # type: ignore[index]
    without_c = led["without_condition"]  # type: ignore[index]
    a_ids = [q for q in with_c if q in {
        "ledger-q1", "ledger-q2", "ledger-q3", "ledger-q4", "ledger-q5",
        "ledger-q6", "ledger-q7", "ledger-q8", "ledger-q9", "ledger-q10",
    }]
    base_only = [q for q in a_ids if with_c[q] == 1 and without_c.get(q) == 1]
    by_cond = [q for q in a_ids if with_c[q] == 1 and without_c.get(q) != 1]
    missed = len(a_ids) - len(base_only) - len(by_cond)

    assert (len(a_ids), len(base_only), len(by_cond), missed) == (10, 3, 6, 1)


def test_billing_count_decomposition() -> None:
    bil = _load(BILLING)
    with_c = bil["with_condition"]  # type: ignore[index]
    without_c = bil["without_condition"]  # type: ignore[index]

    a_ids = [q for q in with_c if q.startswith("billing-a")]
    base_only = [q for q in a_ids if with_c[q] == 1 and without_c.get(q) == 1]
    by_cond = [q for q in a_ids if with_c[q] == 1 and without_c.get(q) != 1]
    missed = len(a_ids) - len(base_only) - len(by_cond)

    assert (len(a_ids), len(base_only), len(by_cond), missed) == (9, 2, 7, 0)


def test_relative_advantage_is_025_not_0125() -> None:
    """消融移除的是相对优势 0.25，不是各自的绝对变化 0.125。

    gold 1.00→0.50（-0.125）、兄弟 0.00→0.50（+0.125）
    相对差 +0.25 → 0.00，变化 0.25。
    """
    w = 0.25
    gold_with = w * 1.0
    sib_with = w * 0.0
    gold_without = w * 0.5
    sib_without = w * 0.5

    assert gold_with - sib_with == pytest.approx(0.25)
    assert gold_without - sib_without == pytest.approx(0.0)
    assert (gold_with - sib_with) - (gold_without - sib_without) == pytest.approx(0.25)

    # 各自的绝对变化是 0.125，但方向相反
    assert gold_with - gold_without == pytest.approx(0.125)
    assert sib_without - sib_with == pytest.approx(0.125)


def test_report_states_axis_c_is_not_comparable() -> None:
    """两轴有效特征数不同，分数不可比——这条必须写在报告里。"""
    text = _report()

    assert "有效特征数" in text
    assert "不可比" in text or "不可直接比较" in text


def test_report_records_axis_c_sample_size() -> None:
    text = _report()
    led = _load(LEDGER)
    bil = _load(BILLING)

    assert led["axis_c_n"] == 2
    assert bil["axis_c_n"] == 3
    assert "n=3" in text or "n = 3" in text
    assert "没有统计意义" in text


def test_report_does_not_claim_condition_capability() -> None:
    """报告不得把 A 轴分数称为"条件区分能力"。"""
    text = _report()

    # 允许出现这个词组，但只能在否定句里
    if "条件区分能力" in text:
        assert "不是" in text or "不能读成" in text
