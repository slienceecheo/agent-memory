"""报告的两处新结构：按"是否需要第三方"分类，以及缺陷 20/21 的登记。

**为什么需要**：

1. §1.1 的分类决定了哪条结论可以推广。若不写，
   读者会把"词面在 A 轴无增量"当成能力结论——而它依赖查询设计。

2. §8 把两条**可修复**的违规登记为缺陷 20/21。
   若不登记，它们就是"测出来了但没进清单"——清单的覆盖关系会漏掉真实缺陷。

两条都容易被后来的重构悄悄改掉，所以钉住。
"""

from __future__ import annotations

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
REPORT = ROOT / "docs" / "reports" / "v2-what-it-measures.md"


def _report() -> str:
    if not REPORT.exists():
        pytest.skip("报告缺失")
    return REPORT.read_text(encoding="utf-8")


# ---------- §1.1：按是否需要第三方分类 ----------


def test_report_classifies_conclusions_by_third_party_need() -> None:
    """必须按"是否需要第三方"给四条结论分类。"""
    text = _report()

    assert "是否需要第三方" in text
    assert "代码事实" in text
    assert "涉及查询设计" in text


def test_report_states_single_author_and_its_consequence() -> None:
    """必须写明数据全是单作者，以及这削弱了哪条结论。"""
    text = _report()

    assert "单一作者" in text or "单作者" in text
    assert "primary" in text
    # 结论 1 需要第三方
    assert "词面" in text
    assert "在这 2 个 subject 上观察到" in text


def test_report_states_third_party_requirement_moved_to_v3() -> None:
    """协议 §8.1 的"第二人独立编写 5 个"未执行，必须写明原因与去向。"""
    text = _report()

    assert "§8.1" in text or "8.1" in text
    assert "未执行" in text
    assert "v3" in text
    # 关键：说明它失去了 C3 那层保护
    assert "C3" in text
    assert "不具备第三方独立性" in text


def test_dataset_authors_are_really_all_primary() -> None:
    """数据必须支持"全是单作者"这个说法。"""
    import sys

    sys.path.insert(0, str(ROOT))
    from evals.datasets.retrieval_v2 import load_dataset

    for name in ("sample", "billing"):
        ds = load_dataset(ROOT / "data" / "retrieval-v2" / name)
        authors = {q.author.value for q in ds.queries}
        assert authors == {"primary"}, f"{name} 的 author 出现 {authors}"


# ---------- §8：缺陷 20 / 21 ----------


def test_report_registers_defects_20_and_21() -> None:
    text = _report()

    assert "## 8. 缺陷 20 与 21" in text
    assert "20" in text and "21" in text
    # 必须给出修法——否则无法判断它是否可修复
    assert "修法" in text
    # 必须说明为什么这两条能进、别的不进
    assert "为什么不登记的" in text


def test_defect_20_and_21_are_marked_locked() -> None:
    """两条新缺陷必须真的带 `locked_defect` 标记。"""
    import ast

    path = ROOT / "tests" / "retrieval" / "test_defects_20_21.py"
    if not path.exists():
        pytest.skip("文件缺失")

    tree = ast.parse(path.read_text(encoding="utf-8"))
    marked: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef):
            continue
        if any(
            "locked_defect" in ast.unparse(d) for d in node.decorator_list
        ):
            marked.add(node.name)

    assert marked == {
        "test_query_condition_is_a_verbatim_copy_of_gold",
        "test_condition_match_degenerates_to_string_equality",
        "test_authority_penalty_equals_condition_bonus",
        "test_only_one_case_triggers_the_authority_critical_point",
    }, marked


def test_non_defects_are_explicitly_excluded() -> None:
    """必须写明"词面无增量"与"四特征模型"不登记，并给出判据。"""
    text = _report()

    assert "词面在 A 轴无增量" in text
    assert "22/22" in text or "四特征模型" in text
    # 判据
    assert "换实验" in text or "没有" in text


def test_defect_numbers_in_both_reports() -> None:
    """缺陷 1–19 在 C4 报告，20–21 在 v2 报告——两份合起来才完整。"""
    import sys

    sys.path.insert(0, str(ROOT))
    from tests.retrieval.test_locked_defect_manifest import (
        DEFECT_TESTS,
        REPAIRED,
        _defect_numbers_in_report,
    )

    mapped = set(DEFECT_TESTS) | set(REPAIRED)
    assert 20 in mapped and 21 in mapped
    assert {20, 21} <= _defect_numbers_in_report()
    assert {1, 19} <= _defect_numbers_in_report()
