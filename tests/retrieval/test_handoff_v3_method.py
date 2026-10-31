"""HANDOFF §0.4–0.6：工具选型、v3 方法选择、缺陷与标记的计数关系。

**三条各自防一种误读**：

| 节 | 防什么误读 |
|---|---|
| 0.4 | 把"选 Wilson"读成"它更先进"，而不是"适用规模匹配" |
| 0.5 | 把"补区间"当成实现细节，而它其实是 spec 变更 |
| 0.6 | 把"27 个标记"读成"27 条缺陷" |
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


def _section(number: str, next_number: str) -> str:
    text = _text()
    start = text.find(f"### {number} ")
    end = text.find(f"### {next_number} ")
    assert start != -1, f"找不到 §{number}"
    return text[start:end] if end != -1 else text[start:]


# ---------- 0.4 工具选型 ----------


def test_section_0_4_states_the_selection_criterion() -> None:
    """判据必须是"样本规模匹配"，不是"方法先进性"。"""
    section = _section("0.4", "0.5")

    assert "样本规模匹配" in section
    assert "不是方法先进" in section or "不是**方法先进" in section


def test_section_0_4_has_both_tools_with_scale() -> None:
    """两个工具及其适用规模都要写。"""
    section = _section("0.4", "0.5")

    assert "proportion_ci" in section
    assert "wilson_interval" in section
    assert "零宽" in section
    # 必须说明 bootstrap 的退化是"有意"的，不是 bug
    assert "有意" in section
    # 以及它缺什么
    assert "没有声明适用规模" in section


def test_section_0_4_records_the_6_of_9_disagreement() -> None:
    """关键实证：6/9 两法结论相反。"""
    section = _section("0.4", "0.5")

    assert "6/9" in section
    assert "0.3333" in section
    assert "0.3542" in section


# ---------- 0.5 v3 的方法选择 ----------


def test_section_0_5_says_it_is_a_spec_change() -> None:
    """必须写明"方法选择是 spec 变更"，不是实现细节。"""
    section = _section("0.5", "0.6")

    assert "spec 变更" in section
    assert "不能在数据阶段决定" in section


def test_section_0_5_lists_four_options() -> None:
    """四个选项都要在，且倾向要写明。"""
    section = _section("0.5", "0.6")

    for mark in ("甲", "乙", "丙", "丁"):
        assert f"| **{mark}** |" in section or f"| {mark} |" in section, (
            f"缺选项 {mark}"
        )
    assert "倾向丁" in section
    # 双报
    assert "双报" in section


def test_section_0_5_records_why_a_is_rejected() -> None:
    """甲（用 bootstrap 接受退化）必须被明确拒绝，并给出类比。"""
    section = _section("0.5", "0.6")

    assert "形式达标但无信息" in section or "门禁绿了" in section
    # 与已有形态类比
    assert "SEH@5 = 1.000" in section or "paths_unwired" in section


def test_spec_really_says_paired_resampling() -> None:
    """数据必须支持"spec 要求配对重采样"。"""
    spec = ROOT / "openspec" / "specs" / "evaluation-harness" / "spec.md"
    if not spec.exists():
        pytest.skip("spec 缺失")

    text = spec.read_text(encoding="utf-8")
    assert "配对重采样" in text, "spec 不再要求配对重采样——§0.5 的前提变了"


# ---------- 0.6 计数关系 ----------


def test_section_0_6_separates_defects_from_markers() -> None:
    """必须区分"22 条缺陷"与"27 个标记"。"""
    section = _section("0.6", "未通过的门禁")

    assert "22 条缺陷" in section
    assert "27 个" in section
    assert "29 条收集" in section


def test_section_0_6_explains_both_gaps() -> None:
    """两个差值都要解释：22→27 与 27→29。"""
    section = _section("0.6", "未通过的门禁")

    # 22 -> 27：多标记 + 已修复的用正向断言
    assert "+5" in section
    assert "正向断言" in section
    # 27 -> 29：parametrize
    assert "+2" in section
    assert "parametrize" in section


def test_counts_match_reality() -> None:
    """三个数字必须与清单和标记一致。"""
    import ast
    import sys

    sys.path.insert(0, str(ROOT))
    from tests.retrieval.test_locked_defect_manifest import DEFECT_TESTS, REPAIRED

    defects = len(set(DEFECT_TESTS) | set(REPAIRED))
    assert defects == 22, f"缺陷编号数变成 {defects}"

    markers = 0
    for path in (ROOT / "tests").rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                for dec in node.decorator_list:
                    if "locked_defect" in ast.unparse(dec):
                        markers += 1
    assert markers == 27, f"标记数变成 {markers}"


def test_section_numbers_are_sequential() -> None:
    """§0 的小节编号必须连续，不能跳号或乱序。

    实测问题：插入 0.4/0.5/0.6 时把 0.2/0.3 挤到了后面，
    顺序变成 0.1 → 0.4 → 0.5 → 0.6 → 0.2 → 0.3。
    """
    import re

    text = _text()
    numbers = [
        m.group(1)
        for m in re.finditer(r"^### 0\.(\d+) ", text, re.M)
    ]
    assert numbers, "找不到 §0 的小节"
    expected = [str(i) for i in range(1, len(numbers) + 1)]
    assert numbers == expected, f"编号乱序：{numbers}"
