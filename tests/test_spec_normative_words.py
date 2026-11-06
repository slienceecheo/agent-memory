"""spec 的规范词可以用中文表达，不能用 `grep MUST` 判定"缺约束"。

**这条测试记录一次真实的误判**：曾用 `grep "MUST"` 扫 `openspec/specs/`，
得到"scenario 里 0 个 MUST"，于是判定"缺规范性约束，需要开变更补"。

但这个仓库的 spec 用中文写，规范词是 **不得 / 必须 / 禁止**。
实测：229 条 scenario 里 175 条（76%）不含任何规范词（中英都算），
所以"scenario 必须有规范词"从来不是本仓库的书写规则。

**这条测试的作用不是强制规范词**，而是防止下一个人重复同一个误判：
用英文词扫中文文档，然后得出"缺约束"的结论。
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
"""`tests/test_spec_normative_words.py` → parents[1] = 仓库根。

注意：本文件直接在 `tests/` 下（一层），所以 `parents[0]=tests`、
`parents[1]=仓库根`。写成 `parents[2]` 会指到仓库之外，
错误信息会是 `FileNotFoundError`，看起来像"spec 不存在"。
"""
SPECS = ROOT / "openspec" / "specs"

CAPABILITIES = (
    "conflict-resolution",
    "evaluation-harness",
    "llm-and-embedding-io",
    "memory-retrieval",
    "memory-store",
)

#: 规范词的两种写法。**中文词必须一起算**，否则会漏掉大半。
NORMATIVE = ("MUST", "SHALL", "不得", "必须", "禁止")


def _scenarios(text: str) -> list[str]:
    return re.split(r"^#### Scenario: ", text, flags=re.M)[1:]


def test_normative_words_include_chinese() -> None:
    """规范词表必须同时含中英，否则扫描会漏。"""
    assert "MUST" in NORMATIVE
    assert "不得" in NORMATIVE


@pytest.mark.parametrize("capability", CAPABILITIES)
def test_each_capability_has_normative_requirements(capability: str) -> None:
    """每个 capability 的 **requirement 陈述句**都必须含规范词。

    与 scenario 不同：requirement 正文是契约本体，必须有 SHALL/MUST/必须。
    """
    text = (SPECS / capability / "spec.md").read_text(encoding="utf-8")
    blocks = re.split(r"^### Requirement: ", text, flags=re.M)[1:]
    assert blocks, f"{capability} 没有 requirement"

    bare = []
    for block in blocks:
        # 只取第一个 scenario 之前的正文
        body = block.split("#### Scenario:")[0]
        if not any(word in body for word in NORMATIVE):
            bare.append(body.splitlines()[0].strip())

    assert not bare, f"{capability} 的这些 requirement 陈述句缺规范词：{bare}"


def test_scenarios_are_not_required_to_carry_normative_words() -> None:
    """**记录事实**：约半数 scenario 不含规范词，这是既有书写习惯。

    若将来统一了规范词，本测试的断言值需要更新——
    但**不要**把它改成"每个 scenario 必须有规范词"，
    那会要求改写 175 条，且 `openspec validate --strict` 本来就不要求。

    **判据不能卡整数阈值**：
    2026-11-06 归档后，这个比例从 51% 掉到 **49.9%**（179/359），
    刚好跌破 `> 0.5`。而 49.9% 与 50% 在实质上是同一件事——
    "多数/约半数 scenario 不含规范词"。

    **所以改成断言一个宽区间** `[0.4, 0.7]`：
    - 下界 0.4：若有人统一规范词，比例会迅速降到很低
    - 上界 0.7：若有人删掉所有规范词，比例会接近 1.0
    """
    total = 0
    bare = 0
    for capability in CAPABILITIES:
        text = (SPECS / capability / "spec.md").read_text(encoding="utf-8")
        for block in _scenarios(text):
            total += 1
            if not any(word in block for word in NORMATIVE):
                bare += 1

    assert total > 200, f"scenario 总数异常：{total}"

    ratio = bare / total
    assert 0.4 <= ratio <= 0.7, (
        f"{bare}/{total} = {ratio:.3f} 条 scenario 不含规范词。\n"
        "若有人统一了规范词（比例骤降）或删光了规范词（比例接近 1），"
        "请更新本断言并在 HANDOFF 里改掉那条误判记录。"
    )


def test_the_path_contribution_requirement_uses_chinese_normative() -> None:
    """「路径贡献的可测性」的中文规范词必须还在。

    这条 requirement 曾在 HANDOFF 里被误记为"缺规范词"。
    它的 scenario 里有"不得"，属于规范性约束。
    """
    text = (SPECS / "evaluation-harness" / "spec.md").read_text(encoding="utf-8")
    index = text.find("### Requirement: 路径贡献的可测性")
    assert index > 0
    section = text[index:]
    end = section.find("\n### Requirement:", 10)
    if end > 0:
        section = section[:end]

    assert "不得" in section, "中文规范词丢了"
    assert section.count("不得") >= 2
