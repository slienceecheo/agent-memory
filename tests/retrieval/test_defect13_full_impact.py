"""缺陷 13 的完整影响面：同 key 全部丢弃，不只"值不同的"。

**为什么需要这条测试**：缺陷 13 原先记的是"值不同的候选被判重复，丢了 147 条"。
那读起来像一个可量化的偏差——补几条数据就能缓解。

实测更彻底：**gold 自己的 key 就占住了 `seen`，所以同 key 的干扰项一条都进不来**，
无论 value 是否相同。

于是 v2 的池里每个 `(subject, relation, condition)` 最多一条。这不是偏差，
是**池的结构性质**，并带来两个后果：

1. **B 轴在池构造层装不进去**——即使召回层返回历史版本，池里也放不下
   （协议 §2.1 只记了召回层那一层）
2. **"base 分接近"的干扰项无法构造**——它们会被 key 丢掉，
   所以 A 轴的 base 分天然拉得开，满分有结构性原因
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from memory.retrieval.pool import _key, build_pool
from memory.store.models import Authority, MemoryItem, Scope, Source, Status

BASE = datetime(2026, 1, 1, tzinfo=UTC)


def _item(tag: str, *, condition: str | None, value: str) -> MemoryItem:
    return MemoryItem(
        owner="default",
        scope=Scope.PROJECT,
        subject="project:test",
        relation="rel_x",
        value=value,
        condition=condition,
        status=Status.ACTIVE,
        valid_from=BASE,
        valid_to=None,
        recorded_at=BASE,
        authority=Authority.USER_DIRECT,
        source=Source(session_id=tag),
        text=value,
        id=tag,
    )


def test_key_does_not_contain_value() -> None:
    """`_key` 不含 value——这是缺陷 13 的根。"""
    a = _item("a", condition="c1", value="林晓")
    b = _item("b", condition="c1", value="陈昊")

    assert _key(a) == _key(b), "_key 现在含 value 了——缺陷 13 可能已修复"


def test_same_key_distractors_are_all_dropped() -> None:
    """**核心**：同 key 的干扰项**全部**被丢弃，不只是"值不同的"。

    实测 `build_pool(gold, [A, B])` 的池大小是 1——只剩 gold。
    A 与 B 的 value 互不相同且都不同于 gold，但它们仍然全被丢掉。
    """
    gold = _item("gold", condition="c1", value="林晓")
    a = _item("A", condition="c1", value="陈昊")
    b = _item("B", condition="c1", value="周敏")

    pool = build_pool(gold, [a, b], seed=0)
    ids = {i.id for i in pool.items}

    assert len(pool.items) == 1, (
        f"池里有 {len(pool.items)} 条——同 key 未被全部丢弃，缺陷 13 可能已修复"
    )
    assert ids == {"gold"}
    assert "A" not in ids and "B" not in ids


def test_different_condition_distractors_do_enter() -> None:
    """condition 不同的干扰项能进池——这解释了 A 轴为什么"能成立"。

    A 轴的竞争集正是"同 relation 的不同 condition 分支"，它们 key 各不相同。
    """
    gold = _item("gold", condition="c1", value="林晓")
    other = _item("C", condition="c2", value="林晓")

    pool = build_pool(gold, [other], seed=0)
    ids = {i.id for i in pool.items}

    assert len(pool.items) == 2
    assert ids == {"gold", "C"}


def test_pool_has_at_most_one_row_per_logical_key() -> None:
    """池里每个 `(subject, relation, condition)` 最多一条。

    这是"同 key 全部丢弃"的直接推论，也是 B 轴装不进去的原因。
    """
    gold = _item("gold", condition="c1", value="林晓")
    cands = [
        _item("A", condition="c1", value="陈昊"),
        _item("B", condition="c1", value="周敏"),
        _item("C", condition="c2", value="林晓"),
        _item("D", condition="c2", value="赵启"),
        _item("E", condition="c3", value="钱多"),
    ]

    pool = build_pool(gold, cands, seed=0)
    keys = [_key(i) for i in pool.items]

    assert len(keys) == len(set(keys)), f"池里出现重复逻辑键：{keys}"


def test_base_scores_cannot_be_close_by_construction() -> None:
    """**结构性推论**：让 base 分接近需要 value 相近，而同 key 的候选进不来。

    `_embedding_text` = subject + relation + value（不含 condition）。
    所以"同 relation、value 相同"的两条会有几乎相同的 base 分——
    但那要求它们 condition 不同（否则同 key 被丢）。

    而 condition 不同 + value 相同，正是 A 轴能构造的最小 base 差场景。
    这条测试记录这个构造，供 v3 参考。
    """
    gold = _item("gold", condition="c1", value="林晓")
    twin = _item("twin", condition="c2", value="林晓")

    pool = build_pool(gold, [twin], seed=0)

    # 两条都在池里（condition 不同），且 value 相同 -> base 分应当接近
    assert len(pool.items) == 2
    values = {i.value for i in pool.items}
    assert values == {"林晓"}, "value 相同的孪生条目应当能同时进池"


def test_report_records_the_full_impact() -> None:
    """报告必须记录"同 key 全部丢弃"，不能只写"值不同的被丢"。"""
    from pathlib import Path

    report = Path(__file__).resolve().parents[2] / "docs" / "reports" / "c4-retrieval.md"
    if not report.exists():
        pytest.skip("报告缺失")

    text = report.read_text(encoding="utf-8")

    assert "同 key 全部丢弃" in text, "报告未升级缺陷 13 的影响面"
    # B 轴两层阻塞
    assert "两层" in text or "池构造层" in text
    # 结构性后果
    assert "最多一条" in text
