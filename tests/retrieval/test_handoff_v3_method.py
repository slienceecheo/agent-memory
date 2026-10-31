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


def _section_until_next_heading(number: str) -> str:
    """截到下一个 `## ` 或 `### ` 标题为止。

    §0.7 是 §0 的最后一节，它后面接的是正文（不是小标题），
    所以不能用 `### x` 作锚点——那样会把后面整篇都算进来。
    """
    import re

    text = _text()
    start = text.find(f"### {number} ")
    assert start != -1, f"找不到 §{number}"
    rest = text[start + len(f"### {number} ") :]
    match = re.search(r"^#{2,3} ", rest, re.M)
    return rest[: match.start()] if match else rest


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


# ---------- 0.7 计数关系 ----------


def test_section_0_7_separates_defects_from_markers() -> None:
    """必须区分"23 条缺陷"与"33 个标记"。"""
    section = _section_until_next_heading("0.7")

    assert "23 条缺陷" in section
    assert "34 个" in section
    assert "36 条收集" in section


def test_section_0_7_explains_both_gaps() -> None:
    """两个差值都要解释：23→33 与 33→35。"""
    section = _section_until_next_heading("0.7")

    # 23 -> 33：多标记 + 已修复的用正向断言
    assert "+16" in section
    assert "正向断言" in section
    # 33 -> 35：parametrize
    assert "+2" in section
    assert "parametrize" in section


def test_section_0_7_lists_defects_with_multiple_markers() -> None:
    """带多个标记的缺陷必须逐条列出，否则 +10 无法核对。"""
    section = _section_until_next_heading("0.7")

    for defect in (5, 10, 11, 15, 16, 18, 20, 21, 22, 23):
        assert f"| {defect} |" in section, f"缺陷 {defect} 未在表中"


def test_counts_match_reality() -> None:
    """三个数字必须与清单和标记一致。"""
    import ast
    import sys

    sys.path.insert(0, str(ROOT))
    from tests.retrieval.test_locked_defect_manifest import DEFECT_TESTS, REPAIRED

    defects = len(set(DEFECT_TESTS) | set(REPAIRED))
    assert defects == 23, f"缺陷编号数变成 {defects}"

    markers = 0
    for path in (ROOT / "tests").rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                for dec in node.decorator_list:
                    if "locked_defect" in ast.unparse(dec):
                        markers += 1
    assert markers == 34, f"标记数变成 {markers}"


def test_locked_defect_collected_count_matches_the_document() -> None:
    """`-m locked_defect` 实际收集到的条数必须等于文档写的 35。

    **为什么单独测**：参数化展开后的条数无法从 AST 直接算出
    （`parametrize` 的 args 可能是变量），只能问 pytest 自己。
    而文档写"35 条收集"，若实际是 34 或 36，没人会发现。
    """
    import subprocess
    import sys

    proc = subprocess.run(
        [
            sys.executable, "-m", "pytest",
            "-m", "locked_defect", "--collect-only", "-q",
            "-p", "no:cacheprovider",
            # 必须显式限制目录：否则 `-m` 会连 deselected 一起列出，
            # 汇总行是全量条数而不是被选中的条数。
            "tests",
        ],
        cwd=ROOT, capture_output=True, text=True,
        encoding="utf-8", errors="replace",
    )
    # 实际跑一遍拿"passed"数比解析 collect-only 更可靠：
    # collect-only 的汇总行在含 deselected 时是 `N/M tests collected`。
    proc = subprocess.run(
        [
            sys.executable, "-m", "pytest",
            "-m", "locked_defect", "-q",
            "-p", "no:cacheprovider",
            "tests",
        ],
        cwd=ROOT, capture_output=True, text=True,
        encoding="utf-8", errors="replace",
    )
    import re

    match = re.search(r"(\d+)\s+passed", proc.stdout)
    assert match, f"无法从输出解析通过条数：{proc.stdout[-400:]}"
    collected = int(match.group(1))

    # 必须真去读文档里的数字，否则这条测试只验证了 pytest 自己。
    # 文档里有两处陈述收集条数，格式不同：
    #   `locked_defect -> 35 条收集（33 个标记...）`
    #   `## 33 个标记不许删（收集为 35 条）`
    text = _text()
    stated = re.search(r"-> (\d+) 条收集", text) or re.search(
        r"收集为 (\d+) 条", text
    )
    assert stated, "文档里找不到 locked_defect 的收集条数"
    documented = int(stated.group(1))

    assert collected == documented, (
        f"`-m locked_defect` 实际跑了 {collected} 条，文档写 {documented} 条"
    )


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
    """必须记录"抽了 10 个 scenario"以及五类覆盖各自的条数。"""
    text = _text()
    section = text.split("### 0.6 自动检查的边界")[1].split("### 0.7")[0]

    assert "抽 10 个" in section
    # 五类，不是三类
    assert "直接覆盖" in section
    assert "间接锁定" in section
    assert "parametrize 分支" in section
    assert "部分覆盖" in section
    assert "无覆盖" in section
    # 分布 4 / 1 / 1 / 3 / 1
    assert "| **4** |" in section
    assert "| **3** |" in section
    assert "| **1** |" in section


