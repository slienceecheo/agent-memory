"""三路召回的行为契约。

三路各自独立，且都能被单独关闭——否则无法测量各自的贡献。

**词面必须按相关性排序且索引原文**（C4 阶段一已修好），
**向量必须跳过无向量的条目而不是崩溃**，
**邻接只做条件兄弟**（跨关系那条路永远召不回 gold，审查已证）。
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
    authority: Authority = Authority.USER_DIRECT,
    valid_from: datetime | None = None,
) -> MemoryItem:
    return MemoryItem(
        owner="o",
        scope=Scope.PROJECT,
        subject=subject,
        relation=relation,
        value=value,
        condition=condition,
        status=Status.ACTIVE,
        valid_from=valid_from or NOW,
        valid_to=None,
        recorded_at=NOW,
        authority=authority,
        source=Source(session_id="s1"),
        text=text,
    )


@pytest.fixture
def store(tmp_path: Path) -> SqliteStore:
    instance = SqliteStore(tmp_path / "m.db", embedding_dims=4)
    yield instance
    instance.close()


# ---------- 词面 ----------


def test_lexical_returns_active_only(store: SqliteStore) -> None:
    first = store.insert(_item(value="pnpm", text="用 pnpm"), reason="r", actor="t")
    store.supersede(
        first.id,
        _item(value="npm", text="改用 npm", valid_from=NOW.replace(day=2)),
        reason="c",
        actor="t",
    )

    hits = recall_by_lexical(store, "pnpm")

    assert hits == []


def test_lexical_finds_by_source_text(store: SqliteStore) -> None:
    store.insert(
        _item(value="C区第三排", text="就是靠窗那一排"), reason="r", actor="t"
    )

    hits = recall_by_lexical(store, "靠窗")

    assert len(hits) == 1


def test_lexical_respects_limit(store: SqliteStore) -> None:
    for index in range(5):
        store.insert(
            _item(value=f"pnpm-{index}", subject=f"user:{index}", text=f"pnpm {index}"),
            reason="r",
            actor="t",
        )

    hits = recall_by_lexical(store, "pnpm", limit=3)

    assert len(hits) == 3


def test_lexical_empty_query_returns_empty(store: SqliteStore) -> None:
    store.insert(_item(value="pnpm", text="用 pnpm"), reason="r", actor="t")

    assert recall_by_lexical(store, "   ") == []


# ---------- 向量 ----------


def test_vector_orders_by_cosine(store: SqliteStore) -> None:
    store.insert(_item(value="近", text="x"), reason="r", actor="t", embedding=[1.0, 0.0, 0.0, 0.0])
    store.insert(
        _item(value="远", subject="user:b", text="y"),
        reason="r",
        actor="t",
        embedding=[0.0, 1.0, 0.0, 0.0],
    )

    hits = recall_by_vector(store, [1.0, 0.0, 0.0, 0.0], limit=5)

    assert [item.value for item in hits] == ["近", "远"]


def test_vector_skips_items_without_embedding(store: SqliteStore) -> None:
    store.insert(_item(value="无向量", text="x"), reason="r", actor="t")
    store.insert(
        _item(value="有向量", subject="user:b", text="y"),
        reason="r",
        actor="t",
        embedding=[1.0, 0.0, 0.0, 0.0],
    )

    hits = recall_by_vector(store, [1.0, 0.0, 0.0, 0.0])

    assert [item.value for item in hits] == ["有向量"]


def test_vector_rejects_wrong_query_dims(store: SqliteStore) -> None:
    """查询向量维度与库声明不一致时报错，而不是静默算错。

    审查指出：静默跳过会掩盖损坏的 vec_items 行。
    """
    store.insert(
        _item(value="a", text="x"), reason="r", actor="t", embedding=[1.0, 0.0, 0.0, 0.0]
    )

    with pytest.raises(ValueError, match="维度"):
        recall_by_vector(store, [1.0, 0.0])


def test_vector_empty_store_returns_empty(store: SqliteStore) -> None:
    assert recall_by_vector(store, [1.0, 0.0, 0.0, 0.0]) == []


def test_vector_excludes_inactive(store: SqliteStore) -> None:
    first = store.insert(
        _item(value="old", text="x"), reason="r", actor="t", embedding=[1.0, 0.0, 0.0, 0.0]
    )
    store.supersede(
        first.id,
        _item(value="new", text="y", valid_from=NOW.replace(day=2)),
        reason="c",
        actor="t",
        embedding=[1.0, 0.0, 0.0, 0.0],
    )

    hits = recall_by_vector(store, [1.0, 0.0, 0.0, 0.0])

    assert [item.value for item in hits] == ["new"]


# ---------- 邻接 ----------


def test_adjacency_returns_sibling_conditions(store: SqliteStore) -> None:
    """BRANCH 场景的 gold 只能靠这条路径召回。"""
    store.insert(
        _item(value="早上", relation="meeting_time", condition="meeting"),
        reason="r",
        actor="t",
    )
    store.insert(
        _item(value="深夜", relation="meeting_time", condition="coding"),
        reason="r",
        actor="t",
    )

    hits = recall_by_adjacency(
        store, subject="user:a", relation="meeting_time", condition="meeting"
    )

    assert [item.value for item in hits] == ["深夜"]


def test_adjacency_excludes_the_matched_item(store: SqliteStore) -> None:
    store.insert(
        _item(value="早上", relation="meeting_time", condition="meeting"),
        reason="r",
        actor="t",
    )

    hits = recall_by_adjacency(
        store, subject="user:a", relation="meeting_time", condition="meeting"
    )

    assert hits == []


def test_adjacency_does_not_cross_subjects(store: SqliteStore) -> None:
    store.insert(
        _item(value="甲", relation="meeting_time", condition="meeting"),
        reason="r",
        actor="t",
    )
    store.insert(
        _item(value="乙", subject="user:b", relation="meeting_time", condition="coding"),
        reason="r",
        actor="t",
    )

    hits = recall_by_adjacency(
        store, subject="user:a", relation="meeting_time", condition="meeting"
    )

    assert hits == []


def test_adjacency_does_not_cross_relations(store: SqliteStore) -> None:
    """跨关系那条路永远召不回 gold（审查已证），所以不做。"""
    store.insert(
        _item(value="甲", relation="meeting_time", condition="meeting"),
        reason="r",
        actor="t",
    )
    store.insert(
        _item(value="乙", relation="lunch_habit", condition="coding"),
        reason="r",
        actor="t",
    )

    hits = recall_by_adjacency(
        store, subject="user:a", relation="meeting_time", condition="meeting"
    )

    assert hits == []


def test_adjacency_includes_unconditional_sibling(store: SqliteStore) -> None:
    """无条件版本也是兄弟：条件分支与无条件可以并存。"""
    store.insert(
        _item(value="早上", relation="meeting_time", condition=None), reason="r", actor="t"
    )
    store.insert(
        _item(value="深夜", relation="meeting_time", condition="coding"),
        reason="r",
        actor="t",
    )

    hits = recall_by_adjacency(
        store, subject="user:a", relation="meeting_time", condition="coding"
    )

    assert [item.value for item in hits] == ["早上"]
