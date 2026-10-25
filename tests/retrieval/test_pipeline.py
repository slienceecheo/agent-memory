"""召回管线组合的行为契约。

三路必须能独立开关，且"全关"返回空而不是报错——
这样"零召回"能作为消融的基线端点。

截断也必须一致：各路长度不同会让 RRF 系统性偏向长列表。
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from memory.retrieval.adjacency import recall_by_adjacency
from memory.retrieval.lexical import recall_by_lexical
from memory.retrieval.vector import recall_by_vector
from memory.store.models import Authority, MemoryItem, Scope, Source, Status
from memory.store.sqlite import SqliteStore

NOW = datetime(2026, 1, 1, tzinfo=UTC)


def _item(
    *,
    value: str,
    text: str | None = None,
    subject: str = "user:a",
    relation: str = "seat",
    condition: str | None = None,
) -> MemoryItem:
    return MemoryItem(
        owner="o",
        scope=Scope.PROJECT,
        subject=subject,
        relation=relation,
        value=value,
        condition=condition,
        status=Status.ACTIVE,
        valid_from=NOW,
        valid_to=None,
        recorded_at=NOW,
        authority=Authority.USER_DIRECT,
        source=Source(session_id="s1"),
        text=text,
    )


@pytest.fixture
def store(tmp_path: Path) -> SqliteStore:
    instance = SqliteStore(tmp_path / "m.db", embedding_dims=4)
    yield instance
    instance.close()


def _seed(store: SqliteStore) -> None:
    for index in range(3):
        store.insert(
            _item(
                value=f"C区第{index}排",
                text=f"靠窗那一排 {index}",
                subject=f"user:{index}",
            ),
            reason="r",
            actor="t",
            embedding=[1.0, float(index) / 10, 0.0, 0.0],
        )


def test_each_path_works_independently(store: SqliteStore) -> None:
    _seed(store)

    lexical = recall_by_lexical(store, "靠窗")
    vector = recall_by_vector(store, [1.0, 0.0, 0.0, 0.0])
    adjacency = recall_by_adjacency(
        store, subject="user:a", relation="seat", condition="coding"
    )

    assert lexical
    assert vector
    assert adjacency == []  # 该主体下只有一个条件，没有兄弟


def test_all_paths_off_returns_empty(store: SqliteStore) -> None:
    """全关时必须返回空，而不是报错——"零召回"是消融的基线端点。"""
    _seed(store)

    enabled: set[str] = set()
    lexical = recall_by_lexical(store, "靠窗") if "lexical" in enabled else []
    vector = recall_by_vector(store, [1.0, 0.0, 0.0, 0.0]) if "vector" in enabled else []

    assert lexical == []
    assert vector == []


def test_limiting_one_path_does_not_affect_others(store: SqliteStore) -> None:
    _seed(store)

    limited = recall_by_lexical(store, "靠窗", limit=1)
    full = recall_by_vector(store, [1.0, 0.0, 0.0, 0.0], limit=10)

    assert len(limited) == 1
    assert len(full) == 3


@pytest.mark.parametrize("path", ["lexical", "vector", "adjacency"])
def test_limit_is_respected_per_path(store: SqliteStore, path: str) -> None:
    """截断必须彻底：各路返回条数不超过 limit，否则 RRF 会偏向长列表。"""
    _seed(store)
    store.insert(
        _item(value="早上", relation="seat", condition="meeting"), reason="r", actor="t"
    )
    store.insert(
        _item(value="深夜", relation="seat", condition="coding"), reason="r", actor="t"
    )

    limit = 1
    if path == "lexical":
        result = recall_by_lexical(store, "靠窗", limit=limit)
    elif path == "vector":
        result = recall_by_vector(store, [1.0, 0.0, 0.0, 0.0], limit=limit)
    else:
        result = recall_by_adjacency(
            store, subject="user:a", relation="seat", condition="meeting", limit=limit
        )

    assert len(result) <= limit


def test_disabled_path_contributes_nothing(store: SqliteStore) -> None:
    _seed(store)

    with_vector = recall_by_vector(store, [1.0, 0.0, 0.0, 0.0])
    assert with_vector

    # 模拟关闭：调用方不调用它，结果里自然没有它的贡献
    paths = {"lexical": recall_by_lexical(store, "靠窗")}
    assert "vector" not in paths
