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


def test_v3_options_have_a_stated_lean() -> None:
    """三个装置选项不能只并列——必须写出倾向。

    否则下一次会话会花一轮重新评估，而那轮正是最容易凭直觉判断的。
    """
    text = _handoff()
    section = text.split("### v3 的装置选项")[1].split("### v3 的数据纪律")[0]

    assert "倾向 c" in section
    # 三条理由
    assert "理由三条" in section
    # 必须说明 a 与 b 的差别比看起来小
    assert "差别比看起来小" in section


def test_v3_lean_states_the_condition_that_would_overturn_it() -> None:
    """倾向必须写明"什么条件下会被推翻"，否则它就成了决定。"""
    text = _handoff()
    section = text.split("### v3 的装置选项")[1].split("### v3 的数据纪律")[0]

    assert "这不是决定" in section
    assert "廉价解法" in section or "可能更优" in section


def test_v3_lean_reason_is_query_side_not_data_side() -> None:
    """理由必须落在"查询侧"，不能落在"槽位表覆盖不了"。

    实测：19 个条件值**全部能归入 7 个父槽位**。
    所以"覆盖不了"是错的，真正的成本在查询侧映射。
    """
    text = _handoff()
    section = text.split("### v3 的装置选项")[1].split("### v3 的数据纪律")[0]

    assert "查询侧" in section
    # 必须点明 implicit 查询不含条件词
    assert "implicit" in section
    assert "0/10" in section
    # 必须承认槽位是可分的
    assert "7 个槽位" in section or "region" in section


def test_methodology_section_exists_with_costs() -> None:
    """方法论一节必须给出探针成本，不能只说"要跑探针"。"""
    text = _handoff()

    assert "听起来合理" in text
    # 四个判断
    assert "两轴只剩池大小不同" in text
    assert "value 太短" in text
    assert "不要造只差两字" in text
    assert "c2 是层级错位" in text
    # 成本
    assert "1 分钟" in text


def test_methodology_gives_a_criterion_not_an_exhortation() -> None:
    """必须给出可操作的判据，不是"要谨慎"这种空话。"""
    text = _handoff()
    marker = "### 对"
    start = text.find(marker)
    assert start != -1, "找不到方法论一节"
    end = text.find("### 表述的模板", start)
    assert end != -1
    section = text[start:end]

    assert "不需要数据就能讲通" in section
    # 必须解释为什么这类判断危险
    assert "叙述的连贯性" in section or "叙述连贯" in section


def test_condition_slots_are_actually_groupable() -> None:
    """数据必须支持"19 个值可归入 7 个父槽位"。"""
    import sys

    sys.path.insert(0, str(ROOT))
    from evals.datasets.retrieval_v2 import load_dataset

    values: set[str] = set()
    for name in ("sample", "billing"):
        ds = load_dataset(ROOT / "data" / "retrieval-v2" / name)
        values |= {m.condition for m in ds.memories if m.condition}

    assert len(values) == 19, f"条件值数量变了：{len(values)}"


# ---------- v3 验收判据 ----------


def test_v3_acceptance_uses_wilson_not_bootstrap() -> None:
    """判据必须用 Wilson，且写明为什么不用 bootstrap。"""
    text = _handoff()
    section = text.split("### v3 的验收判据")[1].split("### v3 的数据纪律")[0]

    assert "Wilson" in section
    assert "bootstrap" in section
    # 必须给出坍缩的实测证据
    assert "2/2" in section
    assert "[1.0, 1.0]" in section or "1.0, 1.0" in section


def test_v3_acceptance_has_no_hard_n_floor() -> None:
    """**不得设 n 的硬下限**——那会把"更严"说成"无定义"。"""
    text = _handoff()
    section = text.split("### v3 的验收判据")[1].split("### v3 的数据纪律")[0]

    assert "不设" in section and "硬下限" in section
    # 必须解释为什么
    assert "更严" in section
    assert "无定义" in section


def test_v3_acceptance_records_rejected_justifications() -> None:
    """两条被推翻的依据必须写明，防止有人重新提出来。"""
    text = _handoff()
    section = text.split("### v3 的验收判据")[1].split("### v3 的数据纪律")[0]

    assert "宽度 < 0.5" in section
    assert "0.527" in section  # 实测反例
    assert "收敛" in section


def test_v3_minimum_hits_table_matches_module() -> None:
    """HANDOFF 里那张表必须与 `evals.metrics.wilson` 的实现一致。"""
    import sys

    sys.path.insert(0, str(ROOT))
    from evals.metrics.wilson import minimum_hits_to_beat

    baseline = 1 / 3  # billing A 轴
    expected = {4: "4/4", 5: "4/5", 6: "5/6", 9: "6/9", 10: "7/10", 20: "11/20"}

    text = _handoff()
    section = text.split("### v3 的验收判据")[1].split("### v3 的数据纪律")[0]

    for n, label in expected.items():
        want = minimum_hits_to_beat(baseline, n)
        hits, total = (int(x) for x in label.split("/"))
        assert (hits, total) == (want, n), f"n={n}: 模块给 {want}/{n}，手写 {label}"
        assert label in section, f"HANDOFF 未写 {label}"


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