def test_section_0_6_separates_indirect_lock_from_partial() -> None:
    """间接锁定与部分覆盖的处置相反，必须写明"补注释"vs"补断言"。"""
    text = _text()
    section = text.split("### 0.6 自动检查的边界")[1].split("### 0.7")[0]

    assert "补注释" in section
    assert "补断言" in section
    # 理由：两者处置相反
    assert "处置相反" in section


def test_section_0_6_records_the_correction_of_scenario_8() -> None:
    """#8 原先误判为 ⚠️，必须记录改判和原因。"""
    text = _text()
    section = text.split("### 0.6 自动检查的边界")[1].split("### 0.7")[0]

    assert "#8 改判说明" in section
    assert "原先误判" in section
    assert "覆盖不需要长成那个样子" in section


def test_section_0_6_records_the_spec_example_that_fails() -> None:
    """spec 自己举的 "应酬 / client dinner" 例子实测跑不通，必须记录。"""
    text = _text()
    section = text.split("### 0.6 自动检查的边界")[1].split("### 0.7")[0]

    assert "spec 自己举的例子" in section
    assert "client dinner" in section
    assert "client_dinner" in section
    assert "唯一不成立的形式" in section


def test_section_0_6_warns_that_fixing_the_example_lowers_the_standard() -> None:
    """修 spec 例子会让场景从失败变通过，而实现没变——必须写明。"""
    text = _text()
    section = text.split("### 0.6 自动检查的边界")[1].split("### 0.7")[0]

    assert "因为标准降低了" in section
    # 三个先例
    assert "协议 §1.2" in section
    assert "缺陷 20" in section
    # 处置顺序
    assert "同时登记" in section
    assert "缺陷 23" in section


def test_section_0_6_records_defect_23_substring_false_positives() -> None:
    """缺陷 23 的三对误命中必须点名，且给出假相似度的实测值。"""
    text = _text()
    section = text.split("### 0.6 自动检查的边界")[1].split("### 0.7")[0]

    assert "缺陷 23" in section
    assert "`day`" in section and "`holiday`" in section
    assert "开发环境" in section and "功能开发" in section
    # 假相似度
    assert "condition_match(\"开发环境\", \"写代码\")" in section
    assert "0.500" in section
    # 生产路径，不是死代码
    assert "rerank.py:111" in section


def test_section_0_6_records_the_three_fix_options_and_their_costs() -> None:
    """甲/乙/丙三条修法各有代价，必须列出，否则会以为这是简单 bugfix。"""
    text = _text()
    section = text.split("### 0.6 自动检查的边界")[1].split("### 0.7")[0]

    assert "词边界" in section
    assert "最长匹配" in section
    assert "精确匹配" in section
    # 丙的实测代价：3 个值退化
    assert "工作日白天" in section
    assert "生产环境" in section
    # 更正：客户应酬 在词表里——断言整句，因为"不成立"在本节出现两次
    assert "`客户应酬` **在** `_ALIASES` 里" in section
    assert '"精确匹配会打断 `客户应酬`"不成立' in section


def test_section_0_6_records_that_references_flip_with_implementation() -> None:
    """引用列记录的映射会随实现翻转——它只能回答"谁负责"。"""
    text = _text()
    section = text.split("### 0.6 自动检查的边界")[1].split("### 0.7")[0]

    assert "会随实现翻转" in section
    assert "谁负责" in section
    assert "不能回答" in section


# ---------- 上面这些数字必须可复算 ----------


def test_defect23_false_positives_really_occur() -> None:
    """三对子串误命中产生 0.5 的假相似度。"""
    import sys

    sys.path.insert(0, str(ROOT))
    from memory.retrieval.condition import parse_condition

    assert parse_condition("holiday").slots == frozenset(
        {"time:day", "time:holiday"}
    )
    assert parse_condition("开发环境").slots == frozenset(
        {"activity:coding", "env:development"}
    )
    assert parse_condition("功能开发").slots == frozenset(
        {"activity:coding", "activity:feature"}
    )


