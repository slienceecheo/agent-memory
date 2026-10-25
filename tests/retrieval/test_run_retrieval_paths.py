"""`--paths` 与 `path_returns` 的行为契约（第 1 组）。

**设计要点：四种状态必须可区分。**

| 状态 | `paths_enabled` | `paths_unwired` | `path_returns` |
|---|---|---|---|
| 没开 | 不含 | — | `null` |
| 开了但代码路径不存在 | 含 | 含 | `null` |
| 跑了，返回空 | 含 | 不含 | `0` |
| 跑了，有结果 | 含 | 不含 | `> 0` |

**为什么不用布尔**：布尔会把"没开"与"跑了但空"压成同一个 `false`，
而这两种情况的排查方向完全相反——这正是 L6c 要区分的。

**为什么还要 `paths_unwired`**：第 1 组只加观测、不接召回逻辑，
所以 vector/adjacency 此刻"被启用但从未被调用"。
若把它记成 `0`，就谎称了"跑了但返回空"；而第 2 组接上之后
`0` 才是真信号。少了这一列，第 1 组与第 2 组的状态无法区分。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from evals.run_retrieval import evaluate, parse_paths

from memory.retrieval.pool_modes import PoolMode

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data" / "conflict-set"

ALL_PATHS = ("lexical", "vector", "adjacency")


def _rows(name: str) -> list[dict[str, object]]:
    path = DATA / name
    if not path.exists():
        pytest.skip(f"{name} 不存在")
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _all_specs() -> list[dict[str, object]]:
    specs: list[dict[str, object]] = []
    for name in ("dev.jsonl", "test.jsonl", "independent.jsonl"):
        specs.extend([row["gold"] for row in _rows(name) if row.get("gold")])  # type: ignore[misc]
    return specs


# ---------- 解析语义：白名单 ----------


def test_parse_default_is_all_three() -> None:
    """默认全开：新用户跑一遍应看到完整行为，而不是残缺的一路。"""
    assert parse_paths(None) == ALL_PATHS


def test_parse_whitelist() -> None:
    assert parse_paths("lexical") == ("lexical",)
    assert parse_paths("lexical,vector") == ("lexical", "vector")


def test_parse_empty_means_zero_recall() -> None:
    """空字符串 = 全关，对应规格里的"全部关闭返回空结果"。"""
    assert parse_paths("") == ()


def test_parse_whitespace_and_order_are_normalized() -> None:
    assert parse_paths(" vector , lexical ") == ("lexical", "vector")


def test_parse_rejects_unknown_path() -> None:
    """打错路名必须报错，不能静默当成"没开"。"""
    with pytest.raises(ValueError, match="sparse"):
        parse_paths("lexical,sparse")


def test_parse_rejects_duplicates_silently_dedupes() -> None:
    assert parse_paths("lexical,lexical") == ("lexical",)


# ---------- 结果里的可观测字段 ----------


def _with_gold(name: str, count: int) -> list[dict[str, object]]:
    """取前 `count` 条**有 gold** 的场景。

    没有 gold 的 ADD 场景会走 early return，不产生 `path_returns`，
    用它做断言会得到误导性的 None。
    """
    rows = [row for row in _rows(name) if row.get("gold")]
    if not rows:
        pytest.skip(f"{name} 没有带 gold 的场景")
    return rows[:count]


def test_result_records_paths_enabled_and_returns() -> None:
    rows = _with_gold("dev.jsonl", 3)
    specs = _all_specs()

    result = evaluate(
        rows,
        all_specs=specs,
        weights_name="uniform",
        enable_dedup=False,
        judge=None,
        k=5,
        pool_mode=PoolMode.UNRELATED,
        paths=("lexical",),
    )

    assert result["paths_enabled"] == ["lexical"]
    returns = result["path_returns"]
    assert set(returns) == set(ALL_PATHS)
    assert isinstance(returns["lexical"], int)
    assert returns["vector"] is None
    assert returns["adjacency"] is None


def test_disabled_path_is_null_not_zero() -> None:
    """没开的一路必须是 null。用 0 会与"跑了但空"混淆。"""
    rows = _with_gold("dev.jsonl", 2)
    specs = _all_specs()

    result = evaluate(
        rows,
        all_specs=specs,
        weights_name="uniform",
        enable_dedup=False,
        judge=None,
        k=5,
        pool_mode=PoolMode.UNRELATED,
        paths=("lexical",),
    )

    assert result["path_returns"]["vector"] is None
    assert result["paths_unwired"] == []


def test_enabled_but_unwired_is_null_and_listed() -> None:
    """第 1 组的真实状态：默认全开，但 vector/adjacency 还没有调用点。

    此时它们必须是 `null` + 出现在 `paths_unwired` 里，
    不能记成 `0`——那会谎称"跑了但返回空"。
    """
    rows = _with_gold("dev.jsonl", 2)
    specs = _all_specs()

    result = evaluate(
        rows,
        all_specs=specs,
        weights_name="uniform",
        enable_dedup=False,
        judge=None,
        k=5,
        pool_mode=PoolMode.UNRELATED,
        paths=ALL_PATHS,
    )

    assert result["paths_enabled"] == list(ALL_PATHS)
    # vector 已在第 2 组接上，只剩 adjacency 未接线。
    # 这条断言会随接线进度变化，是**进度标记**而非缺陷锁定。
    assert result["paths_unwired"] == ["adjacency"]
    assert result["path_returns"]["adjacency"] is None
    assert isinstance(result["path_returns"]["lexical"], int)


def test_zero_recall_baseline_scores_zero() -> None:
    """全关时 SEH 必须是 0，不是 1。

    这条直接对应"指标是死的"那一类：若空召回也记命中，说明指标算错。
    """
    rows = _rows("dev.jsonl")

    result = evaluate(
        rows,
        all_specs=_all_specs(),
        weights_name="uniform",
        enable_dedup=False,
        judge=None,
        k=5,
        pool_mode=PoolMode.UNRELATED,
        paths=(),
    )

    assert result["seh_at_k"] == 0.0
    assert result["paths_enabled"] == []
    assert all(value is None for value in result["path_returns"].values())
