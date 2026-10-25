"""L6c：三路召回必须真的返回东西，不是只是被调用。

**这条为什么单独存在**：L6a 判"调用了"、L6b 判"有数据"，
两者都对时仍可能一条都没返回：

- 向量维度不符 → 静默跳过全部
- 条件兄弟不存在 → 邻接必然为空
- 检索词全被停用 → 词面为空

此时"跑了"与"没跑"在结果上完全一样。**只有检查返回值能区分。**
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


def _item(*, value: str, text: str | None, condition: str | None = None) -> MemoryItem:
    return MemoryItem(
        owner="o",
        scope=Scope.PROJECT,
        subject="project:ledger",
        relation="oncall_owner",
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


def test_vector_returns_empty_when_item_has_no_embedding(store: SqliteStore) -> None:
    """这是 L6c 要抓的核心形态：调用了、条目在、却返回空。

    L6b 修好（池内写向量）之前，实测 `embedding=` 在评测入口出现 0 次，
    所以向量一路必然走到这里——返回空列表，看起来"跑过了"。

    注意用**不同 condition** 区分两条：`ux_active` 唯一索引是
    `(owner, scope, subject, relation, IFNULL(condition,''))`，
    同键两条 ACTIVE 会直接撞 `ActiveExists`——这正是协议 §2.1 阻塞一的实体。
    """
    store.insert(
        _item(value="林晓", text="半夜出问题找林晓", condition="夜间"), reason="r", actor="t"
    )

    assert recall_by_vector(store, [1.0, 0.0, 0.0, 0.0]) == []

    # 同一批数据，写入向量后就有结果——差异只在"有没有向量"。
    store.insert(
        _item(value="周敏", text="周末找周敏", condition="周末"),
        reason="r",
        actor="t",
        embedding=[1.0, 0.0, 0.0, 0.0],
    )

    assert len(recall_by_vector(store, [1.0, 0.0, 0.0, 0.0])) == 1


def test_adjacency_returns_empty_without_sibling(store: SqliteStore) -> None:
    """没有条件兄弟时邻接必然为空——"跑了"与"没跑"结果相同。"""
    store.insert(
        _item(value="陈昊", text="白天找陈昊", condition="工作日白天"),
        reason="r",
        actor="t",
    )

    hits = recall_by_adjacency(
        store, subject="project:ledger", relation="oncall_owner", condition="工作日白天"
    )

    assert hits == []


def test_lexical_returns_empty_on_stopword_only_query(store: SqliteStore) -> None:
    store.insert(_item(value="陈昊", text="白天找陈昊"), reason="r", actor="t")

    assert recall_by_lexical(store, "   ") == []


def test_three_paths_can_all_be_nonempty_on_the_same_store(store: SqliteStore) -> None:
    """三路同时非空是可能的——这才是 L6c 想要的终态。

    给出反例的目的是：让"必然为空"与"本可以非空"在同一份测试里对照，
    避免把结构性空转误读成"数据就是这样"。
    """
    store.insert(
        _item(value="林晓", text="半夜出问题找林晓", condition="夜间"),
        reason="r",
        actor="t",
        embedding=[1.0, 0.0, 0.0, 0.0],
    )
    store.insert(
        _item(value="周敏", text="周末找周敏", condition="周末"),
        reason="r",
        actor="t",
        embedding=[0.9, 0.1, 0.0, 0.0],
    )

    lexical = recall_by_lexical(store, "半夜")
    vector = recall_by_vector(store, [1.0, 0.0, 0.0, 0.0])
    adjacency = recall_by_adjacency(
        store, subject="project:ledger", relation="oncall_owner", condition="周末"
    )

    assert len(lexical) >= 1
    assert len(vector) == 2
    assert len(adjacency) == 1
