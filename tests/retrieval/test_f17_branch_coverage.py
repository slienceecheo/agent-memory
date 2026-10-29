"""F17a / F17b：分支覆盖必须按轴分开检查。

**为什么必须分轴**：旧 F17 用 `{q.gold_memory_id for q in dataset.queries}`，
不分轴。于是：

- 一条 C 轴查询若碰巧指向多分支 relation 的某个分支，旧 F17 会认为"该分支被覆盖"
- 但 C 轴测的是"同 subject 跨 relation 选择"，不是"同 relation 分支区分"

**实测后果**：`project:ledger` 的 5 个 relation 中，3 个多分支全靠 A 轴测、
2 个单值全靠 C 轴测，没有任何一个 relation 同时被两轴覆盖。旧 F17 绿，
新 F17b 红——这就是"门禁通过了但没测到"的形态。

拆成两条的粒度不同，因为两轴测的东西不同：

| 轴 | 要求 | 理由 |
|---|---|---|
| A（F17a） | 多分支的**每个分支** | 要在同 relation 的兄弟里挑对 |
| C（F17b） | 每个 **relation 一条** | 同一 relation 的多个分支在 C 轴上占同一个"属性位置" |
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from evals.datasets.retrieval_v2 import load_dataset
from evals.tools.check_v2_dataset import (
    check_f17_every_branch_queried,
    check_f17a_axis_a_covers_every_branch,
    check_f17b_every_relation_has_axis_c,
)

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


def _memory(
    memory_id: str,
    condition: str | None,
    value: str,
    *,
    relation: str = "code_style",
    subject: str = "project:x",
) -> dict:
    return {
        "memory_id": memory_id,
        "subject": subject,
        "relation": relation,
        "condition": condition,
        "value": value,
        "memory_text": f"原话 {value}",
        "authority": "user_direct",
        "status": "ACTIVE",
        "branch_nature": "natural",
        "valid_from": "2026-01-01T00:00:00+00:00",
    }


def _query(query_id: str, gold: str, *, axis: str = "A") -> dict:
    return {
        "query_id": query_id,
        "query": f"问题 {query_id}？",
        "subject": "project:x",
        "axis": axis,
        "cue_type": "explicit",
        "gold_memory_id": gold,
        "expected_value": "v",
        "author": "primary",
        "query_condition": "重构" if axis == "A" else None,
    }


# ---------- F17a：A 轴覆盖每个分支 ----------


def test_f17a_fails_when_a_branch_is_never_queried(tmp_path: Path) -> None:
    """3 个分支只写了 1 条 A 轴查询 → 另外 2 个分支从未被考过。"""
    root = _write(
        tmp_path,
        [
            _memory("m-1", "重构", "ruff"),
            _memory("m-2", "新功能", "mypy strict"),
            _memory("m-3", "小项目", "ruff 和黑"),
        ],
        [_query("q-1", "m-1")],
    )

    result = check_f17a_axis_a_covers_every_branch(load_dataset(root))

    assert result.code == "F17a"
    assert result.passed is False
    assert "2 个分支" in result.detail


def test_f17a_passes_when_all_branches_queried(tmp_path: Path) -> None:
    root = _write(
        tmp_path,
        [
            _memory("m-1", "重构", "ruff"),
            _memory("m-2", "新功能", "mypy strict"),
        ],
        [_query("q-1", "m-1"), _query("q-2", "m-2")],
    )

    result = check_f17a_axis_a_covers_every_branch(load_dataset(root))

    assert result.passed, result.detail


def test_f17a_ignores_c_axis_queries(tmp_path: Path) -> None:
    """**核心**：C 轴查询指向某分支，不算该分支被 A 轴覆盖。"""
    root = _write(
        tmp_path,
        [
            _memory("m-1", "重构", "ruff"),
            _memory("m-2", "新功能", "mypy strict"),
        ],
        [_query("q-1", "m-1", axis="C"), _query("q-2", "m-2", axis="C")],
    )

    result = check_f17a_axis_a_covers_every_branch(load_dataset(root))

    assert result.passed is False
    assert "2 个分支" in result.detail


def test_f17a_exempts_single_value_relation(tmp_path: Path) -> None:
    """单值 relation 不做 A 轴 gold——竞争集只有 1 条，L5 必红。"""
    root = _write(
        tmp_path,
        [_memory("m-solo", None, "pnpm", relation="package_manager")],
        [],
    )

    result = check_f17a_axis_a_covers_every_branch(load_dataset(root))

    assert result.passed, "单值 relation 不应要求 A 轴查询"


# ---------- F17b：C 轴覆盖每个 relation ----------


def test_f17b_fails_when_a_relation_has_no_c_query(tmp_path: Path) -> None:
    root = _write(
        tmp_path,
        [
            _memory("m-1", "重构", "ruff"),
            _memory("m-2", "新功能", "mypy strict"),
            _memory("m-solo", None, "pnpm", relation="package_manager"),
        ],
        [_query("q-1", "m-1"), _query("q-2", "m-2")],
    )

    result = check_f17b_every_relation_has_axis_c(load_dataset(root))

    assert result.code == "F17b"
    assert result.passed is False
    assert "package_manager" in result.detail


def test_f17b_requires_single_value_relation_covered(tmp_path: Path) -> None:
    """**与 F17a 相反**：单值 relation 在 C 轴上必须被覆盖。

    它做不了 A 轴 gold，但作为 C 轴的干扰项与目标都需要它。
    """
    root = _write(
        tmp_path,
        [_memory("m-solo", None, "pnpm", relation="package_manager")],
        [],
    )

    result = check_f17b_every_relation_has_axis_c(load_dataset(root))

    assert result.passed is False


def test_f17b_one_query_per_relation_is_enough(tmp_path: Path) -> None:
    """C 轴粒度是 relation，不是分支：一个多分支 relation 一条 C 轴即可。"""
    root = _write(
        tmp_path,
        [
            _memory("m-1", "重构", "ruff"),
            _memory("m-2", "新功能", "mypy strict"),
            _memory("m-solo", None, "pnpm", relation="package_manager"),
        ],
        [_query("q-c1", "m-1", axis="C"), _query("q-c2", "m-solo", axis="C")],
    )

    result = check_f17b_every_relation_has_axis_c(load_dataset(root))

    assert result.passed, result.detail


# ---------- 样例上的红绿 ----------


def test_sample_f17a_passes() -> None:
    """A 轴覆盖是完整的：10 个多分支全部被指向。"""
    if not SAMPLE.exists():
        pytest.skip("样例数据集缺失")

    result = check_f17a_axis_a_covers_every_branch(load_dataset(SAMPLE))

    assert result.passed, result.detail


def test_sample_f17b_fails() -> None:
    """**正确的失败**：C 轴只覆盖 2 个单值 relation。

    这不是待修的 bug，而是 §8"每 (subject, relation) 一条 C 轴"从未被
    门禁检查的直接后果。保留作为证据。
    """
    if not SAMPLE.exists():
        pytest.skip("样例数据集缺失")

    result = check_f17b_every_relation_has_axis_c(load_dataset(SAMPLE))

    assert result.passed is False
    assert "3/5" in result.detail


# ---------- F17 作为并集 ----------


def test_f17_equals_conjunction() -> None:
    """F17 停用，但函数必须与 F17a ∧ F17b 一致。"""
    if not SAMPLE.exists():
        pytest.skip("样例数据集缺失")

    dataset = load_dataset(SAMPLE)
    a = check_f17a_axis_a_covers_every_branch(dataset)
    b = check_f17b_every_relation_has_axis_c(dataset)
    combined = check_f17_every_branch_queried(dataset)

    assert combined.passed == (a.passed and b.passed)
