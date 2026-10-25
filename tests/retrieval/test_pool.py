"""候选池构建的行为契约。

**为什么必须有池**：设计审查实测，此前每条场景只建 1 条既有条目，
排名恒为 1、SRS 恒为 1.0、SEH@5 等于"唯一那条回来了吗"。
没有池就没有排名，没有排名就没有检索指标。

**为什么干扰项键必须互不相同**：审查实测跨文件合并场景会产生 17 个重复键
（`project:agent-memory/package_manager` 出现 12 次），直接建库必撞 `ux_active`。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from memory.retrieval.pool import (
    PoolTooSmall,
    build_pool,
)
from memory.store.models import Authority, MemoryItem, Scope, Source, Status


def _item(
    *,
    subject: str,
    relation: str,
    value: str,
    condition: str | None = None,
    authority: Authority = Authority.USER_DIRECT,
    item_id: str = "",
) -> MemoryItem:
    from datetime import UTC, datetime

    now = datetime(2026, 1, 1, tzinfo=UTC)
    return MemoryItem(
        owner="o",
        scope=Scope.PROJECT,
        subject=subject,
        relation=relation,
        value=value,
        condition=condition,
        status=Status.ACTIVE,
        valid_from=now,
        valid_to=None,
        recorded_at=now,
        authority=authority,
        source=Source(session_id="s1"),
        id=item_id,
    )


def _gold() -> MemoryItem:
    return _item(subject="user:a", relation="seat", value="靠窗那一排", item_id="gold")


def _distractors(count: int) -> list[MemoryItem]:
    return [
        _item(subject=f"user:d{i}", relation="note", value=f"干扰{i}", item_id=f"d{i}")
        for i in range(count)
    ]


def test_pool_size_reflects_available_distractors(tmp_path: Path) -> None:
    """池大小受可用干扰项数量限制，这是数据约束而非缺陷。

    实测：全部三个场景文件合计只有 76 条 gold，扣掉与 gold 同键的之后，
    实际池大小落在 13~15。对 K=5 仍然有效（池 > K），但排名空间比
    理想的 21 小。这个数字必须报出来，不能假装池是 21。
    """
    pool = build_pool(_gold(), _distractors(5))

    assert len(pool.items) == 6


def test_gold_rank_varies_across_different_gold_ids() -> None:
    """不同 gold 的位次必须不同——否则等于没有排名空间。

    这条锁住一个真实缺陷：最初只用固定 seed 打乱，相同长度的池会得到
    相同的排列，gold 位次恒定。
    """
    ranks = set()
    for index in range(8):
        from datetime import UTC, datetime

        from memory.store.models import Authority, Scope, Source, Status

        now = datetime(2026, 1, 1, tzinfo=UTC)
        gold = MemoryItem(
            owner="o",
            scope=Scope.PROJECT,
            subject="user:a",
            relation="seat",
            value="靠窗那一排",
            condition=None,
            status=Status.ACTIVE,
            valid_from=now,
            valid_to=None,
            recorded_at=now,
            authority=Authority.USER_DIRECT,
            source=Source(session_id="s1"),
            id=f"gold-{index}",
        )
        pool = build_pool(gold, _distractors(10), seed=0)
        ranks.add(pool.gold_rank)

    assert len(ranks) > 1, f"gold 位次恒为 {ranks}，打乱失效"


def test_gold_is_in_pool() -> None:
    pool = build_pool(_gold(), _distractors(20))

    assert any(item.id == "gold" for item in pool.items)


def test_gold_position_varies() -> None:
    """gold 不能恒在同一位置，否则排名没有意义。"""
    positions = set()
    for count in (3, 7, 11, 20):
        pool = build_pool(_gold(), _distractors(count))
        positions.add(pool.gold_rank)
    assert len(positions) > 1


def test_distractor_keys_are_unique() -> None:
    """键重复会让建库直接撞 ux_active。"""
    pool = build_pool(_gold(), _distractors(20))
    keys = [(i.subject, i.relation, i.condition) for i in pool.items]

    assert len(keys) == len(set(keys))


def test_duplicate_distractors_are_dropped() -> None:
    """重复的干扰项被去重而不是报错——数据里确实会有重复键。"""
    repeated = [
        _item(subject="user:x", relation="note", value="a", item_id="d1"),
        _item(subject="user:x", relation="note", value="b", item_id="d2"),
    ]

    pool = build_pool(_gold(), repeated)

    assert len(pool.items) == 2


def test_distractor_sharing_gold_key_is_dropped() -> None:
    """与 gold 同键的干扰项会撞唯一索引，必须排除。"""
    clash = [_item(subject="user:a", relation="seat", value="别的值", item_id="clash")]

    pool = build_pool(_gold(), clash)

    assert [i.id for i in pool.items] == ["gold"]


def test_pool_smaller_than_k_raises() -> None:
    """池大小 ≤ K 时 SEH 恒为 1，必须报错而不是给出虚高值。"""
    pool = build_pool(_gold(), _distractors(2))

    with pytest.raises(PoolTooSmall):
        pool.validate_for_k(5)


def test_pool_equal_to_k_raises() -> None:
    pool = build_pool(_gold(), _distractors(4))

    with pytest.raises(PoolTooSmall):
        pool.validate_for_k(5)


def test_pool_larger_than_k_is_accepted() -> None:
    pool = build_pool(_gold(), _distractors(20))

    pool.validate_for_k(5)


def test_gold_rank_is_one_based() -> None:
    pool = build_pool(_gold(), _distractors(3))

    assert 1 <= pool.gold_rank <= 4


def test_empty_distractors_gives_pool_of_one() -> None:
    pool = build_pool(_gold(), [])

    assert len(pool.items) == 1
    assert pool.gold_rank == 1


def test_pool_is_deterministic() -> None:
    """同一输入两次构建结果相同，否则实验不可复现。"""
    first = build_pool(_gold(), _distractors(20), seed=7)
    second = build_pool(_gold(), _distractors(20), seed=7)

    assert [i.id for i in first.items] == [i.id for i in second.items]


def test_different_seed_changes_order() -> None:
    first = build_pool(_gold(), _distractors(20), seed=1)
    second = build_pool(_gold(), _distractors(20), seed=2)

    assert [i.id for i in first.items] != [i.id for i in second.items]


def test_to_store_items_are_valid(tmp_path: Path) -> None:
    """池必须能真的写进 SqliteStore 而不撞约束。"""
    import dataclasses

    from memory.store.sqlite import SqliteStore

    pool = build_pool(_gold(), _distractors(20))
    store = SqliteStore(tmp_path / "m.db")

    for index, item in enumerate(pool.items):
        store.insert(
            dataclasses.replace(item, id=""),
            reason=f"pool-{index}",
            actor="tester",
        )

    assert store.count() == len(pool.items)
