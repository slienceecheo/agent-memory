"""标签迁移脚本的行为契约。

修场景内容时不该丢掉已经确认的标签，但也不能把修改过的内容覆盖回去。
所以必须按 id 精确迁移，且只迁移标签字段。
"""

from __future__ import annotations

import json
from pathlib import Path

from evals.tools.preserve_labels import preserve


def _row(case_id: str, **overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "id": case_id,
        "text": "原文本",
        "subject": "project:x",
        "relation": "package_manager",
        "candidate_value": "npm",
        "existing_value": "pnpm",
        "expected": "SUPERSEDE",
        "label_status": "proposed",
    }
    base.update(overrides)
    return base


def _write(path: Path, rows: list[dict[str, object]]) -> Path:
    path.write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n",
        encoding="utf-8",
    )
    return path


def _read(path: Path) -> dict[str, dict[str, object]]:
    return {
        json.loads(line)["id"]: json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    }


def test_confirmed_label_is_migrated(tmp_path: Path) -> None:
    old = _write(
        tmp_path / "old.jsonl",
        [
            _row(
                "c1",
                expected="MERGE",
                label_status="confirmed",
                labeler="xly",
                confirmed_at="2026-10-25T10:00:00",
            )
        ],
    )
    new = _write(tmp_path / "new.jsonl", [_row("c1", expected="SUPERSEDE")])

    migrated, kept, orphaned = preserve(old, new)

    assert migrated == 1
    assert kept == 0
    assert orphaned == []
    row = _read(new)["c1"]
    assert row["expected"] == "MERGE"
    assert row["label_status"] == "confirmed"
    assert row["labeler"] == "xly"
    assert row["confirmed_at"] == "2026-10-25T10:00:00"


def test_proposed_label_is_not_migrated(tmp_path: Path) -> None:
    """未确认的条目应保持新文件的提案标签，而不是把旧提案搬过来。"""
    old = _write(tmp_path / "old.jsonl", [_row("c1", expected="NOOP")])
    new = _write(tmp_path / "new.jsonl", [_row("c1", expected="SUPERSEDE")])

    migrated, kept, _ = preserve(old, new)

    assert migrated == 0
    assert kept == 1
    assert _read(new)["c1"]["expected"] == "SUPERSEDE"


def test_content_fields_come_from_new_file(tmp_path: Path) -> None:
    """修好的内容不能被旧文件覆盖回去——这是本脚本存在的最大风险。"""
    old = _write(
        tmp_path / "old.jsonl",
        [
            _row(
                "c1",
                text="旧文本",
                candidate_value="旧值",
                label_status="confirmed",
                labeler="xly",
            )
        ],
    )
    new = _write(
        tmp_path / "new.jsonl",
        [_row("c1", text="修复后的文本", candidate_value="修复后的值")],
    )

    preserve(old, new)

    row = _read(new)["c1"]
    assert row["text"] == "修复后的文本"
    assert row["candidate_value"] == "修复后的值"
    assert row["label_status"] == "confirmed"


def test_orphaned_ids_are_reported(tmp_path: Path) -> None:
    """旧文件有、新文件没有的 id 必须报出来，不能静默丢弃。"""
    old = _write(
        tmp_path / "old.jsonl",
        [
            _row("c1", label_status="confirmed", labeler="xly"),
            _row("c2", label_status="confirmed", labeler="xly"),
        ],
    )
    new = _write(tmp_path / "new.jsonl", [_row("c1")])

    migrated, _, orphaned = preserve(old, new)

    assert migrated == 1
    assert orphaned == ["c2"]


def test_output_is_sorted_by_id(tmp_path: Path) -> None:
    old = _write(tmp_path / "old.jsonl", [_row("c3"), _row("c1"), _row("c2")])
    new = _write(tmp_path / "new.jsonl", [_row("c3"), _row("c1"), _row("c2")])

    preserve(old, new)

    ids = [json.loads(line)["id"] for line in new.read_text(encoding="utf-8").splitlines()]
    assert ids == sorted(ids)
