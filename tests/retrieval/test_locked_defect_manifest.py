"""F11：`locked_defect` 清单必须与报告第 0.1 节的缺陷一一对应。

**为什么不比数量**：用例数不等于缺陷数。
`test_authority_and_status_have_no_variance_in_pool` 有 3 个 parametrize 分支，
缺陷 8 又有两条互补的证据（入口传参 + 排序退化）。
直接比 `12 == 8` 会永远失败，然后人会去改数字——那就变成"让测试迁就现实"。

所以真正的判据是**覆盖关系**：

- 报告第 0.1 节列了 N 个缺陷（编号 1..N）
- 每个缺陷至少有一条 `locked_defect` 测试指向它
- 每条 `locked_defect` 测试都指向某个存在的缺陷（没有孤儿测试）

任一侧漂移都会让本文件变红：修了缺陷没更新报告，或加了缺陷没加测试。
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
REPORT = ROOT / "docs" / "reports" / "c4-retrieval.md"
# v2 的缺陷（20、21）记在 v2 报告里，不在 C4 报告里。
V2_REPORT = ROOT / "docs" / "reports" / "v2-what-it-measures.md"
TESTS = ROOT / "tests" / "retrieval"

# 缺陷编号 -> 覆盖它的测试函数名
#
# **本表随修复推进而收缩。** 已修复并翻面为正向断言的缺陷，不再出现在这里，
# 而是记在 `REPAIRED` 里——这样"修好了"与"忘了登记"能被区分开。
DEFECT_TESTS: dict[int, tuple[str, ...]] = {
    1: ("test_query_is_verbatim_the_gold_document",),
    2: ("test_constant_scores_turn_dedup_into_a_lexical_sort",),
    3: ("test_ranking_never_happened_on_independent",),
    4: ("test_authority_and_status_have_no_variance_in_pool",),
    5: (
        "test_distractors_are_a_fixed_prefix_not_a_sample",
        "test_unrelated_mode_is_a_file_order_prefix",
    ),
    6: ("test_same_relation_mixes_subjects",),
    9: ("test_non_dev_selection_is_all_from_dev",),
    10: (
        "test_test_and_dev_share_mirrored_branches",
        "test_test_split_is_not_independent",
    ),
    11: (
        "test_condition_match_prefers_unstated_over_mismatched",
        "test_branch_query_points_at_candidate_not_gold",
    ),
    13: ("test_pool_dedup_drops_distinct_values",),
    15: (
        "test_dedup_has_no_legal_merge_target_after_pool_build",
        "test_dedup_breaks_ties_by_id_not_by_input_order",
    ),
    16: (
        "test_adjacency_has_no_legal_target_on_dev",
        "test_adjacency_siblings_exist_but_are_truncated_away",
    ),
    18: ("test_sample_authority_is_unjustified",),
    19: ("test_q4_loses_to_unrelated_entries_on_authority",),
    # 以下两条是 v2 上测出的新缺陷，记在 v2 报告里而非 C4 报告。
    # 它们**可修复**：改 adapter 不传 query_condition、调 authority 权重。
    # 而"词面在 A 轴无增量"这类观测结论**不进本表**——没有"修好"这个状态。
    20: (
        "test_query_condition_is_a_verbatim_copy_of_gold",
        "test_condition_match_degenerates_to_string_equality",
    ),
    21: (
        "test_authority_penalty_equals_condition_bonus",
        "test_only_one_case_triggers_the_authority_critical_point",
    ),
    # 缺陷 22：spec 要求配对 bootstrap 区间，检索评测从未产出。
    # 这是"spec 的 MUST 没有对应测试"的实例——归档时未核对。
    22: (
        "test_spec_still_requires_intervals",
        "test_runner_does_not_compute_intervals",
        "test_results_have_no_interval_fields",
        "test_no_test_asserts_intervals_exist",
    ),
    # 缺陷 23：`parse_condition` 子串匹配混淆"误命中"与"多命中"。
    # 记在 v2 报告 §8.0——v3 之前登记，修法需要设计决策（甲/乙/丙）。
    23: (
        "test_defect23_true_positive_hits_are_real",
        "test_defect23_multi_hits_are_not_overlapping_and_are_correct",
        "test_defect23_produces_a_false_positive_similarity",
        "test_defect23_chinese_english_pair_is_not_equal",
        "test_defect23_dataset_values_split_into_three_groups",
        "test_defect23_spec_example_does_not_match",
        "test_defect23_exact_matching_would_break_three_values",
    ),
}

# 缺陷编号 -> 为什么还没修。
#
# **这不是"哪些能修"的判断，是"修它的动作是什么"的记录。**
# 分三类：
#
# | blocked_by | 含义 | 修它的动作 |
# |---|---|---|
# | `None` | 待修 | 改代码或改数据 |
# | `"dataset-frozen"` | 数据集已冻结（v2 是报告集，不是修复集） | 换数据，需要 v3 或 v2.1 |
# | `"needs-design"` | 修法有多个方案，需要设计决策 | 先定方案，再改代码 |
#
# **为什么不用"能不能修"做判断**：那会让"修不了"的缺陷从清单消失，
# 而清单的价值正是"还剩多少没修"。`blocked_by` 只回答"下一步是什么"。
BLOCKED_BY: dict[int, str | None] = {
    # 缺陷 1/9/10/13/16：全部是数据构造问题，修法是换数据集
    1: "dataset-frozen",
    9: "dataset-frozen",
    10: "dataset-frozen",
    13: "dataset-frozen",
    16: "dataset-frozen",
    # 缺陷 2/3/4/5/6/11/15/18/19：评测装置或权重问题，v3 可改
    2: None,
    3: None,
    4: None,
    5: None,
    6: None,
    11: None,
    15: None,
    18: None,
    19: None,
    # 缺陷 20/21/22：v3 可修（改 adapter / 调权重 / 补区间）
    20: None,
    21: None,
    22: None,
    # 缺陷 23：三种修法各有代价，必须先定方案
    23: "needs-design",
}

# 已修复的缺陷编号 -> 翻面后的正向断言。
#
# 缺陷 7（三路召回从未联合跑过）：第 1–3 组接上三路后修复。
# 缺陷 8（dedup 收到 id 与常数分）：第 3 组修复。
# 缺陷 12（归档文件名不区分路径集合）：加 `_assert_writable` 后修复。
# 缺陷 14（gold 向量输入含 query 原文）：`_embedding_text` 不再读 text 后修复。
#   `text` 字段本身保留给 FTS——实测去掉会让 10 条 case 零召回。
REPAIRED: dict[int, tuple[str, ...]] = {
    7: (
        "test_retrieval_entry_now_runs_lexical_and_vector",
        "test_embedding_is_written_into_the_pool",
    ),
    8: (
        "test_dedup_receives_text_and_real_scores",
        "test_constant_scores_turn_dedup_into_a_lexical_sort",
    ),
    12: ("test_archive_overwrite_is_refused",),
    14: ("test_gold_document_text_does_not_contain_query",),
    17: ("test_vector_without_embedder_raises",),
}


def _defect_numbers_in_report() -> set[int]:
    """两份报告「缺陷总表」里的编号。

    **为什么要两份**：缺陷 1–19 记在 C4 报告，缺陷 20–21 是 v2 才测出来的，
    记在 v2 报告。只读 C4 会让 20/21 变成"孤儿缺陷"。

    定位锚点写死是危险的（重构时静默失效），所以显式检查锚点存在。
    """
    numbers: set[int] = set()

    c4_anchor = "### 0.4 缺陷总表"
    c4_text = REPORT.read_text(encoding="utf-8")
    if c4_anchor not in c4_text:
        pytest.fail(f"C4 报告里找不到「{c4_anchor}」，无法核对缺陷表")
    c4_section = c4_text.split(c4_anchor)[1].split("#### ")[0]
    numbers |= {int(m) for m in re.findall(r"^\| (\d+) \|", c4_section, re.MULTILINE)}

    v2_numbers, _ = _v2_defect_numbers(V2_REPORT.read_text(encoding="utf-8"))
    numbers |= v2_numbers

    return numbers


def _v2_defect_numbers(text: str) -> tuple[set[int], bool]:
    """从 v2 报告里取缺陷编号。

    **锚点不能写死**：原先写的是 `## 8. 缺陷 20 与 21`，
    而 2026-11-05 新增结论 5 后那一节变成了 §9——锚点失配，
    `if v2_anchor in v2_text` 静默跳过，返回空集合。

    **后果**：`test_report_lists_all_defects` 报"缺 [20,21,22,23]"，
    而正文其实都在。**错的是锚点，不是报告。**

    现在改为**按标题前缀匹配**（`## <数字>. 缺陷`），并把"找到了没有"
    返回给调用方，让它能显式失败。
    """
    m = re.search(r"^## \d+\. 缺陷.*$", text, re.MULTILINE)
    if not m:
        return set(), False

    section = text[m.start() :].split("\n## ")[0]
    # 这里的编号是加粗的（`| **20** |`），与 C4 表的 `| 20 |` 格式不同
    found = {
        int(x)
        for x in re.findall(r"^\|\s*\**\s*(\d+)\s*\**\s*\|", section, re.MULTILINE)
    }
    return found, True


def _marked_test_names() -> set[str]:
    """所有带 locked_defect 标记的测试函数名。"""
    names: set[str] = set()
    for path in TESTS.glob("test_*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.FunctionDef) or not node.name.startswith("test_"):
                continue
            marked = any(
                "locked_defect" in ast.unparse(decorator) for decorator in node.decorator_list
            )
            if marked:
                names.add(node.name)
    return names


def test_report_lists_all_defects() -> None:
    """两份报告合起来必须列出映射表里的**所有**编号。

    原先断言 `== set(range(1, 20))`——那是只有 C4 一份报告时的写法。
    缺陷 20/21 是 v2 测出来的，记在 v2 报告里，所以现在的判据是
    "两份并集 == 映射表"，而不是"恰好 1..19"。

    函数名不带数字：原先叫 `test_report_lists_eight_defects`，
    加到 13 条时只改断言不改名字，就成了缺陷 6（报告与实现不一致）的同一形态。
    """
    in_reports = _defect_numbers_in_report()
    mapped = set(DEFECT_TESTS) | set(REPAIRED)

    _, v2_found = _v2_defect_numbers(V2_REPORT.read_text(encoding="utf-8"))
    assert v2_found, (
        "v2 报告里找不到「## <数字>. 缺陷」这一节——"
        "锚点失配会让 20-23 被静默漏掉，而它们其实记在正文里"
    )

    assert in_reports == mapped, (
        f"报告里缺 {sorted(mapped - in_reports)}；"
        f"报告里多出 {sorted(in_reports - mapped)}"
    )
    # C4 报告本身仍必须覆盖 1..19（v2 的两条在另一份）
    assert set(range(1, 20)) <= in_reports


def test_every_defect_has_a_locked_test() -> None:
    """每个缺陷要么有锁定测试，要么已登记为修复。"""
    missing = set(_defect_numbers_in_report()) - set(DEFECT_TESTS) - set(REPAIRED)
    assert not missing, f"缺陷 {sorted(missing)} 既没有锁定测试，也没登记为已修复"


def test_no_orphan_locked_tests() -> None:
    """每条 locked_defect 测试都必须指向一个已登记的缺陷。

    孤儿测试通常意味着：某个缺陷被修好后，测试被保留但没人更新映射。
    """
    marked = _marked_test_names()
    mapped = {name for names in DEFECT_TESTS.values() for name in names}

    assert not (marked - mapped), f"未登记的锁定测试：{sorted(marked - mapped)}"
    assert not (mapped - marked), f"映射里有不存在的测试：{sorted(mapped - marked)}"


def test_repaired_tests_exist() -> None:
    """`REPAIRED` 里登记的正向断言必须真实存在。"""
    for names in REPAIRED.values():
        for name in names:
            assert f"def {name}(" in "".join(
                path.read_text(encoding="utf-8")
                for path in TESTS.glob("test_*.py")
            ), f"REPAIRED 里登记了不存在的测试：{name}"


def test_repaired_defects_are_not_also_locked() -> None:
    """已修复的缺陷不得同时留在锁定表里——那说明翻面没做干净。"""
    assert not (set(REPAIRED) & set(DEFECT_TESTS))


def test_all_mapped_tests_exist_and_are_marked() -> None:
    """映射表里的名字必须真实存在，且真的带标记。"""
    marked = _marked_test_names()
    mapped = {name for names in DEFECT_TESTS.values() for name in names}

    assert mapped <= marked


@pytest.mark.parametrize("defect", sorted(DEFECT_TESTS))
def test_defect_number_appears_in_report(defect: int) -> None:
    """映射里的每个编号都真的出现在报告表格里。"""
    assert defect in _defect_numbers_in_report()


# ---------- blocked_by：为什么还没修 ----------


def test_every_unrepaired_defect_declares_why() -> None:
    """每条未修复缺陷都必须回答"为什么还没修"。

    **不回答会让 `blocked_by` 变成半个字段**——只有部分条目填了，
    下一个人查询"还剩多少能修"时会得到错误的数。
    """
    from tests.retrieval.test_locked_defect_manifest import BLOCKED_BY

    unrepaired = set(DEFECT_TESTS)
    missing = unrepaired - set(BLOCKED_BY)
    assert not missing, f"缺陷 {sorted(missing)} 未声明 blocked_by"

    extra = set(BLOCKED_BY) - unrepaired
    assert not extra, f"已修复的缺陷不该出现在 BLOCKED_BY：{sorted(extra)}"


def test_blocked_by_values_are_from_a_fixed_vocabulary() -> None:
    """取值只能是三种：None / dataset-frozen / needs-design。

    自由文本会让"还剩多少能修"无法机器统计，而那正是这个字段的用途。
    """
    from tests.retrieval.test_locked_defect_manifest import BLOCKED_BY

    allowed = {None, "dataset-frozen", "needs-design"}
    bad = {k: v for k, v in BLOCKED_BY.items() if v not in allowed}
    assert not bad, f"未知的 blocked_by 取值：{bad}"


def test_dataset_frozen_defects_are_the_data_ones() -> None:
    """`dataset-frozen` 必须只标在"修法是换数据"的缺陷上。

    实测依据：这些缺陷的锁定测试都不随代码改动变红（除 13/16 依赖 evals 代码）。
    若哪天把一条代码缺陷标成 `dataset-frozen`，这个过滤条件就失去意义了。
    """
    from tests.retrieval.test_locked_defect_manifest import BLOCKED_BY

    frozen = {k for k, v in BLOCKED_BY.items() if v == "dataset-frozen"}
    assert frozen == {1, 9, 10, 13, 16}, f"dataset-frozen 集合变成 {sorted(frozen)}"


def test_needs_design_is_only_defect_23() -> None:
    """`needs-design` 目前只有缺陷 23（三种修法各有代价）。"""
    from tests.retrieval.test_locked_defect_manifest import BLOCKED_BY

    design = {k for k, v in BLOCKED_BY.items() if v == "needs-design"}
    assert design == {23}, f"needs-design 集合变成 {sorted(design)}"


def test_actionable_defect_count_is_queryable() -> None:
    """`blocked_by is None` 的条数是可查询的——这是这个字段存在的理由。

    23 条未修复缺陷 = 12 条待修 + 5 条等换数据 + 1 条等设计 + 5 条已修复不该在此表。

    注意：本表只覆盖**未修复**的缺陷（`DEFECT_TESTS`，18 条），已修复的 5 条
    在 `REPAIRED` 里。所以三组之和必须等于 `DEFECT_TESTS` 的条数。
    """
    from tests.retrieval.test_locked_defect_manifest import BLOCKED_BY

    actionable = [k for k, v in BLOCKED_BY.items() if v is None]
    frozen = [k for k, v in BLOCKED_BY.items() if v == "dataset-frozen"]
    design = [k for k, v in BLOCKED_BY.items() if v == "needs-design"]

    assert len(actionable) == 12, f"待修变成 {len(actionable)} 条：{sorted(actionable)}"
    assert len(frozen) == 5
    assert len(design) == 1
    assert len(actionable) + len(frozen) + len(design) == len(DEFECT_TESTS)
