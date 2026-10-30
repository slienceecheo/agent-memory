"""HANDOFF 的 v3 段落必须反映实测结论，不是旧方案。

**两条被实测推翻的说法**：

1. "v3 第一步是造更难的干扰项" —— 缺陷 13 让同 key 的条目一条都进不了池，
   所以"base 分接近"的干扰项在结构上无法构造。v3 第一步必须是改装置。

2. "B 轴有一层阻塞（召回层）" —— 实际有两层，第二层是池构造。
   即使召回层修好，池里也放不下。

这两条都容易在后续编辑中被改回旧说法，所以钉住。
"""

from __future__ import annotations

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
HANDOFF = ROOT / "docs" / "HANDOFF.md"
REPORT = ROOT / "docs" / "reports" / "c4-retrieval.md"


def _handoff() -> str:
    if not HANDOFF.exists():
        pytest.skip("HANDOFF 缺失")
    return HANDOFF.read_text(encoding="utf-8")


def test_handoff_says_first_step_is_device_not_data() -> None:
    """必须写明"A 的第一步是改装置，不是改数据"。"""
    text = _handoff()

    assert "A 的第一步是改装置" in text
    # 必须给出原因：三条约束
    assert "同 key 的干扰项一条都进不了池" in text or "一条都进不了池" in text


def test_handoff_lists_three_constraints() -> None:
    """三条约束必须都写出来，否则"无法靠造数据消除"这个结论没有依据。"""
    text = _handoff()
    section = text.split("A 的第一步是改装置")[1].split("### v3 的数据纪律")[0]

    assert "query_condition" in section
    assert "condition_match = 1.00" in section
    assert "base 差 < 0.25" in section


def test_handoff_lists_three_device_options() -> None:
    """必须给出三个选项（部分匹配 / 文本推断 / 不参与排序）。"""
    text = _handoff()
    section = text.split("A 的第一步是改装置")[1].split("### v3 的数据纪律")[0]

    assert "部分匹配" in section
    assert "文本推断" in section
    assert "不参与排序" in section


def test_handoff_says_b_axis_has_two_layers() -> None:
    """B 轴必须写成"两层阻塞"，不是一层。"""
    text = _handoff()

    assert "两层阻塞" in text
    assert "缺陷 13" in text
    # 第二层必须点明是池构造
    assert "池构造" in text


def test_v3_data_discipline_is_marked_provisional() -> None:
    """v3 的数据纪律必须标为"待确认"，不能写成已生效规范。

    理由：它现在只是一条判断，还没被任何 v3 决策检验过。
    """
    text = _handoff()
    section = text.split("### v3 的数据纪律")[1]

    assert "待 v3 变更确认" in section or "还没有被任何一次 v3 决策检验过" in section
    # 已知边界必须写
    assert "已知边界" in section
    assert "不知道 v3 自己的" in section or "不指" in section


def test_report_upgraded_defect13_impact() -> None:
    """C4 报告的缺陷 13 必须升级为"同 key 全部丢弃"。"""
    if not REPORT.exists():
        pytest.skip("报告缺失")
    text = REPORT.read_text(encoding="utf-8")

    assert "缺陷 13 的完整影响面" in text
    assert "同 key 全部丢弃" in text
    # 两层阻塞的说明
    assert "池构造层" in text
    assert "B 轴不支持" in text or "两层阻塞" in text
