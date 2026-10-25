"""检索因变量补全的行为契约。

`query` 与 `gold` 是 SEH@K / SRS 的前提。这两个字段的定义若有偏差，
后续所有检索指标都会失真。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from evals.tools.annotate_retrieval import annotate, gold_for


def _row(case_id: str, **overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "id": case_id,
        "text": "就是C区第三排左数第二个工位。",
        "subject": "user:default",
        "relation": "seat",
        "candidate_value": "C区第三排左数第二个工位",
        "existing_value": "靠窗那一排",
        "expected": "MERGE",
        "label_status": "confirmed",
    }
    base.update(overrides)
    return base


def _write(path: Path, rows: list[dict[str, object]]) -> Path:
    path.write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n",
        encoding="utf-8",
    )
    return path


def _read(path: Path) -> list[dict[str, object]]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def test_query_is_the_utterance_not_the_key(tmp_path: Path) -> None:
    """query 必须是原话语。拼进 subject/relation 会把答案放进查询里。"""
    path = _write(tmp_path / "t.jsonl", [_row("c1")])

    annotate(path)

    written = _read(path)[0]
    assert written["query"] == written["text"]
    assert "user:default" not in written["query"]
    assert "seat" not in written["query"]


def test_query_equals_text_after_annotate(tmp_path: Path) -> None:
    path = _write(tmp_path / "t.jsonl", [_row("c1")])

    annotate(path)

    written = _read(path)[0]
    assert written["query"] == written["text"]
    assert written["subject"] not in written["query"]


def test_gold_points_to_existing_value() -> None:
    row = _row("c1")

    gold = gold_for(row)

    assert gold is not None
    assert gold["value"] == "靠窗那一排"
    assert gold["subject"] == row["subject"]
    assert gold["relation"] == row["relation"]


def test_add_case_has_no_gold() -> None:
    """没有既有值的场景不可能有 gold。"""
    row = _row("c1", existing_value=None, expected="ADD")

    assert gold_for(row) is None


def test_empty_existing_treated_as_no_gold() -> None:
    row = _row("c1", existing_value="")

    assert gold_for(row) is None


def test_gold_carries_existing_condition() -> None:
    """BRANCH 场景的 gold 必须带上它的条件，否则无法在池中唯一定位。"""
    row = _row("c1", existing_condition="meeting", expected="BRANCH")

    gold = gold_for(row)

    assert gold is not None
    assert gold["condition"] == "meeting"


def test_gold_carries_existing_authority() -> None:
    row = _row("c1", existing_authority="third_party")

    gold = gold_for(row)

    assert gold is not None
    assert gold["authority"] == "third_party"


def test_annotate_counts_gold_coverage(tmp_path: Path) -> None:
    path = _write(
        tmp_path / "t.jsonl",
        [
            _row("c1"),
            _row("c2", existing_value=None, expected="ADD"),
            _row("c3"),
        ],
    )

    stats = annotate(path)

    assert stats["total"] == 3
    assert stats["with_gold"] == 2
    assert stats["without_gold"] == 1


def test_annotate_is_idempotent(tmp_path: Path) -> None:
    path = _write(tmp_path / "t.jsonl", [_row("c1")])

    annotate(path)
    first = _read(path)
    annotate(path)
    second = _read(path)

    assert first == second


def test_annotate_sorts_by_id(tmp_path: Path) -> None:
    path = _write(tmp_path / "t.jsonl", [_row("c3"), _row("c1"), _row("c2")])

    annotate(path)

    assert [row["id"] for row in _read(path)] == ["c1", "c2", "c3"]


def test_existing_gold_is_not_overwritten(tmp_path: Path) -> None:
    """已有人工核过的 gold 不能被自动覆盖。"""
    hand = {"subject": "x", "relation": "y", "value": "手工指定", "condition": None}
    path = _write(tmp_path / "t.jsonl", [_row("c1", gold=hand)])

    annotate(path)

    assert _read(path)[0]["gold"] == hand


# ---------- 真实数据的泄露程度 ----------


def test_query_gold_overlap_is_measured() -> None:
    """量化"query 复述了 gold"的比例。

    这不是缺陷，是数据集的性质：dev/test 的 MERGE 场景里，
    原话语本身就会复述旧值（"我们用 pnpm，另外还用了 workspace"）。
    而 independent 是真实对话，很少直接复述。

    **这个差异必须被测量**，否则 dev/test 上的词面召回会被系统性高估。
    """
    from pathlib import Path as _Path

    root = _Path(__file__).resolve().parents[2] / "data" / "conflict-set"
    ratios: dict[str, float] = {}
    for name in ("dev.jsonl", "test.jsonl", "independent.jsonl"):
        path = root / name
        if not path.exists():
            pytest.skip(f"{name} 不存在")
        rows = [
            json.loads(line)
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        with_gold = [row for row in rows if row.get("gold")]
        if not with_gold:
            continue
        leaked = sum(
            1 for row in with_gold if row["gold"]["value"] and row["gold"]["value"] in row["query"]
        )
        ratios[name] = leaked / len(with_gold)

    assert ratios["dev.jsonl"] > ratios["independent.jsonl"], (
        "预期 dev 的 query 更常复述 gold（MERGE 场景性质），"
        "若这条失败说明数据集结构变了，报告的分层结论需重算"
    )
    assert ratios["independent.jsonl"] < 0.2, (
        f"independent 的 gold 复述率 {ratios['independent.jsonl']:.0%} 过高，"
        "可能 query 被改写成了包含答案的形式"
    )
