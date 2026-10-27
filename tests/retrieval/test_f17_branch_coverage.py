"""F17：每个 condition 分支都必须至少被一条查询指向。

**为什么这条必须能失败**：L5 检查"池里有几条候选"，不检查"有几条被查询指向过"。
按旧口径（每 subject 4 条 A 轴查询）构造数据时，一个 4 relation 的 subject
只有 4 条查询 → 每 relation 1 条。其余分支会进池（L5 绿），
但永远不会成为任何查询的 gold。

这是 C4 缺陷 3 的精确重演：**池里有 3 条 ≠ 有查询在考这 3 条。**
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from evals.datasets.retrieval_v2 import load_dataset
from evals.tools.check_v2_dataset import check_f17_every_branch_queried

ROOT = Path(__file__).resolve().parents[2]
SAMPLE = ROOT / "data" / "retrieval-v2" / "sample"


def _write(tmp_path: Path, memories: list[dict], queries: list[dict]) -> Path:
    root = tmp_path / "ds"
    root.mkdir()
    (root / "memories.jsonl").write_text(
        "\n".join(json.dumps(m, ensure_ascii=False) for m in memories) + "\n",
        encoding="utf-8",
    )
    (root / "queries.jsonl").write_text(
        "\n".join(json.dumps(q, ensure_ascii=False) for q in queries) + "\n",
        encoding="utf-8",
    )
    return root


def _memory(memory_id: str, condition: str | None, value: str) -> dict:
    return {
        "memory_id": memory_id,
        "subject": "project:x",
        "relation": "code_style",
        "condition": condition,
        "value": value,
        "memory_text": f"原话 {value}",
        "authority": "user_direct",
        "status": "ACTIVE",
        "branch_nature": "natural",
        "valid_from": "2026-01-01T00:00:00+00:00",
    }


def _query(query_id: str, gold: str) -> dict:
    return {
        "query_id": query_id,
        "query": f"问题 {query_id}？",
        "subject": "project:x",
        "axis": "A",
        "cue_type": "explicit",
        "gold_memory_id": gold,
        "expected_value": "v",
        "author": "primary",
        "query_condition": "重构",
    }


def test_sample_passes(tmp_path: Path) -> None:
    """样例数据的分支都被查询指向。"""
    if not SAMPLE.exists():
        pytest.skip("样例数据集缺失")
    result = check_f17_every_branch_queried(load_dataset(SAMPLE))

    assert result.passed, result.detail


def test_fails_when_a_branch_is_never_queried(tmp_path: Path) -> None:
    """三个分支，只给其中一个写了查询 → 必须失败。

    这是旧口径（每 subject 4 条查询、4 relation）的精确形态：
    池里 3 条，L5 会绿，但只有 1 条被考过。
    """
    root = _write(
        tmp_path,
        [
            _memory("m-1", "重构", "ruff"),
            _memory("m-2", "新功能", "mypy strict"),
            _memory("m-3", "小项目", "ruff 就够了"),
        ],
        [_query("q-1", "m-1")],
    )

    result = check_f17_every_branch_queried(load_dataset(root))

    assert result.passed is False
    assert "2 个分支" in result.detail


def test_single_value_relation_is_exempt(tmp_path: Path) -> None:
    """单值 relation 不适用"每分支一条"。

    `package_manager` 只有一个值，天然没有条件维度。
    给它编造分支会让 `condition_match` 假性有效（协议 §3.4）。
    """
    root = _write(
        tmp_path,
        [_memory("m-solo", None, "pnpm")],
        [],
    )

    result = check_f17_every_branch_queried(load_dataset(root))

    assert result.passed, "单值 relation 不应被要求有查询"


def test_all_branches_queried_passes(tmp_path: Path) -> None:
    """每个分支都有查询时通过。"""
    root = _write(
        tmp_path,
        [
            _memory("m-1", "重构", "ruff"),
            _memory("m-2", "新功能", "mypy strict"),
        ],
        [_query("q-1", "m-1"), _query("q-2", "m-2")],
    )

    result = check_f17_every_branch_queried(load_dataset(root))

    assert result.passed, result.detail
