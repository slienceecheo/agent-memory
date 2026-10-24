"""标注数据的逻辑自洽检查。

标注可以有主观分歧（同一条 A 说 MERGE、B 说 SUPERSEDE），但不能**违反定义**。

最典型的一类：`existing_value` 为空却标成 `NOOP` / `MERGE` / `SUPERSEDE` / `BRANCH`。
这四个类都以"存在既有值"为前提：
- NOOP：与既有值完全相同
- MERGE：既有值仍成立，新值更完整
- SUPERSEDE：既有值失效
- BRANCH：与既有值条件不同，并存

没有既有值时只可能是 `ADD`（或 `CONFLICT`，如果冲突对象来自库外）。

这类错误不会被 κ 抓出来——κ 只衡量"两人是否一致"，不衡量"是否合法"。
所以必须单独检查。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from evals.datasets.conflict_set import load_conflict_set
from evals.tools.label import check_logical_consistency

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data" / "conflict-set"

NEEDS_EXISTING = {"NOOP", "MERGE", "SUPERSEDE", "BRANCH"}


def _case(case_id: str, expected: str, existing: str | None, **overrides: object) -> dict:
    base = {
        "id": case_id,
        "text": "测试文本",
        "subject": "project:x",
        "relation": "package_manager",
        "candidate_value": "npm",
        "existing_value": existing,
        "expected": expected,
        "label_status": "confirmed",
        "labeler": "tester",
        "confirmed_at": "2026-10-26T10:00:00",
    }
    base.update(overrides)
    return base


def _write(path: Path, rows: list[dict]) -> Path:
    path.write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n",
        encoding="utf-8",
    )
    return path


# ---------- 检查器本身 ----------


@pytest.mark.parametrize("kind", sorted(NEEDS_EXISTING))
def test_kinds_requiring_existing_are_flagged(tmp_path: Path, kind: str) -> None:
    """没有既有值却标成这四类之一，必须被报出来。"""
    path = _write(tmp_path / "t.jsonl", [_case("c1", kind, None)])

    problems = check_logical_consistency(load_conflict_set(path))

    assert len(problems) == 1
    assert problems[0].case_id == "c1"
    assert problems[0].kind == "MISSING_EXISTING"
    assert kind in problems[0].detail


def test_add_without_existing_is_fine(tmp_path: Path) -> None:
    """ADD 的前提正是"没有既有值"，不该被报。"""
    path = _write(tmp_path / "t.jsonl", [_case("c1", "ADD", None)])

    assert check_logical_consistency(load_conflict_set(path)) == []


def test_supersede_with_existing_is_fine(tmp_path: Path) -> None:
    path = _write(tmp_path / "t.jsonl", [_case("c1", "SUPERSEDE", "pnpm")])

    assert check_logical_consistency(load_conflict_set(path)) == []


def test_conflict_without_existing_is_allowed(tmp_path: Path) -> None:
    """冲突对象可能来自库外（例如用户口述与文档矛盾），不强制要求既有值。"""
    path = _write(tmp_path / "t.jsonl", [_case("c1", "CONFLICT", None)])

    assert check_logical_consistency(load_conflict_set(path)) == []


def test_identical_values_are_flagged(tmp_path: Path) -> None:
    """值与既有值完全相同却标成 SUPERSEDE，逻辑上不成立（那应是 NOOP）。"""
    path = _write(tmp_path / "t.jsonl", [_case("c1", "SUPERSEDE", "npm")])

    problems = check_logical_consistency(load_conflict_set(path))

    assert any(problem.kind == "SUPERSEDE_WITH_SAME_VALUE" for problem in problems)


def test_identical_values_noop_is_fine(tmp_path: Path) -> None:
    path = _write(tmp_path / "t.jsonl", [_case("c1", "NOOP", "npm")])

    assert check_logical_consistency(load_conflict_set(path)) == []


def test_problem_message_is_actionable(tmp_path: Path) -> None:
    """报错要说清哪条、为什么、应该是什么。"""
    path = _write(tmp_path / "t.jsonl", [_case("test-add-01", "NOOP", None)])

    problems = check_logical_consistency(load_conflict_set(path))

    assert problems[0].case_id == "test-add-01"
    assert "既有值" in problems[0].message or "existing" in problems[0].message


# ---------- 真实数据必须干净 ----------


@pytest.mark.parametrize(
    "filename",
    ["dev.jsonl", "test.jsonl", "test.alice.jsonl", "test.bob.jsonl"],
)
def test_real_annotation_files_are_consistent(filename: str) -> None:
    """所有已提交的标注文件都必须逻辑自洽。

    这条会抓到"标注者看漏了 existing=None"这类硬错误——
    κ 抓不到它，因为 κ 只比较两人是否一致。
    """
    path = DATA / filename
    if not path.exists():
        pytest.skip(f"{filename} 不存在（双人副本可能未创建）")

    problems = check_logical_consistency(load_conflict_set(path))

    assert problems == [], "\n".join(
        f"{filename}: {p.case_id} 标成 {p.kind}，{p.message}" for p in problems
    )


def test_consistency_report_is_serializable(tmp_path: Path) -> None:
    """检查结果要能进报告。"""
    path = _write(tmp_path / "t.jsonl", [_case("c1", "NOOP", None)])

    problems = check_logical_consistency(load_conflict_set(path))

    payload = json.loads(json.dumps([p.model_dump() for p in problems]))
    assert payload[0]["case_id"] == "c1"