def test_defect23_produces_a_false_positive_similarity() -> None:
    """语义无关的两个条件，因为共享误命中槽位而得到 0.5。"""
    import sys

    sys.path.insert(0, str(ROOT))
    from memory.retrieval.condition import condition_match

    assert condition_match("开发环境", "写代码") == pytest.approx(0.5)
    assert condition_match("功能开发", "写代码") == pytest.approx(0.5)


def test_exact_matching_would_break_these_three_values() -> None:
    """精确匹配（丙）会让恰好 3 个数据集值退化为 raw。"""
    import sys

    sys.path.insert(0, str(ROOT))
    from memory.retrieval.condition import _ALIASES, parse_condition

    folded = {a.casefold() for a in _ALIASES}
    would_break = [
        v
        for v in ("工作日白天", "本地开发", "生产环境")
        if v.casefold() not in folded and parse_condition(v).structured
    ]

    assert len(would_break) == 3, f"实际会被打断：{would_break}"


def test_client_dinner_is_not_in_the_alias_table() -> None:
    """`client dinner`（空格）不在词表里——这是 spec 例子失败的原因。"""
    import sys

    sys.path.insert(0, str(ROOT))
    from memory.retrieval.condition import _ALIASES

    assert "client_dinner" in _ALIASES
    assert "client dinner" not in _ALIASES


def test_client_yingshou_is_an_exact_key() -> None:
    """更正：`客户应酬` 是精确键，精确匹配不会打断它。"""
    import sys

    sys.path.insert(0, str(ROOT))
    from memory.retrieval.condition import _ALIASES

    assert "客户应酬" in _ALIASES
    assert "应酬" in _ALIASES


def test_condition_match_is_on_the_production_path() -> None:
    """缺陷 23 不是死代码：`rerank.py` 与 `run_retrieval.py` 都调用它。"""
    rerank = (ROOT / "src" / "memory" / "retrieval" / "rerank.py").read_text(
        encoding="utf-8"
    )
    runner = (ROOT / "evals" / "run_retrieval.py").read_text(encoding="utf-8")

    assert "condition_match" in rerank
    assert "condition_match" in runner


def test_section_0_6_records_the_subset_assertion_blind_spot() -> None:
    """`expected_slot in slots` 是子集断言，看不见多出来的槽位。"""
    text = _text()
    section = text.split("### 0.6 自动检查的边界")[1].split("### 0.7")[0]

    assert "子集断言" in section
    assert "holiday" in section
    assert "3 对" in section


def test_section_0_6_defines_test_reference_semantics() -> None:
    """`Test:` 的语义是"由谁负责"，不是"已验收"。"""
    text = _text()
    section = text.split("### 0.6 自动检查的边界")[1].split("### 0.7")[0]

    assert "由哪个测试函数负责" in section
    assert "已被验证" in section
    # 这是第三个盲区
    assert "第三个盲区" in section


# ---------- 上面这些数字必须可复算 ----------


def test_spec_example_client_dinner_really_does_not_match() -> None:
    """`应酬 / client dinner` 匹配 0.0，而 `应酬 / client_dinner` 匹配 1.0。"""
    import sys

    sys.path.insert(0, str(ROOT))
    from memory.retrieval.condition import condition_match

    assert condition_match("应酬", "client dinner") == pytest.approx(0.0)
    assert condition_match("应酬", "client_dinner") == pytest.approx(1.0)


def test_holiday_and_chinese_equivalent_are_not_equal() -> None:
    """`holiday` 多给一个 `time:day`，与 `节假日` 不相等。"""
    import sys

    sys.path.insert(0, str(ROOT))
    from memory.retrieval.condition import parse_condition

    en = parse_condition("holiday").slots
    zh = parse_condition("节假日").slots

    assert en != zh
    assert en == frozenset({"time:day", "time:holiday"})
    assert zh == frozenset({"time:holiday"})


def test_there_are_exactly_three_substring_collisions() -> None:
    """`_ALIASES` 里"短别名是长别名子串且槽位不同"的组合恰好 3 对。"""
    import sys

    sys.path.insert(0, str(ROOT))
    from memory.retrieval.condition import _ALIASES

    collisions = [
        (short, long)
        for short in _ALIASES
        for long in _ALIASES
        if short != long
        and short.casefold() in long.casefold()
        and _ALIASES[short] != _ALIASES[long]
    ]

    assert len(collisions) == 3, f"子串误命中变成 {len(collisions)} 对：{collisions}"


