"""候选池难度模式的行为契约。

**核心问题**：SEH@5 = 1.000 若来自"干扰项毫不相干"，那它测的是
"能不能在一片噪声里找到唯一相关的条目"，而不是"能不能在同主题的
多条记忆里挑对"。

三种模式必须分开报告，否则分数会被误读。
"""

from __future__ import annotations

from datetime import UTC, datetime

from memory.retrieval.pool_modes import PoolMode, describe_modes, select_distractors
from memory.store.models import Authority, MemoryItem, Scope, Source, Status

NOW = datetime(2026, 1, 1, tzinfo=UTC)


def _item(*, subject: str, relation: str, value: str) -> MemoryItem:
    return MemoryItem(
        owner="o",
        scope=Scope.PROJECT,
        subject=subject,
        relation=relation,
        value=value,
        condition=None,
        status=Status.ACTIVE,
        valid_from=NOW,
        valid_to=None,
        recorded_at=NOW,
        authority=Authority.USER_DIRECT,
        source=Source(session_id="s1"),
    )


def _corpus() -> tuple[MemoryItem, list[MemoryItem]]:
    gold = _item(subject="user:a", relation="seat", value="靠窗那一排")
    candidates = [
        _item(subject="user:b", relation="seat", value="靠门那一排"),      # 同 relation
        _item(subject="user:c", relation="seat", value="靠窗第三个"),      # 同 relation + 重叠
        _item(subject="user:d", relation="phone", value="13812345678"),    # 无关主题
    ]
    return gold, candidates


def test_unrelated_takes_any() -> None:
    gold, candidates = _corpus()

    picked = select_distractors(gold, candidates, mode=PoolMode.UNRELATED, limit=3)

    assert len(picked) == 3


def test_same_relation_filters_by_relation() -> None:
    gold, candidates = _corpus()

    picked = select_distractors(gold, candidates, mode=PoolMode.SAME_RELATION, limit=10)

    assert all(item.relation == "seat" for item in picked)
    assert len(picked) == 2


def test_adversarial_requires_overlap() -> None:
    """只保留与 gold 有字符重叠的同 relation 候选。

    `"靠门那一排"` 与 `"靠窗那一排"` 共享"靠/那/一/排"，也算重叠——
    这正是 adversarial 模式的意图：这些候选字面上很像，但答案不同。
    """
    gold, candidates = _corpus()

    picked = select_distractors(gold, candidates, mode=PoolMode.ADVERSARIAL, limit=10)

    assert len(picked) == 2
    assert all(item.relation == "seat" for item in picked)
    assert all(set(item.value) & set(gold.value) for item in picked)


def test_adversarial_is_smaller_or_equal_than_same_relation() -> None:
    """更严格的条件只能选出更少的候选。"""
    gold, candidates = _corpus()

    same = select_distractors(gold, candidates, mode=PoolMode.SAME_RELATION, limit=10)
    adversarial = select_distractors(gold, candidates, mode=PoolMode.ADVERSARIAL, limit=10)

    assert len(adversarial) <= len(same)


def test_limit_is_respected() -> None:
    gold, candidates = _corpus()

    picked = select_distractors(gold, candidates, mode=PoolMode.UNRELATED, limit=1)

    assert len(picked) == 1


def test_all_modes_are_described() -> None:
    """报告要能列出三种模式的含义，避免读者把分数跨模式比较。"""
    descriptions = describe_modes()

    for mode in PoolMode:
        assert mode.value in descriptions
        assert descriptions[mode.value]
