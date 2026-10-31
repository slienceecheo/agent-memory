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


# ---------- 0.5 双报判据 ----------


def test_dual_interval_gap_is_used_as_a_flag() -> None:
    """必须写明"用两区间下界的差标记 bootstrap 是否可信"。

    这比"选一个方法"更好：把"需要判断 n 够不够"变成"看一个可观测的量"。
    """
    text = _text()
    section = text.split("### 双报的判据")[1].split("### 0.6")[0]

    assert "差距本身" in section
    assert "0.021" in section   # 6/9 一致
    assert "0.299" in section   # 9/9 分歧
    assert "0.658" in section   # 2/2 严重分歧
    # 阈值规则
    assert "> 0.1" in section
    assert "以 Wilson 为准" in section


def test_dual_interval_gap_numbers_are_real() -> None:
    """三个差距必须能从模块复算。"""
    import sys

    sys.path.insert(0, str(ROOT))
    from evals.metrics.wilson import wilson_interval

    from memory.eval.bootstrap import proportion_ci

    cases = [(6, 9, 0.021), (9, 9, 0.299), (2, 2, 0.658)]
    for k, n, expected_gap in cases:
        boot = proportion_ci([True] * k + [False] * (n - k), seed=0)
        wilson = wilson_interval(k, n)
        gap = abs(boot.low - wilson.low)
        assert gap == pytest.approx(expected_gap, abs=2e-3), (
            f"{k}/{n}: bootstrap {boot.low:.4f} vs Wilson {wilson.low:.4f}，"
            f"差 {gap:.4f}，文档写 {expected_gap}"
        )


# ---------- 0.6 自动检查的边界 ----------


def test_section_0_6_records_the_coverage_limit() -> None:
    """必须写明"能自动检查的只有一部分"及其真实比例。"""
    text = _text()
    section = text.split("### 0.6 自动检查的边界")[1].split("### 0.7")[0]

    assert "83" in section, "未写 MUST/SHALL 总行数"
    # 按可验证性细分
    assert "1.2%" in section, "未写函数实现可验证率"
    assert "3.6%" in section, "未写字段可验证率"
    # 关键区分
    assert "有反引号" in section and "不等于" in section
    # 能力分组
    assert "conflict-resolution" in section
    assert "memory-store" in section


def test_section_0_6_records_the_three_layer_split() -> None:
    """必须写明三层（符号存在 / 行为符合 / 人工映射），不是一个比例。"""
    text = _text()
    section = text.split("### 0.6 自动检查的边界")[1].split("### 0.7")[0]

    assert "三层，不是两层" in section
    assert "符号存在" in section
    assert "行为符合" in section
    # 关键：行为符合是 0%
    assert "0/83 = 0%" in section or "0%" in section
    # 关键：不是 98.8%
    assert "100% 的" in section


def test_section_0_6_has_the_four_way_split() -> None:
    """四种分类的数字都要在。"""
    text = _text()
    section = text.split("### 0.6 自动检查的边界")[1].split("### 0.7")[0]

    assert "88.0%" in section   # 无反引号
    assert "1.2%" in section    # 函数名
    assert "4.8%" in section    # 字符串常量
    assert "6.0%" in section    # 非字面量


def test_section_0_6_records_scenario_gap() -> None:
    """**真正的缺口**：229 个 Scenario 只有 3 个有映射测试。"""
    text = _text()
    section = text.split("### 0.6 自动检查的边界")[1].split("### 0.7")[0]

    assert "229" in section
    assert "Scenario" in section
    assert "1.3%" in section
    # 修复成本更低
    assert "Test:" in section or "引用的测试名" in section


def test_scenario_count_is_real() -> None:
    """229 这个数必须能从 spec 复算。"""
    import re

    total = 0
    for path in (ROOT / "openspec" / "specs").rglob("spec.md"):
        total += len(
            re.findall(r"^#### Scenario:", path.read_text(encoding="utf-8"), re.M)
        )
    assert total == 229, f"Scenario 数变成 {total}"


# ---------- 0.6 抽样与 Test: 列的边界 ----------


def test_spec_has_zero_test_references() -> None:
    """spec 里必须有 **0** 条测试引用——这是"映射表"这一节的前提。

    若将来有人加了 `Test: xxx` 行，这个数字会变，本节的所有推论都要重算。
    """
    import re

    total = 0
    for path in (ROOT / "openspec" / "specs").rglob("spec.md"):
        text = path.read_text(encoding="utf-8")
        total += len(re.findall(r"^\s*(?:\*\*)?Test(?:\*\*)?:", text, re.M))
        total += len(re.findall(r"tests/test_[a-z_]+\.py", text))
    assert total == 0, f"spec 里出现了 {total} 条测试引用，§0.6 的结论需要重算"


def test_section_0_6_records_the_sample_of_ten() -> None:
    """必须记录"抽了 10 个 scenario"以及三种判定各自的条数。"""
    text = _text()
    section = text.split("### 0.6 自动检查的边界")[1].split("### 0.7")[0]

    assert "抽 10 个" in section
    # 三种判定
    assert "THEN 每段都有断言" in section
    assert "只覆盖部分" in section
    assert "没有 / 测的不是这个" in section
    # 分布是 5 / 4 / 1，不是 4 / 4 / 2
    assert "| **5** |" in section
    assert "| **4** |" in section
    assert "| **1** |" in section


