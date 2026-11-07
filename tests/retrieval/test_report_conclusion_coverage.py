"""§1.1 的分类表必须覆盖 §1 表格的每一条结论。

**为什么需要**：`test_report_classifies_conclusions_by_third_party_need`
只检查三个关键词存在（"是否需要第三方" / "代码事实" / "涉及查询设计"），
**结论 5 缺席时它仍然绿**——那是"覆盖范围被高估"的形态。

本文件用集合相等替代关键词存在：
从 §1 表格取结论编号，从 §1.1 表格的"结论"列取编号，断言两者相等。
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
REPORT = ROOT / "docs" / "reports" / "v2-what-it-measures.md"


def _report() -> str:
    if not REPORT.exists():
        pytest.skip("报告缺失")
    return REPORT.read_text(encoding="utf-8")


def _section_by_prefix(text: str, prefix: str) -> str:
    """取出以 `prefix` 开头的一节，**到最近的二级或三级标题为止**。

    **为什么不能只用 `split("\\n## ")`**：若该节后面出现 `### 1.1.1`，
    切出的范围会把子节一起包进来，于是"分类表"里混进别处的编号。
    这个坑本项目踩过：插入 `6.12.4` 后 `6.12.5` 的边界找不到，
    后面的内容全被包进那一节。

    所以取 `\\n## ` 与 `\\n### ` 中**更近的那个**作为终点。
    """
    rest = text.split(prefix, 1)[1]
    candidates = [
        i for i in (rest.find("\n## "), rest.find("\n### ")) if i >= 0
    ]
    return rest[: min(candidates)] if candidates else rest


def test_every_conclusion_is_classified() -> None:
    """§1.1 的分类表必须覆盖 §1 表格里的**每一条**结论。

    判据是**集合相等**，不是"关键词出现"：

    | 写法 | 结论 5 缺席时 |
    |---|---|
    | `assert "涉及查询设计" in text` | **仍然绿** |
    | 集合相等 | **红** |

    **附带查出的事实**：初版这条断言第一次跑就红，
    `sec1={1,2,3,4,5}` vs `classified={1,2,3,4}`——确认了缺失。
    """
    text = _report()

    # §1 表格：| 1 | 结论 | 复算输入 | 强度 |
    sec1 = _section_by_prefix(text, "## 1. ")
    sec1_ids = set(re.findall(r"^\| (\d) \|", sec1, re.M))
    assert len(sec1_ids) >= 5, f"§1 表格只找到 {sorted(sec1_ids)}"

    # §1.1 分类表：| **装置实现** | 2、3、4 | ... |
    sec11 = _section_by_prefix(text, "### 1.1 ")
    classified: set[str] = set()
    for row in re.findall(r"^\| \*\*[^|]+\*\*[^|]*\|([^|]+)\|", sec11, re.M):
        classified |= set(re.findall(r"\d", row))

    missing = sec1_ids - classified
    extra = classified - sec1_ids
    assert not missing, (
        f"§1.1 的分类表漏了结论 {sorted(missing)}。\n"
        f"§1 有 {sorted(sec1_ids)}，分类表只有 {sorted(classified)}。\n"
        "**这不是排版问题**：未分类的结论没有'它的局限是什么、怎么消除'的说明，\n"
        "读者会把它当成与代码事实同等的结论。"
    )
    assert not extra, (
        f"§1.1 分类表里有 §1 不存在的结论编号 {sorted(extra)}"
    )


def test_section_1_1_states_all_three_dependency_kinds() -> None:
    """§1.1 必须同时写出三种依赖：装置实现 / 查询表述 / 分析口径。

    **为什么是三种不是两种**：结论 5 的局限既不是"装置怎么算"，
    也不是"作者怎么写 query"，而是"配对集怎么划定"——
    配对集恰好等于 lexical 的召回集（实测 6/6、9/9），
    所以它衡量的是"两者都召回的 case 上谁排得准"，
    而 threeway 独有召回的 7 条（4+3）**完全没进这个指标**
    （那 7 条上 threeway 的 top-1 也是 0，因此它既没被计入优势也没被计入劣势）。

    把这三种并成两种，会让读者以为"找个第三方重写 query"就能解决结论 5。
    """
    text = _report()
    sec11 = _section_by_prefix(text, "### 1.1 ")

    for kind in ("装置实现", "查询表述", "分析口径"):
        assert kind in sec11, f"§1.1 缺依赖类型「{kind}」"

    # 每种依赖都必须说"怎么消除"——否则读者无法判断结论还能不能用
    assert "消除" in sec11, "§1.1 没有说明各局限怎么消除"
