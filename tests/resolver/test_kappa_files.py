"""双人标注的 κ 计算。

当前的存储模型里，一条场景只有一个 `labeler` 字段，两个人标同一份文件会互相覆盖。
所以真双人标注必须用**两份副本**：

    test.jsonl        原文件（保留提案）
    test.alice.jsonl  alice 的标注
    test.bob.jsonl    bob 的标注

κ 从两份副本的 `expected` 字段求一致率，而不看 `labeler`
（副本里 `labeler` 各自不同，用它是同义反复）。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from evals.tools.label import kappa_from_files


def _case(case_id: str, expected: str, labeler: str = "x") -> dict[str, object]:
    return {
        "id": case_id,
        "text": "现在改用 npm 了",
        "subject": "project:x",
        "relation": "package_manager",
        "candidate_value": "npm",
        "existing_value": "pnpm",
        "expected": expected,
        "label_status": "confirmed",
        "labeler": labeler,
        "confirmed_at": "2026-10-25T10:00:00",
    }


def _write(path: Path, cases: list[dict[str, object]]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join(json.dumps(c, ensure_ascii=False) for c in cases) + "\n",
        encoding="utf-8",
    )
    return path


def test_identical_files_give_kappa_one(tmp_path: Path) -> None:
    cases = [_case("c1", "NOOP"), _case("c2", "ADD", labeler="b")]
    a = _write(tmp_path / "a.jsonl", cases)
    b = _write(tmp_path / "b.jsonl", cases)

    result = kappa_from_files(a, b)

    assert result.kappa == pytest.approx(1.0)
    assert result.shared == 2
    assert result.disagreements == []


def test_disagreements_are_listed_with_both_labels(tmp_path: Path) -> None:
    """报告必须能定位到具体哪几条不一致，否则无法坐下来讨论。"""
    a = _write(tmp_path / "a.jsonl", [_case("c1", "NOOP"), _case("c2", "ADD")])
    b = _write(tmp_path / "b.jsonl", [_case("c1", "NOOP"), _case("c2", "MERGE", "bob")])

    result = kappa_from_files(a, b)

    assert result.shared == 2
    assert len(result.disagreements) == 1
    disagreement = result.disagreements[0]
    assert disagreement.case_id == "c2"
    assert disagreement.left == "ADD"
    assert disagreement.right == "MERGE"


def test_only_shared_cases_are_compared(tmp_path: Path) -> None:
    """一方漏标时不该算作不一致，而应从共同集合里排除。"""
    a = _write(tmp_path / "a.jsonl", [_case("c1", "NOOP"), _case("c2", "ADD")])
    b = _write(tmp_path / "b.jsonl", [_case("c1", "NOOP")])

    result = kappa_from_files(a, b)

    assert result.shared == 1
    assert result.only_left == ["c2"]


def test_no_shared_cases_raises(tmp_path: Path) -> None:
    a = _write(tmp_path / "a.jsonl", [_case("c1", "NOOP")])
    b = _write(tmp_path / "b.jsonl", [_case("c2", "ADD")])

    with pytest.raises(ValueError, match="共同"):
        kappa_from_files(a, b)


def test_kappa_uses_expected_not_labeler(tmp_path: Path) -> None:
    """用 labeler 求一致率是同义反复：两份文件里它天然不同。"""
    a = _write(tmp_path / "a.jsonl", [_case("c1", "NOOP", labeler="alice")])
    b = _write(tmp_path / "b.jsonl", [_case("c1", "ADD", labeler="bob")])

    result = kappa_from_files(a, b)

    assert result.shared == 1
    assert result.kappa < 1.0


def test_verdict_thresholds(tmp_path: Path) -> None:
    """κ 的解释必须写进结果，避免读者自行发挥。"""
    cases = [_case(f"c{i}", "NOOP") for i in range(10)]
    a = _write(tmp_path / "a.jsonl", cases)
    b = _write(tmp_path / "b.jsonl", cases)

    result = kappa_from_files(a, b)

    assert "高度一致" in result.verdict


def test_low_kappa_verdict_warns(tmp_path: Path) -> None:
    a = _write(tmp_path / "a.jsonl", [_case(f"c{i}", "NOOP") for i in range(10)])
    b = _write(
        tmp_path / "b.jsonl",
        [_case(f"c{i}", "NOOP" if i % 3 == 0 else "ADD") for i in range(10)],
    )

    result = kappa_from_files(a, b)

    assert result.kappa < 0.7
    assert "不足" in result.verdict
