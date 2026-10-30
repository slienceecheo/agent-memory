"""交接文档的"最小可读集"与"表述模板"必须存在。

**为什么需要**：

1. HANDOFF 有 400+ 行。第一次读的人不一定知道该停在哪，
   所以要标出"最小可读集"。

2. 这一路反复出现"结论对，但表述的范围比证据大"：
   "只有文档改动"、"池 100% 来自 dev"、"向量救回 4/4"、"A 轴 0.9000"。
   而 §0.1 的写法是唯一接近"完整表述"的段落，应当作为模板固定下来。

第 2 条尤其重要：它是**防止下一个结论又写得过宽**的唯一办法。
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


def test_minimal_reading_set_is_stated_up_front() -> None:
    """开头必须标出"只读一节就读 §0 和 §0.1"。"""
    text = _text()
    head = text[: text.index("## 0. 当前状态")]

    assert "只读一节" in head
    assert "§0" in head and "§0.1" in head
    # 说明其余章节是展开
    assert "展开" in text[:1000]


def test_expression_template_section_exists() -> None:
    """必须有"表述模板"一节，且列出这一路写宽过的句子。"""
    text = _text()

    assert "表述的模板" in text
    assert "范围比证据大" in text
    # 四个实例
    for phrase in ("只有文档改动", "池 100% 来自 dev", "向量救回", "A 轴 0.9000"):
        assert phrase in text, f"未列入 {phrase}"


def test_template_lists_the_five_steps() -> None:
    """模板必须给出可操作的步骤，不是"要写完整"这种空话。"""
    text = _text()
    section = text.split("表述的模板")[1].split("## ")[0]

    assert "先说差异存在" in section
    assert "逐项列出" in section
    assert "影响判断" in section
    assert "验证方式" in section
    assert "写根因" in section


def test_template_states_the_limit_of_automation() -> None:
    """必须写明"这个 diff 影不影响数字"无法自动化。

    这是 §0.1 那种人工说明存在的理由——
    如果自动化能做，就不需要写那么多。
    """
    text = _text()
    section = text.split("表述的模板")[1].split("## ")[0]

    assert "结构性事实" in section
    assert "必须人来判断" in section
    assert "git diff" in section


def test_reproduction_test_skips_when_results_missing() -> None:
    """重跑验证的测试必须在依赖缺失时 skip，不能 fail。

    否则它会把"环境不全"报成"门禁判定不一致"——
    那是把缺条件说成结论错误，与"装置没接上却当成世界的性质"同型。
    """
    path = ROOT / "tests" / "retrieval" / "test_fingerprint_tag_consistency.py"
    text = path.read_text(encoding="utf-8")
    section = text.split("def test_gate_verdicts_still_reproduce")[1]

    # 必须先检查依赖再跑
    assert "pytest.skip" in section
    assert "condition-ablation" in section or "ablation" in section
    # 且说明为什么不调网络
    assert "不导入 embedding" in section or "不调网络" in section
