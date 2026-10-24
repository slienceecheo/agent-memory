"""标注工具的行为契约。

工具存在的理由：标签必须能追溯到"谁在什么时候确认的"。
做成 CSV 手工编辑会丢失这个信息，且容易出现格式错误与遗漏。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from evals.datasets.conflict_set import load_conflict_set
from evals.tools.label import confirm_case, list_cases, update_label


def _case(case_id: str, **overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "id": case_id,
        "text": "现在改用 npm 了",
        "subject": "project:x",
        "relation": "package_manager",
        "candidate_value": "npm",
        "existing_value": "pnpm",
        "expected": "SUPERSEDE",
        "label_status": "proposed",
    }
    base.update(overrides)
    return base


def _write(path: Path, cases: list[dict[str, object]]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join(json.dumps(case, ensure_ascii=False) for case in cases) + "\n",
        encoding="utf-8",
    )
    return path


def test_list_returns_all(tmp_path: Path) -> None:
    path = _write(tmp_path / "dev.jsonl", [_case("c1"), _case("c2")])

    rows = list_cases(path, status=None)

    assert len(rows) == 2


def test_list_filters_by_status(tmp_path: Path) -> None:
    path = _write(
        tmp_path / "dev.jsonl",
        [
            _case("c1"),
            _case("c2", label_status="confirmed", labeler="alice", confirmed_at="2026-01-01"),
        ],
    )

    assert len(list_cases(path, status="proposed")) == 1
    assert len(list_cases(path, status="confirmed")) == 1


def test_confirm_changes_status_and_records_labeler(tmp_path: Path) -> None:
    """没有 labeler 就无法计算双人一致性。"""
    path = _write(tmp_path / "dev.jsonl", [_case("c1")])

    changed = confirm_case(
        path, case_id="c1", label="SUPERSEDE", labeler="alice", at="2026-10-25T10:00:00"
    )

    assert changed.label_status == "confirmed"
    assert changed.labeler == "alice"
    assert changed.confirmed_at == "2026-10-25T10:00:00"
    reloaded = load_conflict_set(path)
    assert reloaded.cases[0].label_status == "confirmed"


def test_confirm_rejects_unknown_id(tmp_path: Path) -> None:
    path = _write(tmp_path / "dev.jsonl", [_case("c1")])

    with pytest.raises(KeyError, match="nope"):
        confirm_case(path, case_id="nope", label="NOOP", labeler="alice")


def test_confirm_rejects_invalid_label(tmp_path: Path) -> None:
    path = _write(tmp_path / "dev.jsonl", [_case("c1")])

    with pytest.raises(ValueError, match="MAYBE"):
        confirm_case(path, case_id="c1", label="MAYBE", labeler="alice")


def test_confirm_can_correct_a_label(tmp_path: Path) -> None:
    """人工确认时发现提案标签是错的，应当能改。"""
    path = _write(tmp_path / "dev.jsonl", [_case("c1", expected="SUPERSEDE")])

    changed = confirm_case(
        path, case_id="c1", label="MERGE", labeler="alice", at="2026-10-25T10:00:00"
    )

    assert changed.expected.value == "MERGE"


def test_confirm_requires_labeler(tmp_path: Path) -> None:
    path = _write(tmp_path / "dev.jsonl", [_case("c1")])

    with pytest.raises(ValueError, match="labeler"):
        confirm_case(path, case_id="c1", label="NOOP", labeler="  ")


def test_update_label_keeps_other_cases_intact(tmp_path: Path) -> None:
    """改一条不能影响其他条。"""
    path = _write(tmp_path / "dev.jsonl", [_case("c1"), _case("c2")])

    update_label(path, case_id="c1", label="NOOP", labeler="alice")

    reloaded = load_conflict_set(path)
    by_id = {case.id: case for case in reloaded.cases}
    assert by_id["c1"].expected.value == "NOOP"
    assert by_id["c2"].expected.value == "SUPERSEDE"


def test_file_is_rewritten_in_stable_order(tmp_path: Path) -> None:
    """写回顺序不稳定会让 git diff 充满噪声。"""
    path = _write(tmp_path / "dev.jsonl", [_case("c3"), _case("c1"), _case("c2")])

    confirm_case(path, case_id="c2", label="NOOP", labeler="alice", at="2026-10-25T10:00:00")

    ids = [json.loads(line)["id"] for line in path.read_text(encoding="utf-8").splitlines()]
    assert ids == sorted(ids)
