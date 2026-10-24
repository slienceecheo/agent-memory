"""场景集加载与校验的行为契约。

场景集的正确性直接决定 G2/D6 的可信度。三道防线：
1. schema 校验（缺字段、非法类别）
2. 六类分布均衡检查（稀有类样本太少时 macro-F1 不可信）
3. 标签状态必须区分 proposed / confirmed
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from evals.datasets.conflict_set import (
    ConflictCase,
    DuplicateCaseId,
    InvalidCase,
    load_conflict_set,
)

from memory.resolver.rules import DecisionKind


def _case(case_id: str, expected: str = "SUPERSEDE", **overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "id": case_id,
        "text": "现在改用 npm 了",
        "subject": "project:x",
        "relation": "package_manager",
        "candidate_value": "npm",
        "existing_value": "pnpm",
        "expected": expected,
        "label_status": "proposed",
    }
    base.update(overrides)
    return base


def _write(path: Path, cases: list[dict[str, object]]) -> Path:
    path.write_text(
        "\n".join(json.dumps(case, ensure_ascii=False) for case in cases) + "\n",
        encoding="utf-8",
    )
    return path


def test_load_valid_cases(tmp_path: Path) -> None:
    path = _write(tmp_path / "dev.jsonl", [_case("c1"), _case("c2")])

    dataset = load_conflict_set(path)

    assert len(dataset.cases) == 2
    assert isinstance(dataset.cases[0], ConflictCase)


def test_missing_required_field_is_rejected(tmp_path: Path) -> None:
    """缺字段会让后续统计静默错位。"""
    case = _case("c1")
    del case["candidate_value"]
    path = _write(tmp_path / "dev.jsonl", [case])

    with pytest.raises(InvalidCase, match="candidate_value"):
        load_conflict_set(path)


def test_invalid_expected_label_is_rejected(tmp_path: Path) -> None:
    """自由字符串会让混淆矩阵出现无法归类的行。"""
    path = _write(tmp_path / "dev.jsonl", [_case("c1", expected="MAYBE")])

    with pytest.raises(InvalidCase, match="expected"):
        load_conflict_set(path)


def test_duplicate_ids_are_rejected(tmp_path: Path) -> None:
    """重复 id 会让标注确认落到错误的条目上。"""
    path = _write(tmp_path / "dev.jsonl", [_case("c1"), _case("c1")])

    with pytest.raises(DuplicateCaseId, match="c1"):
        load_conflict_set(path)


def test_invalid_label_status_is_rejected(tmp_path: Path) -> None:
    """只有 proposed / confirmed 两种状态有意义。"""
    path = _write(tmp_path / "dev.jsonl", [_case("c1", label_status="maybe")])

    with pytest.raises(InvalidCase, match="label_status"):
        load_conflict_set(path)


def test_confirmed_case_requires_labeler(tmp_path: Path) -> None:
    """确认了却不知道谁确认的，κ 就算不出来。"""
    path = _write(tmp_path / "dev.jsonl", [_case("c1", label_status="confirmed")])

    with pytest.raises(InvalidCase, match="labeler"):
        load_conflict_set(path)


def test_proposed_case_has_no_labeler(tmp_path: Path) -> None:
    case = _case("c1")
    path = _write(tmp_path / "dev.jsonl", [case])

    dataset = load_conflict_set(path)

    assert dataset.cases[0].labeler is None


def test_imbalanced_distribution_is_reported(tmp_path: Path) -> None:
    """某类样本过少时 macro-F1 的方差会很大，必须提示。"""
    cases = [_case(f"c{i}", expected="SUPERSEDE") for i in range(9)]
    cases.append(_case("c9", expected="NOOP"))
    path = _write(tmp_path / "dev.jsonl", cases)

    dataset = load_conflict_set(path)

    assert dataset.is_balanced() is False
    assert dataset.min_class_count() == 1


def test_balanced_distribution_passes(tmp_path: Path) -> None:
    cases = []
    for kind in DecisionKind:
        for index in range(3):
            cases.append(_case(f"{kind.value}-{index}", expected=kind.value))
    path = _write(tmp_path / "dev.jsonl", cases)

    dataset = load_conflict_set(path)

    assert dataset.is_balanced() is True


def test_split_by_label_status(tmp_path: Path) -> None:
    """指标只在 confirmed 上作为验收依据。"""
    cases = [
        _case("c1"),
        _case("c2", label_status="confirmed", labeler="alice", confirmed_at="2026-01-01"),
    ]
    path = _write(tmp_path / "dev.jsonl", cases)
    dataset = load_conflict_set(path)

    confirmed = dataset.confirmed()
    proposed = dataset.proposed()

    assert len(confirmed.cases) == 1
    assert len(proposed.cases) == 1


def test_missing_file_raises_with_hint(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError, match="conflict-set"):
        load_conflict_set(tmp_path / "nope.jsonl")


def test_summary_counts_by_class(tmp_path: Path) -> None:
    cases = [
        _case("c1", expected="NOOP"),
        _case("c2", expected="NOOP"),
        _case("c3", expected="ADD"),
    ]
    dataset = load_conflict_set(_write(tmp_path / "dev.jsonl", cases))

    counts = dataset.class_counts()

    assert counts[DecisionKind.NOOP] == 2
    assert counts[DecisionKind.ADD] == 1
    assert counts[DecisionKind.MERGE] == 0
