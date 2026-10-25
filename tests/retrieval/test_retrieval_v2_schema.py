"""v2 数据集的 schema 与加载契约。

先写测试：这些断言全部来自 `docs/requirements/retrieval-dataset-v2.md`
（tag `dataset-v2-protocol`），每一条都对应一个已记录的 C4 缺陷。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from evals.datasets.retrieval_v2 import (
    Author,
    Axis,
    BranchNature,
    CueType,
    InvalidDataset,
    load_dataset,
    parse_memory,
    parse_query,
)

from memory.store.models import Authority

ROOT = Path(__file__).resolve().parents[2]
SAMPLE = ROOT / "data" / "retrieval-v2" / "sample"


def _memory(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "memory_id": "m-1",
        "subject": "project:ledger",
        "relation": "package_manager",
        "value": "pnpm",
        "memory_text": "我们用 pnpm 管理依赖",
        "authority": "user_direct",
        "status": "ACTIVE",
        "branch_nature": "natural",
        "valid_from": "2026-01-01T00:00:00+00:00",
        "condition": None,
    }
    base.update(overrides)
    return base


def _query(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "query_id": "q-1",
        "query": "我们这个仓库用什么包管理器？",
        "subject": "project:ledger",
        "axis": "C",
        "cue_type": "explicit",
        "gold_memory_id": "m-1",
        "expected_value": "pnpm",
        "author": "primary",
        "query_condition": None,
    }
    base.update(overrides)
    return base


# ---------- 字段级 ----------


def test_memory_text_is_required() -> None:
    """L4：没有原文的记忆直接拒绝，不许等到评测才发现。

    C4 的干扰项 `text=None`，导致它们在索引里只剩 subject/relation/value，
    词面召回无从匹配——那不是"数据不完整"，是测量装置坏了。
    """
    raw = _memory()
    del raw["memory_text"]

    with pytest.raises(InvalidDataset, match="memory_text"):
        parse_memory(raw, where="t")


def test_empty_memory_text_is_rejected() -> None:
    raw = _memory(memory_text="   ")

    with pytest.raises(InvalidDataset, match="memory_text"):
        parse_memory(raw, where="t")


def test_branch_nature_is_required() -> None:
    """不许省略——省略了就分不清难度是真实的还是构造的。"""
    raw = _memory()
    del raw["branch_nature"]

    with pytest.raises(InvalidDataset, match="branch_nature"):
        parse_memory(raw, where="t")


def test_cue_type_is_required() -> None:
    """`cue_type` 缺省会让"显式条件"悄悄变成主集，F13 就失去意义。"""
    raw = _query()
    del raw["cue_type"]

    with pytest.raises(InvalidDataset, match="cue_type"):
        parse_query(raw, where="t")


def test_unknown_cue_type_is_rejected() -> None:
    with pytest.raises(InvalidDataset, match="cue_type"):
        parse_query(_query(cue_type="vague"), where="t")


def test_unknown_author_is_rejected() -> None:
    with pytest.raises(InvalidDataset, match="author"):
        parse_query(_query(author="friend"), where="t")


def test_condition_defaults_to_none() -> None:
    parsed = parse_memory(_memory(), where="t")

    assert parsed.condition is None
    assert parsed.authority is Authority.USER_DIRECT


def test_supersedes_is_optional() -> None:
    assert parse_memory(_memory(), where="t").supersedes is None


# ---------- 数据集级 ----------


def _write(
    tmp_path: Path,
    memories: list[dict[str, object]],
    queries: list[dict[str, object]],
) -> Path:
    root = tmp_path / "ds"
    root.mkdir()
    (root / "memories.jsonl").write_text(
        "\n".join(json.dumps(m, ensure_ascii=False) for m in memories) + "\n", encoding="utf-8"
    )
    (root / "queries.jsonl").write_text(
        "\n".join(json.dumps(q, ensure_ascii=False) for q in queries) + "\n", encoding="utf-8"
    )
    return root


def test_gold_memory_must_exist(tmp_path: Path) -> None:
    root = _write(tmp_path, [_memory()], [_query(gold_memory_id="m-999")])

    with pytest.raises(InvalidDataset, match="m-999"):
        load_dataset(root)


def test_duplicate_memory_id_is_rejected(tmp_path: Path) -> None:
    root = _write(tmp_path, [_memory(), _memory()], [_query()])

    with pytest.raises(InvalidDataset, match="重复"):
        load_dataset(root)


def test_missing_file_is_reported_with_path(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError, match=r"memories\.jsonl"):
        load_dataset(tmp_path / "nowhere")


def test_cue_type_counts_cover_both_kinds(tmp_path: Path) -> None:
    root = _write(
        tmp_path,
        [_memory()],
        [
            _query(query_id="q-1", cue_type="explicit"),
            _query(query_id="q-2", cue_type="implicit"),
        ],
    )

    assert load_dataset(root).cue_type_counts() == {"explicit": 1, "implicit": 1}


def test_forced_subject_ratio_counts_subjects_not_rows(tmp_path: Path) -> None:
    """一个 subject 写 5 条 forced，占比只算 1 个 subject，不按条目稀释。"""
    root = _write(
        tmp_path,
        [
            _memory(memory_id=f"m-{i}", subject="project:forced", branch_nature="forced")
            for i in range(5)
        ]
        + [_memory(memory_id="n-1", subject="project:natural")],
        [_query(gold_memory_id="n-1")],
    )

    assert load_dataset(root).forced_subject_ratio() == pytest.approx(0.5)


def test_real_sample_dataset_loads() -> None:
    """样例数据集必须能被加载——它是 schema 的可运行证明。"""
    if not SAMPLE.exists():
        pytest.skip("样例数据集尚未生成")

    dataset = load_dataset(SAMPLE)

    assert dataset.memories
    assert dataset.queries
    assert dataset.subjects()


def test_real_sample_has_both_cue_types_per_subject() -> None:
    """F13：每个 subject 的 A 轴查询必须有 explicit 也有 implicit。"""
    if not SAMPLE.exists():
        pytest.skip("样例数据集尚未生成")

    dataset = load_dataset(SAMPLE)
    for subject in dataset.subjects():
        kinds = {
            q.cue_type
            for q in dataset.queries
            if q.subject == subject and q.axis is Axis.A
        }
        if not kinds:
            continue
        assert CueType.EXPLICIT in kinds and CueType.IMPLICIT in kinds, (
            f"{subject} 的 A 轴查询只有 {kinds}；两种都必须有，否则退化为测词表"
        )


def test_parse_query_accepts_author_independent() -> None:
    parsed = parse_query(_query(author="independent"), where="t")

    assert parsed.author is Author.INDEPENDENT
    assert parsed.axis is Axis.C
    assert parsed.cue_type is CueType.EXPLICIT


def test_parse_memory_accepts_forced_branch() -> None:
    assert parse_memory(_memory(branch_nature="forced"), where="t").branch_nature is (
        BranchNature.FORCED
    )
