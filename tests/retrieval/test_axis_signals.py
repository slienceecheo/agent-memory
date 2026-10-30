"""A/C 两轴的可利用信号不同，且 billing C 轴 0/3 有三个层次。

**两条纠正**：

1. 我曾判断"去掉 condition 后两轴只剩池大小不同，应该合并"。
   实测不成立：A 轴候选的 relation 恒定（零信息），C 轴候选的 relation 大多不同。

2. 我曾写"v3 的数据不要造只差两字的 value"。
   那是让数据迁就向量的能力不足，与"为了让测试通过而改数据"同形。
   正确做法是承认向量在短同构串上的边界，并写进报告。
"""

from __future__ import annotations

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
HANDOFF = ROOT / "docs" / "HANDOFF.md"


def _text() -> str:
    if not HANDOFF.exists():
        pytest.skip("HANDOFF 缺失")
    return HANDOFF.read_text(encoding="utf-8")


def test_axes_signal_section_exists() -> None:
    """必须有"A/C 两轴的区别不是池大小"这一节。"""
    text = _text()

    assert "不是池大小" in text
    assert "可利用信号" in text
    # 明确说不合并
    assert "不要因为" in text and "合并两轴" in text


def test_axes_signal_table_has_measured_numbers() -> None:
    """表格必须带实测数字，不能只写"relation 大多不同"。"""
    text = _text()
    section = text.split("不是池大小")[1].split("### billing C 轴")[0]

    assert "24/24" in section  # ledger A 同 relation
    assert "18/18" in section  # billing A 同 relation
    assert "22/22" in section  # ledger C 异 relation
    assert "6/24" in section   # billing C 同 relation 兄弟


def test_c_axis_has_three_layers() -> None:
    """billing C 轴必须归因到三个层次，不是一个。"""
    text = _text()
    section = text.split("### billing C 轴 0/3 的归因")[1].split("### 不做的")[0]

    assert "查询设计" in section
    assert "向量能力" in section
    assert "数据表示" in section
    # 三者的可修性不同
    assert "改查询" in section
    assert "固有局限" in section
    assert "迁就" in section


def test_probe_results_are_recorded() -> None:
    """探针的三条结果必须写下来（2 条改善、1 条无变化）。"""
    text = _text()
    section = text.split("### billing C 轴 0/3 的归因")[1].split("### 不做的")[0]

    assert "2 → 1" in section  # c1 或 c3
    assert "2 → 2" in section  # c2 无变化
    assert "3 → 1" in section  # c3


def test_c2_is_systematic_not_random() -> None:
    """必须写明 c2 是系统性偏差，且给出随机基线对照。"""
    text = _text()
    section = text.split("### billing C 轴 0/3 的归因")[1].split("### 不做的")[0]

    assert "系统性偏差" in section
    assert "5/5" in section
    assert "1/9" in section or "0.111" in section


def test_no_value_length_prescription() -> None:
    """**核心**：不得写"v3 的数据不要造只差两字的 value"。

    那是让数据迁就向量，与"通过设计数据让指标好看"同形。
    """
    text = _text()

    # 允许作为被否定的说法出现
    if "不要造只差两字" in text:
        assert "迁就" in text or "不做" in text, "该说法未被否定"

    # 必须明确写出"不做"
    assert "不要为了" in text and "把 value 写长" in text
    # 必须解释为什么
    assert "避开" in text and "真实世界" in text
    # 必须与 C4 类比
    assert "SEH@5 = 1.000" in text or "SEH@5=1.000" in text


def test_report_states_vector_boundary_not_data_rule() -> None:
    """结论必须是"承认向量边界"，不是"数据要避开"。"""
    text = _text()

    assert "短同构串" in text
    assert "精确匹配" in text
    # 产品决策
    assert "什么时候该用向量" in text or "产品决策" in text


def test_axis_signal_counts_match_data() -> None:
    """数据必须支持表格里的四个数字。"""
    import sys

    sys.path.insert(0, str(ROOT))
    from evals.datasets.retrieval_v2 import Axis, load_dataset
    from evals.metrics.v2_baselines import competing_set

    expected = {
        ("sample", Axis.A): (24, 24),
        ("sample", Axis.C): (0, 22),
        ("billing", Axis.A): (18, 18),
        ("billing", Axis.C): (6, 24),
    }

    for (name, axis), (want_same, want_total) in expected.items():
        ds = load_dataset(ROOT / "data" / "retrieval-v2" / name)
        same = total = 0
        for q in ds.queries:
            if q.axis is not axis:
                continue
            gold = ds.memory(q.gold_memory_id)
            for m in competing_set(ds, q):
                if m.memory_id == gold.memory_id:
                    continue
                total += 1
                if m.relation == gold.relation:
                    same += 1
        assert (same, total) == (want_same, want_total), (
            f"{name}/{axis.value}: 实测 {same}/{total}，报告写 {want_same}/{want_total}"
        )
