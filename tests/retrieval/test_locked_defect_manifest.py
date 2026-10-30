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

    v2_anchor = "## 8. 缺陷 20 与 21"
    v2_text = V2_REPORT.read_text(encoding="utf-8")
    if v2_anchor in v2_text:
        v2_section = v2_text.split(v2_anchor)[1].split("\n## ")[0]
        # 这里的编号是加粗的（`| **20** |`），与 C4 表的 `| 20 |` 格式不同
        numbers |= {
            int(m)
            for m in re.findall(r"^\|\s*\**\s*(\d+)\s*\**\s*\|", v2_section, re.MULTILINE)
        }

    return numbers


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
