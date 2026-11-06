"""commit ② 的测试：向量召回必须同时带出余弦分。

对应 tasks 3.1 / 3.2 / 3.5 / 3.6 / 3.8 / 3.10。

**为什么必须带出而不是重排时重算**：`AGENTS.md` 登记了 embedding 非确定性
（未命中缓存时 `cos = 0.9971`，跨变体 0.9976）。重算会引入第二次调用，
于是"排序用的 cosine"与"记录的 cosine"是两个数，而差异只在缓存未命中时出现
——正是最难归因的形态。
"""

from __future__ import annotations

from datetime import UTC, datetime

import numpy as np
import pytest

from memory.retrieval.vector import recall_by_vector, recall_by_vector_scored
from memory.store.models import (
    Authority,
    MemoryItem,
    Scope,
    Source,
    Status,
)

NOW = datetime(2026, 1, 1, tzinfo=UTC)


def _item(item_id: str, text: str) -> MemoryItem:
    return MemoryItem(
        owner="default",
        scope=Scope.PROJECT,
        subject=item_id,  # 逻辑键必须不同，否则 store 会拒绝（ActiveExists）
        relation="r",
        condition=None,
        value=text,
        status=Status.ACTIVE,
        valid_from=NOW,
        valid_to=None,
        recorded_at=NOW,
        authority=Authority.USER_DIRECT,
        source=Source(session_id="s1"),
        text=text,
    )


@pytest.fixture()
def store(tmp_path):
    from memory.store.sqlite import SqliteStore

    s = SqliteStore(tmp_path / "t.db", embedding_dims=4)
    # 三个向量，与查询 [1,0,0,0] 的余弦分别是 1.0、0.6、0.0
    vecs = {
        "a": [1.0, 0.0, 0.0, 0.0],
        "b": [0.6, 0.8, 0.0, 0.0],
        "c": [0.0, 1.0, 0.0, 0.0],
    }
    for item_id, vec in vecs.items():
        s.insert(_item(item_id, item_id), reason="t", actor="t", embedding=vec)
    yield s
    s.close()


def test_scored_variant_matches_plain_order(store) -> None:
    """带分数的版本与旧版的**顺序**必须一致——它们是同一次计算。"""
    plain = [i.id for i in recall_by_vector(store, [1.0, 0.0, 0.0, 0.0])]
    scored = [
        i.id for i, _ in recall_by_vector_scored(store, [1.0, 0.0, 0.0, 0.0])
    ]

    assert plain == scored, f"顺序不同：plain={plain} scored={scored}"


def test_scored_values_are_the_cosine(store) -> None:
    """分数必须等于手工算的余弦，**逐位相等**（不是 approx）。

    逐位是因为：这个数会被写进产物、用来复算名次。
    允许 1e-9 的误差就可以让"复算名次"在边界上翻转。

    **用 `subject` 匹配而不是 `id`**：`store.insert` 会分配 uuid4，
    构造时给的 `item_id` 不会成为 id。
    """
    query = np.asarray([1.0, 0.0, 0.0, 0.0], dtype=np.float32)
    qn = float(np.linalg.norm(query))

    got = {
        item.subject: score
        for item, score in recall_by_vector_scored(store, [1.0, 0.0, 0.0, 0.0])
    }

    expected = {}
    for item_id, raw in {
        "a": [1.0, 0.0, 0.0, 0.0],
        "b": [0.6, 0.8, 0.0, 0.0],
        "c": [0.0, 1.0, 0.0, 0.0],
    }.items():
        v = np.asarray(raw, dtype=np.float32)
        expected[item_id] = float(np.dot(query, v) / (qn * float(np.linalg.norm(v))))

    for item_id, want in expected.items():
        assert got[item_id] == want, (
            f"{item_id}: 得到 {got[item_id]!r}，手算 {want!r}。"
            "两者必须逐位相等——否则复算名次会在边界上翻转。"
        )


def test_limit_applies_to_both(store) -> None:
    """limit 对两个版本都生效。"""
    assert len(recall_by_vector(store, [1.0, 0.0, 0.0, 0.0], limit=2)) == 2
    assert len(recall_by_vector_scored(store, [1.0, 0.0, 0.0, 0.0], limit=2)) == 2


def test_zero_vector_returns_empty_for_both(store) -> None:
    """零向量必须返回空，两个版本一致。"""
    assert recall_by_vector(store, [0.0, 0.0, 0.0, 0.0]) == []
    assert recall_by_vector_scored(store, [0.0, 0.0, 0.0, 0.0]) == []


def test_dimension_mismatch_raises_for_both(store) -> None:
    """维度不符必须报错（静默算错会更糟）。"""
    with pytest.raises(ValueError, match="维度"):
        recall_by_vector(store, [1.0, 0.0])
    with pytest.raises(ValueError, match="维度"):
        recall_by_vector_scored(store, [1.0, 0.0])