def test_indirect_lock_really_fails_when_exclusion_is_removed() -> None:
    """#7 说"删掉排除逻辑，均值会变"——这个说法必须实测。

    若这个差不存在，"间接锁定"这个类型就是编出来的。
    **这里不用 skip**：文件缺失时必须红，否则这条测试会在无人察觉时变成空转。
    """
    import json

    data = ROOT / "data" / "conflict-set" / "independent.jsonl"
    assert data.exists(), f"样本文件丢失：{data}"

    rows = [
        json.loads(line)
        for line in data.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    with_gold = [r for r in rows if r.get("gold")]
    without_gold = [r for r in rows if not r.get("gold")]

    assert len(with_gold) == 26
    assert len(without_gold) == 4

    excluded_mean = 26 / 26   # 排除无 gold
    included_mean = 26 / 30   # 不排除，4 条以 False 进分母

    assert excluded_mean == pytest.approx(1.0)
    assert included_mean == pytest.approx(0.867, abs=1e-3)
    assert included_mean < 1.0, "若仍等于 1.0，这条间接锁定就是假的"


def test_parametrize_uses_subset_not_equality() -> None:
    """`test_known_expressions_map_to_slots` 断言的是 `in`，不是相等。

    这个断言本身是"记录现状"：只要它还写 `in`，多给槽位就不会红。
    """
    source = (ROOT / "tests" / "retrieval" / "test_condition.py").read_text(
        encoding="utf-8"
    )

    assert "assert expected_slot in parsed.slots" in source
    assert "assert parsed.slots == {" not in source


def test_section_0_6_separates_false_hits_from_multi_hits() -> None:
    """必须区分"误命中"（区间重叠）与"多命中"（区间不交）。

    这两类性质不同：误命中一定是错的，多命中可能都对。
    不分开记，选方案时就不知道在选什么。
    """
    text = _text()
    section = text.split("### 0.6 自动检查的边界")[1].split("### 0.7")[0]

    assert "误命中" in section
    assert "多命中" in section
    # 判据是区间重叠
    assert "重叠" in section
    # 多命中可能是对的
    assert "可能都对" in section


def test_section_0_6_records_the_three_value_groups() -> None:
    """41 个条件值必须分成三组：26 精确键 / 3 靠子串 / 12 本来就 raw。"""
    text = _text()
    section = text.split("### 0.6 自动检查的边界")[1].split("### 0.7")[0]

    assert "**A** 精确键" in section
    assert "**B** 靠子串命中" in section
    assert "**C** 本来就是 raw" in section
    assert "**26**" in section
    assert "**3**" in section
    assert "**12**" in section
    # 组 C 不该算进"被打断"
    assert "不该算进" in section


def test_section_0_6_says_exact_matching_kills_correct_behaviour() -> None:
    """丙会让 3 个**语义正确**的值退化——必须写明，否则读者以为那 3 个本来错。"""
    text = _text()
    section = text.split("### 0.6 自动检查的边界")[1].split("### 0.7")[0]

    assert "全是语义正确的" in section
    assert "杀掉" in section
    # 乙保留多命中
    assert "乙 看起来最好" in section
    # 乙需要区间占位
    assert "区间占位" in section


def _section_by_title(prefix: str) -> str:
    """按小节标题前缀取内容，截到下一个同级或更高级标题。"""
    import re

    text = _text()
    start = text.find(prefix)
    assert start != -1, f"找不到小节：{prefix}"
    rest = text[start:]
    match = re.search(r"^#{2,3} ", rest[len(prefix) :], re.M)
    return rest[: len(prefix) + match.start()] if match else rest


def test_section_0_7_distinguishes_plan_check_from_locked_defect() -> None:
    """`plan_check` 与 `locked_defect` 必须分开记，并写出实测依据。

    修缺陷 23 时：locked_defect 会红（该翻面），plan_check 不会（方案论证）。
    若不写清，修完会看到"7 红 3 绿"然后困惑。
    """
    # plan_check 的说明在 §0.7 的"带多个标记"表下方，属于 0.7 正文
    section = _section_until_next_heading("0.7")

    assert "plan_check" in section
    # 实测数字
    assert "3 failed" in section
    assert "3 passed" in section
    # 标记定义
    assert "不调用产品的匹配/排序逻辑" in section
    # 为什么必须分开
    assert "困惑" in section


def test_section_0_7_records_the_blocked_by_field() -> None:
    """`blocked_by` 字段必须写明三档取值与条数。"""
    section = _section_by_title("### 为什么还没修：`blocked_by` 字段")

    assert "blocked_by" in section
    assert "dataset-frozen" in section
    assert "needs-design" in section
    # 条数
    assert "**12**" in section
    assert "**5**" in section
    assert "**1**" in section
    # 可查询的过滤条件
    assert "可查询" in section
    # 不改标记语义
    assert "不改变" in section and "语义" in section


def test_section_0_7_explains_why_not_removing_unfixable_defects() -> None:
    """必须写明"为什么不用'能不能修'做分类"。"""
    section = _section_by_title("### 为什么还没修：`blocked_by` 字段")

    assert "从清单消失" in section
    assert "还剩多少没修" in section


def test_section_0_7_records_the_src_sensitivity_audit() -> None:
    """必须记录"改什么会红"的实测分类，含 rerank 修复后的 2 条。"""
    section = _section_until_next_heading("0.8")

    assert "改 `condition.py` 的匹配逻辑" in section
    assert "| **6** | 缺陷 23 的真锁 |" in section
    assert "改 `rerank.py` 的权重" in section
    # 修复后是 2 条，不再是 0
    assert "**2**（见下，已从 0 修复）" in section
    # 结论：不是"没有一条对 src 敏感"
    assert "这个说法是错的" in section


def test_section_0_8_records_the_copied_constant_problem_as_fixed() -> None:
    """必须记录"抄常量"这个测试缺陷**已修**，以及修前修后的实测对照。"""
    section = _section_by_title("### 已修：`rerank.py` 权重改动原本 0 条红")

    assert "硬编码" in section
    assert "w = 0.25" in section
    # 修前/修后对照
    assert "**仍绿**" in section
    assert "**2 条红**" in section
    assert "测试抄了产品常量" in section


def test_section_0_8_records_the_fix_actions() -> None:
    """三处修复动作必须写明，且说明为什么不需要开变更。"""
    section = _section_by_title("### 修复动作（test-only，不需要 OpenSpec 变更）")

    assert "test_defect18_authority.py" in section
    assert "test_defects_20_21.py" in section
    assert "test_rerank.py" in section
    # 为什么不需要变更
    assert "改测试断言不改任何产品行为" in section
    # 实测验证
    assert "0 条红（36 passed）" in section
    assert "2 条红" in section


def test_section_0_8_records_that_the_arithmetic_was_wrong() -> None:
    """必须记录这节的算术错过一次（0.1016 实为 0.1066），以及为什么会错。"""
    section = _section_by_title("### 这一节的算术出过一次错")

    assert "0.1016" in section
    assert "0.1066" in section
    # 错误来源
    assert "位置搞反" in section
    # 与抄常量同性质
    assert "错误性质与 `w = 0.25` 抄常量相同" in section
    # 两条防线
    assert "从本文档里用正则抓出这些数字" in section
    assert "只验算不读文档" in section


def test_section_0_8_states_the_critical_point_premises() -> None:
    """0.170849 有两个前提，文档必须写明——它不是缺陷 19 的普适临界点。

    **为什么这条必须有**：`spec` 从未规定 `base == condition`，
    而调这两个的分配是 v3 改权重时最自然的动作。
    不写前提，v3 一改就会有人以为"0.170849 失效了 = 缺陷没有了"。
    """
    section = _section_by_title("### 断言类型的选择")

    assert "0.170849 有两个前提" in section
    # 前提 (b) 是那个没有产品依据的——断言整行，避免"等分"在别处也出现
    assert "**等分**剩余权重" in section
    assert "| (b) `base` 与 `condition` **等分**剩余权重 | 各 50% |" in section
    assert "没有" in section and "spec" in section
    # 通式
    assert "(1 − w_status) × k / (1 + k)" in section
    # 前提变动表
    assert "0.182239" in section
    assert "0.188623" in section
    # 判据不受影响
    assert "缺陷 19 的判据不受影响" in section


def test_section_0_8_uses_a_bound_not_a_point() -> None:
    """这是本轮最后一条判据的应用：阈值必须是界，不是点估计。

    0.170849 通过了"引用符号""可复算""与文档一致"三道检查，
    但它只能回答"当前分配的临界点"，不能回答"该降到多少"——
    后者需要所有分配下的下确界 0.061927。
    """
    section = _section_by_title('### 但 `0.170849` 是个点')

    # 两个端点——断言整行，因为这两个数字在别处也出现
    assert "| **0.0** | **0.250000** | 全给 condition" in section
    assert "| **1.0** | **0.061927** | 全给 base" in section
    assert "下确界" in section
    assert "上确界" in section
    # 闭式
    assert "(1 − w_status) × d_base / (1 + d_base)" in section
    # 倍数
    assert "2.76" in section
    # 单调性——极值在端点的依据
    assert "单调递减" in section


def test_section_0_8_records_the_015_counterexample() -> None:
    """必须写"降到 0.15 在 base_share=1 时仍不安全"，那是点估计的具体危害。"""
    section = _section_by_title('### 但 `0.170849` 是个点')

    # 断言整行，避免命中别处的 0.15
    assert "base_share=1.0  crit=0.061927  **不安全（缺陷仍在）**" in section
    assert "0.15 > 0.062" in section or "0.15 > 0.0619" in section


def test_section_0_9_threshold_is_at_most_the_infimum() -> None:
    """新判据：结论里的阈值必须是下确界。

    `0.170849` 是本轮唯一一个"三道检查全过但仍然错"的数——
    不是数值错，是用途错。这条区分必须写下来。
    """
    section = _section_by_title("### 由此补一条判据")

    assert "下确界" in section
    assert "所有可能情形" in section
    # 项目里已有的同类先例
    assert "axis_baseline" in section

    # "不是数值错，是用途错"这段在下一节
    second = _section_by_title("### 这一层不是")
    assert "不是数值错" in second and "是用途错" in second
    assert "2.76" in second


def test_section_0_8_arithmetic_numbers_are_recomputable() -> None:
    """文档里出现的每个算术数字都必须能从权重算出来。

    **这条是为一次真实错误加的**：讨论"数值断言要防什么"时，
    我把 base 0.26 / condition 0.24 的差值口算成 0.1016，
    实际是 0.1066（把 0.26×0.09 算成了 0.24×0.09）。

    错误性质与 `w = 0.25` 抄常量相同：用一个不需要更新的来源（记忆）
    代替一个会变的来源（计算）。区别只是测试的错误会被 CI 抓，对话里的不会。
    """
    d_base = 1.0 - 0.91
    d_cond = 1.0 - 0.50

    # 基准：uniform 各 0.25
    base_adv = 0.25 * d_base + 0.25 * d_cond
    assert base_adv == pytest.approx(0.1475, abs=1e-4)
    assert 0.25 - base_adv == pytest.approx(0.1025, abs=1e-4)

    # 变异 A：base 0.24 / cond 0.26（文档 §0.8 写的 0.0984）
    adv_a = 0.24 * d_base + 0.26 * d_cond
    assert adv_a == pytest.approx(0.1516, abs=1e-4)
    assert 0.25 - adv_a == pytest.approx(0.0984, abs=1e-4)

    # 变异 B：base 0.26 / cond 0.24（文档 §0.8 写的 0.1066，不是 0.1016）
    adv_b = 0.26 * d_base + 0.24 * d_cond
    assert adv_b == pytest.approx(0.1434, abs=1e-4)
    assert 0.25 - adv_b == pytest.approx(0.1066, abs=1e-4)

    # 两种变异下结构断言都仍成立——所以它们不是"缺陷被修"的信号
    assert adv_a < 0.25
    assert adv_b < 0.25

    # 临界点：a = (0.75 - a)/2 * (d_base + d_cond) => a = 0.4425 / 2.59
    #
    # **这两个常量也是抄来的，必须说清**：
    #   0.25 = status 权重（可从 PREREGISTERED_WEIGHTS 读，但本条只验文档里那个数字）
    #   / 2  = base 与 condition 等分剩余权重
    # 而后者**没有产品依据**——spec 从未规定 base == condition。
    # 所以下面算的是"status=0.25 且等分时"的临界点，不是缺陷 19 的普适临界点。
    # 通式与前提表写在 HANDOFF §0.8；前提一变，0.170849 就要重算。
    crit = 0.4425 / 2.59
    assert crit == pytest.approx(0.170849, abs=1e-5)

    # 通用式（不假设等分），验证文档里的通式：crit = (1-w_status)*k/(1+k)
    def crit_general(w_status: float, base_share: float) -> float:
        k = base_share * d_base + (1.0 - base_share) * d_cond
        return (1.0 - w_status) * k / (1.0 + k)

    assert crit_general(0.25, 0.5) == pytest.approx(crit, abs=1e-9)

    # 文档里列的前提变动表，逐项复算
    assert crit_general(0.20, 0.5) == pytest.approx(0.182239, abs=1e-5)
    assert crit_general(0.30, 0.5) == pytest.approx(0.159459, abs=1e-5)
    assert crit_general(0.35, 0.5) == pytest.approx(0.148069, abs=1e-5)
    assert crit_general(0.25, 0.6) == pytest.approx(0.151914, abs=1e-5)
    assert crit_general(0.25, 0.4) == pytest.approx(0.188623, abs=1e-5)

    # 端点：下确界与上确界
    #
    # **这是"点估计 vs 界"的修正**：0.170849 只是 base_share=0.5 的值，
    # 而"authority 该降到多少"要的是所有分配下的下确界。
    infimum = crit_general(0.25, 1.0)
    supremum = crit_general(0.25, 0.0)
    assert infimum == pytest.approx(0.061927, abs=1e-5)
    assert supremum == pytest.approx(0.250000, abs=1e-5)

    # 单调性保证极值在端点，不必扫描内部
    shares = [i / 50 for i in range(51)]
    crits = [crit_general(0.25, s) for s in shares]
    assert all(crits[i] >= crits[i + 1] for i in range(len(crits) - 1)), (
        "crit 不再对 base_share 单调递减，端点极值的论证失效"
    )

    # 文档建议的 0.05 必须低于**下确界**，不是低于某个临界点
    assert infimum > 0.05, "0.05 不再对全部分配安全"
    # 反例：0.15 在某分配下不安全——这正是点估计的危险
    assert infimum <= 0.15, "若 0.15 也安全，文档里那个反例就不成立"
    assert crit_general(0.25, 0.5) > 0.15, "0.15 在等分时是安全的（所以它有迷惑性）"

    def adv_at(a: float) -> float:
        rest = (1.0 - a - 0.25) / 2
        return rest * d_base + rest * d_cond

    assert crit > adv_at(crit) - 1e-9        # 临界点成立
    just_below = 0.17
    assert just_below < adv_at(just_below)   # 再降就不成立

    # 最后：文档里写的数字必须与上面算出的一致
    import re

    section = _section_by_title("### 但数值断言也有反方向的代价")

    documented = re.search(r"diff\s*=\s*0\.25\s*−\s*0\.1434\s*=\s*([0-9.]+)", section)
    assert documented, "文档里找不到 0.1434 那组算式的差值"
    assert float(documented.group(1)) == pytest.approx(0.1066, abs=1e-4), (
        f"文档写 {documented.group(1)}，实际应为 0.1066"
    )

    adv_doc = re.search(
        r"advantage\s*=\s*0\.26\s*×\s*0\.09\s*\+\s*0\.24\s*×\s*0\.50\s*="
        r"\s*0\.0234\s*\+\s*0\.1200\s*=\s*([0-9.]+)",
        section,
    )
    assert adv_doc, "文档里找不到完整的 advantage 算式"
    assert float(adv_doc.group(1)) == pytest.approx(0.1434, abs=1e-4)


def test_section_0_8_records_assertion_types_not_two_layers() -> None:
    """必须区分结构断言与数值断言，不能说成"引用符号不够"。"""
    section = _section_by_title("### 断言类型的选择")

    assert "结构断言" in section
    assert "数值断言" in section
    # 失效条件相反 —— 该节的核心判据
    assert "失效条件相反" in section
    # 临界点与它的两个前提
    assert "0.1709" in section
    assert "0.170849 有两个前提" in section


def test_section_0_8_records_which_assertion_fails_first() -> None:
    """结构断言晚红、且"晚"有代价——这段在「由此补一条判据」一节内。"""
    section = _section_by_title("### 由此补一条判据")

    assert "数值断言早红" in section
    assert "缺陷被削弱但没被修" in section


def test_section_0_8_records_the_numerical_assertion_cost() -> None:
    """数值断言也有反方向代价：无关权重调整会误报。"""
    section = _section_by_title("### 但数值断言也有反方向的代价")

    assert "误报" in section
    assert "缺陷 19 一点没变" in section
    # 两者都留
    assert "两者都留" in section


def test_section_0_8_records_the_01025_scope() -> None:
    """0.1025 是 uniform 权重下的条件值，不是缺陷常量。"""
    section = _section_by_title("### 报告里的 0.1025 是条件值")

    assert "c4-retrieval.md" in section
    assert "v2-sample-validation.md" in section
    assert "条件值" in section
    # 为什么不改报告
    assert "已冻结" in section


def test_section_0_7_has_the_four_step_checklist() -> None:
    """四步检查清单必须写出来——原则换不成动作。"""
    section = _section_by_title("### 这三步检查")

    assert "可复用的清单" in section
    assert "改 `src/` / 改 `evals/` / 改数据" in section
    assert "什么情况下它会变红" in section
    assert "不该叫" in section
    # 明确不写原则
    assert "不要写成原则" in section


def test_rerank_defect_tests_read_the_product_weights() -> None:
    """缺陷 19/21 的测试必须**读取**产品权重，不能抄 `w = 0.25`。

    **这条记录了一次已修的测试缺陷**：

    原先这两条测试各写 `w = 0.25`，于是"改 rerank 权重"不会让它们变红——
    实测把 `uniform` 改成 base 0.24 / condition 0.26 时，36 条 `locked_defect`
    一条都没红，而缺陷 19/21 恰恰是唯一与权重相关的锁。

    两个测试改了之后：
    - 引用 `PREREGISTERED_WEIGHTS["uniform"]` 的**符号**，
    - 且断言的量（0.1475 / 0.25 / 0.1025 / 相等）确实随权重变化。

    **若这条变红**：说明有人又把它改回了抄常量——那会让缺陷 19/21 重新失去保护。
    """
    q4 = (ROOT / "tests" / "retrieval" / "test_defect18_authority.py").read_text(
        encoding="utf-8"
    )
    p21 = (ROOT / "tests" / "retrieval" / "test_defects_20_21.py").read_text(
        encoding="utf-8"
    )

    for name, src in (("缺陷 19", q4), ("缺陷 21", p21)):
        assert "PREREGISTERED_WEIGHTS" in src, (
            f"{name}的测试没有引用产品权重表——抄常量会让权重改动不触发它"
        )
        assert "    w = 0.25" not in src, (
            f"{name}的测试又把权重抄成了字面量"
        )

    # 而且必须是分别取字段，不是取一个数当四个用
    assert "w.authority" in q4, "缺陷 19 必须用 w.authority，不能拿单一 w 顶替"
    assert "w.base * d_base" in q4, "缺陷 19 的 base 项必须用 w.base"
    assert "w.condition" in p21, "缺陷 21 的加成必须用 w.condition"


def test_thread_three_of_the_six_evals_sensitive_tests_are_locked_defect() -> None:
    """改 `select_pool_distractors` 会让 6 条 `locked_defect` 变红。

    这是"锁数据×评测代码"那一类，不是纯数据锁。
    """
    names = {
        "test_adjacency_has_no_legal_target_on_dev",
        "test_dedup_has_no_legal_merge_target_after_pool_build",
        "test_pool_dedup_drops_distinct_values",
        "test_same_relation_mixes_subjects",
        "test_unrelated_mode_is_a_file_order_prefix",
        "test_non_dev_selection_is_all_from_dev",
    }
    from tests.retrieval.test_locked_defect_manifest import DEFECT_TESTS

    mapped = {n for names_ in DEFECT_TESTS.values() for n in names_}
    missing = names - mapped
    assert not missing, f"这些测试不在映射表里：{sorted(missing)}"


def test_product_code_matches_head() -> None:
    """变异脚本可能留下 CRLF 或其他字节差异。

    **为什么需要这条**：一整轮的论证都建立在"产品代码没动"上。若 `condition.py`
    被改了内容（哪怕只是行尾），"缺陷 23 仍然存在"这个断言就是假的。
    而 blob hash 相同说明内容确实没变——但没有这一步检查，
    `git status` 里的 M 会让"没动"变成一句无法验证的话。

    实测事故：变异脚本用 `write_text` 把三个产品文件写成 CRLF，
    内容与 HEAD 一致但字节不同，`git status` 显示 M，靠人工排查才还原。
    """
    import subprocess

    watch = [
        "src/memory/retrieval/condition.py",
        "src/memory/retrieval/rerank.py",
        "src/memory/retrieval/dedup.py",
        "src/memory/retrieval/fusion.py",
        "src/memory/retrieval/pool.py",
        "src/memory/store/models.py",
        "evals/run_retrieval.py",
    ]

    diffs = []
    for rel in watch:
        disk = subprocess.run(
            # `--no-filters` 必须加：否则 `hash-object` 会按 `.gitattributes`
            # 做 EOL 转换，CRLF 与 LF 算出同一个哈希，这条检查就形同虚设。
            ["git", "hash-object", "--no-filters", rel],
            cwd=ROOT, capture_output=True, text=True, encoding="utf-8",
        ).stdout.strip()
        head = subprocess.run(
            ["git", "rev-parse", f"HEAD:{rel}"],
            cwd=ROOT, capture_output=True, text=True, encoding="utf-8",
        ).stdout.strip()
        if disk != head:
            diffs.append(rel)

    assert not diffs, (
        f"这些产品文件与 HEAD 的 blob 不同：{diffs}\n"
        f"若只是行尾差异（CRLF），用 git cat-file -p 落盘还原。"
    )


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