def test_section_0_6_says_the_sample_refutes_the_a_or_b_choice() -> None:
    """抽样必须明确写出"不是 A 也不是 B，是第三种"。"""
    text = _text()
    section = text.split("### 0.6 自动检查的边界")[1].split("### 0.7")[0]

    assert "推翻了 A/B 二选一" in section
    assert "第三种" in section


def test_section_0_6_records_the_partial_coverage_case() -> None:
    """必须举出"引用全绿但只覆盖一段"的具体例子（缓存损坏）。"""
    text = _text()
    section = text.split("### 0.6 自动检查的边界")[1].split("### 0.7")[0]

    assert "test_corrupt_row_is_treated_as_miss" in section
    assert "重新请求" in section
    assert "记录警告" in section
    # 结论句
    assert "引用列能保证" in section
    assert "不等于" in section and "229 条行为都有验证" in section


def test_section_0_6_records_that_test_structure_is_problem_driven() -> None:
    """"问题驱动 vs spec 驱动"这个区分必须在，否则读者会以为只是补一列。"""
    text = _text()
    section = text.split("### 0.6 自动检查的边界")[1].split("### 0.7")[0]

    assert "问题驱动" in section
    assert "spec 驱动" in section
    assert "组织方式的改变" in section
    # 测试比 scenario 多
    assert "1322" in section


def test_section_0_6_records_why_7_is_counted_as_covered() -> None:
    """#7 是"间接锁定"而非直接断言，必须写明，否则会被误读成直接断言。"""
    text = _text()
    section = text.split("### 0.6 自动检查的边界")[1].split("### 0.7")[0]

    assert "间接锁定" in section
    assert "26/30" in section


def test_section_0_6_records_the_unmeasurable_case() -> None:
    """#9 是"全库找不到对应测试"的具体缺口，必须点名。"""
    text = _text()
    section = text.split("### 0.6 自动检查的边界")[1].split("### 0.7")[0]

    assert "valid_from < recorded_at" in section
    assert "test_write.py:276" in section


def test_section_0_6_records_why_judging_is_not_unique() -> None:
    """#8 两种口径都能自圆其说——这说明判据不唯一，是引用列的第二难题。"""
    text = _text()
    section = text.split("### 0.6 自动检查的边界")[1].split("### 0.7")[0]

    assert "判据不唯一" in section
    assert "两种口径" in section


def test_section_0_6_records_that_the_audit_itself_was_wrong() -> None:
    """**必须记录这次审计本身算错过一次。**

    第一版写的是"13 条中 5 条，38%"，错因是脚本只读了部分 spec 文件。
    记录它，是为了让后来者先验证提取脚本，再相信输出。
    """
    text = _text()
    section = text.split("### 0.6 自动检查的边界")[1].split("### 0.7")[0]

    assert "审计本身出过一次错" in section
    assert "13 条" in section     # 错误的旧数字
    assert "38%" in section       # 错误的旧比例
    assert "只读了部分" in section  # 错因
    assert "装置可能出错" in section


def test_section_0_6_has_a_non_empty_mapping_table() -> None:
    """映射表必须非空，且带"可自动验证"一列。"""
    text = _text()
    section = text.split("### 0.6 自动检查的边界")[1].split("### 0.7")[0]

    assert "配对 bootstrap 区间" in section
    assert "path_returns" in section
    assert "substring_exact_match" in section
    # 新增的可验证性列
    assert "可自动验证" in section
    assert "❌ 无符号" in section
    assert "✅ **有函数名**" in section


def test_section_0_6_warns_about_false_assurance() -> None:
    """必须写明"1300+ 测试"会给人虚假安全感。"""
    text = _text()
    section = text.split("### 0.6 自动检查的边界")[1].split("### 0.7")[0]

    assert "虚假的安全感" in section
    assert "没测到" in section


def test_must_coverage_numbers_are_real() -> None:
    """83 与"1 条函数名"必须能从 spec 复算。"""
    import re

    specs = ROOT / "openspec" / "specs"
    total = 0
    function_lines = 0

    fields = {
        "valid_from", "valid_to", "recorded_at", "value", "condition",
        "subject", "relation", "owner", "scope",
    }
    constants = {"no-memory", "full-context", "naive-rag"}
    # 参数名不是函数
    params = {"gold_item_id"}

    for path in specs.rglob("spec.md"):
        for line in path.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if "MUST" not in stripped and "SHALL" not in stripped:
                continue
            total += 1
            syms = re.findall(r"`([^`]+)`", stripped)
            real_functions = [
                s
                for s in syms
                if re.fullmatch(r"[a-z_][a-z0-9_]*", s)
                and s not in fields
                and s not in constants
                and s not in params
            ]
            if real_functions:
                function_lines += 1

    assert total == 83, f"含 MUST/SHALL 的行变成 {total}"
    assert function_lines == 1, (
        f"能验证函数实现的行变成 {function_lines}——文档里的 1.2% 要更新"
    )
