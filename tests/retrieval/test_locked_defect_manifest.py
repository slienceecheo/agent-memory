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
    8: (
        "test_dedup_receives_ids_not_text",
        "test_constant_scores_turn_dedup_into_a_lexical_sort",
    ),
}

# 已修复的缺陷编号 -> 翻面后的正向断言。
#
# 缺陷 7（三路召回从未联合跑过）在第 2 组接上词面+向量后部分修复；
# 邻接仍未接线，由 L6a/L6c 门禁覆盖，等第 3 组接上后整体翻面。
REPAIRED: dict[int, tuple[str, ...]] = {
    7: (
        "test_retrieval_entry_now_runs_lexical_and_vector",
        "test_embedding_is_written_into_the_pool",
    ),
}


def _defect_numbers_in_report() -> set[int]:
    """报告第 0.1 节末尾那张"八个缺陷"表里的编号。"""
    text = REPORT.read_text(encoding="utf-8")
    section = text.split("#### 这一节的结论")[1].split("## 1.")[0]
    return {int(match) for match in re.findall(r"^\| (\d+) \|", section, re.MULTILINE)}


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


def test_report_lists_eight_defects() -> None:
    """报告第 0.1 节必须列出八个缺陷。数量变化时要同步改映射。"""
    assert _defect_numbers_in_report() == set(range(1, 9))


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
