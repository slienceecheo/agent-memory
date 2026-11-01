"""窄版规则：运行时数值必须标 case id。

规则（窄）：
  在**结论区**内，一行同时满足以下三条即为违例：
    1. 含"运行时"
    2. 含数值
    3. 没有 case id

**为什么不能扫全文**：这条规则自身的说明也含"运行时"与数字，
扫全文会让它把自己的描述算成输入。实测 N 从 1 变 4，增量全是规则文字。
**一条会改变自己输入的检查，比没有检查更糟。**

所以范围**外置**为常量 `CONCLUSION_SECTION_MARKER`，而不是靠内容模式识别。

**为什么不做全版**（每个数值结论一张符号表）：40+ 个结论里大多数全是常量，
表里全是"—"。样板会让人跳过它，而跳过的规则等于没有。

**为什么现在 0 处违例**：结论区内只有 1 处"运行时 + 数值"，
即 §0.8 符号表的 `d_base = 0.09（q4）`，它已经标了 case。
所以这条规则守着未来，不是守着现在——文档必须写明这个"1"。
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HANDOFF = ROOT / "docs" / "HANDOFF.md"

CASE_RE = re.compile(
    r"\b(?:ledger|billing)-[a-z]*\d+\b"
    r"|\bq\d+\b"
    r"|\bc\d+\b"
    r"|\bpkg-\d\b|\boncall-\d\b"
)
NUM_RE = re.compile(r"\d+\.\d+|\b\d{1,3}\b")

CONCLUSION_SECTION_MARKER = "### 三个变量里，只有 `d_base` 不是配置也不是常量"
CONCLUSION_SECTION_END = "### 方向容易搞反"


def conclusion_text(text: str) -> str:
    """取"结论区"文本：符号表那一段，不含规则描述。"""
    start = text.find(CONCLUSION_SECTION_MARKER)
    if start == -1:
        return ""
    end = text.find(CONCLUSION_SECTION_END, start)
    return text[start:end] if end != -1 else text[start:]


def violations(text: str, *, scan_all: bool = False) -> list[tuple[int, str]]:
    """返回违反"运行时数值必须标 case"的行。

    默认只扫结论区；`scan_all=True` 用于自检样例（裸文本没有小节结构）。
    """
    section = text if scan_all else conclusion_text(text)
    if not section:
        return []
    offset = 0 if scan_all else text.find(section)
    out = []
    for i, line in enumerate(section.splitlines(), 1):
        if "运行时" not in line:
            continue
        if not NUM_RE.search(line):
            continue
        if CASE_RE.search(line):
            continue
        out.append((offset + i, line.strip()))
    return out


def runtime_numeric_lines(
    text: str, *, scan_all: bool = False
) -> list[tuple[int, str]]:
    """结论区内所有"运行时 + 数值"的行（无论是否标了 case）。"""
    section = text if scan_all else conclusion_text(text)
    if not section:
        return []
    offset = 0 if scan_all else text.find(section)
    out = []
    for i, line in enumerate(section.splitlines(), 1):
        if "运行时" not in line:
            continue
        if not NUM_RE.search(line):
            continue
        out.append((offset + i, line.strip()))
    return out


# ---------- 自检：抓得到 / 不误报（内存里造，不碰磁盘） ----------


def test_rule_catches_missing_case_id() -> None:
    """缺 case 的样例必须被报。"""
    sample = "该值是运行时算出的 d_base = 0.09。"
    assert violations(sample, scan_all=True), "规则没抓到缺 case id 的运行时数值"


def test_rule_accepts_line_with_case_id() -> None:
    """补上 case 后必须放行。"""
    sample = "该值是运行时算出的 d_base = 0.09（q4）。"
    assert not violations(sample, scan_all=True), "规则误报了已标 case 的行"


def test_rule_ignores_methodology_lines() -> None:
    """方法论描述不含具体数值结论，不该被报。"""
    sample = "它是常量、配置、假设，还是运行时算出来的？"
    assert not violations(sample, scan_all=True)


def test_rule_ignores_runtime_without_numbers() -> None:
    """只说"运行时算的"但没给数值，不该被报。"""
    sample = "d_base 是运行时算的，逐 case 不同。"
    assert not violations(sample, scan_all=True)


def test_rule_scope_is_external_not_content_based() -> None:
    """范围必须是外部常量，不能靠内容模式识别。

    **这条防的是"规则的说明文字改变规则输出"**：
    若用"排除含'全文只有'的行"这种方式，规则会随自己的写法变化。
    """
    # 同一句放在结论区外，不该被扫到
    outside = (
        "### 某节\n\n"
        "**运行时**的数值 d_base = 0.09 在这里，但不在结论区。\n\n"
        "### 方向容易搞反\n\n"
    )
    assert not violations(outside), "结论区外的文本不该被扫"

    # 同一句放在结论区内，必须被扫到
    inside = (
        f"{CONCLUSION_SECTION_MARKER}\n\n"
        "**运行时**的数值 d_base = 0.09 在这里。\n\n"
        f"{CONCLUSION_SECTION_END}\n"
    )
    assert violations(inside), "结论区内的文本必须被扫"


# ---------- 对真实文档的检查 ----------


def test_handoff_has_no_violation() -> None:
    """当前文档的结论区必须 0 处违例。"""
    text = HANDOFF.read_text(encoding="utf-8")
    bad = violations(text)
    assert not bad, (
        "这些运行时数值缺 case id：\n"
        + "\n".join(f"  {i}: {line[:70]}" for i, line in bad)
    )


def test_handoff_states_how_many_runtime_numeric_lines_exist() -> None:
    """文档必须写明结论区内有几处运行时数值——否则绿得没有信息。"""
    text = HANDOFF.read_text(encoding="utf-8")
    lines = runtime_numeric_lines(text)
    n = len(lines)

    assert n >= 1, "结论区内找不到运行时数值，规则失去意义"

    marker = f"结论区内只有 **{n}** 处运行时数值"
    assert marker in text, (
        f"文档没写明「{marker}」。实测行号：{[i for i, _ in lines]}"
    )
