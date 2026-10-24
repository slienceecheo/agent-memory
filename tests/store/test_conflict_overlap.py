"""CONFLICTED 条目与区间重叠的关系。

这是一条在 C3 才暴露出来的设计缺口：冲突候选与既有有效值**必然**时间重叠
——它按定义就是"同一时段的另一种说法"。

若重叠检测把 CONFLICTED 也算进去，合法的冲突场景会被拒绝，
`ConflictResolver` 的 CONFLICT 类别根本无法落库。

同时要保证：CONFLICTED 与 RETRACTED 的排除**不放宽 ACTIVE 之间的约束**。
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from memory.store.models import Authority, MemoryItem, Scope, Source, Status
from memory.store.sqlite import SqliteStore

BASE = datetime(2026, 1, 1, tzinfo=UTC)


def _item(
    *,
    value: str,
    status: Status = Status.ACTIVE,
    valid_from: datetime = BASE,
    valid_to: datetime | None = None,
) -> MemoryItem:
    return MemoryItem(
        owner="o",
        scope=Scope.PROJECT,
        subject="s",
        relation="r",
        value=value,
        condition=None,
        status=status,
        valid_from=valid_from,
        valid_to=valid_to,
        recorded_at=BASE,
        authority=Authority.USER_DIRECT,
        source=Source(session_id="s1"),
    )


def test_conflicted_can_overlap_active(tmp_path: Path) -> None:
    """冲突候选与既有有效值时间重叠是它的定义特征，不能被拒。"""
    store = SqliteStore(tmp_path / "m.db")
    store.insert(_item(value="对花生过敏"), reason="init", actor="t")

    stored = store.insert_conflicted(
        _item(value="喜欢花生酱"), reason="矛盾陈述", actor="t"
    )

    assert stored.status is Status.CONFLICTED
    assert store.count() == 2


def test_conflicted_does_not_become_current_value(tmp_path: Path) -> None:
    """冲突未裁决时"当前值"仍是既有那条。"""
    store = SqliteStore(tmp_path / "m.db")
    store.insert(_item(value="对花生过敏"), reason="init", actor="t")
    store.insert_conflicted(_item(value="喜欢花生酱"), reason="矛盾", actor="t")

    current = store.active_at(
        owner="o",
        scope=Scope.PROJECT,
        subject="s",
        relation="r",
        condition=None,
        at=BASE + timedelta(days=1),
    )

    assert current is not None
    assert current.value == "对花生过敏"


def test_two_conflicted_can_coexist(tmp_path: Path) -> None:
    """同一键可能有多个互相矛盾的候选，它们彼此也不该被判为重叠。"""
    store = SqliteStore(tmp_path / "m.db")
    store.insert(_item(value="原值"), reason="init", actor="t")
    store.insert_conflicted(_item(value="说法甲"), reason="a", actor="t")
    store.insert_conflicted(_item(value="说法乙"), reason="b", actor="t")

    assert store.count() == 3


def test_active_still_cannot_overlap_active(tmp_path: Path) -> None:
    """放宽 CONFLICTED 不能顺带放宽 ACTIVE 之间的约束。"""
    from memory.store.base import ActiveExists

    store = SqliteStore(tmp_path / "m.db")
    store.insert(_item(value="a"), reason="1", actor="t")

    with pytest.raises(ActiveExists):
        store.insert(_item(value="b"), reason="2", actor="t")


def test_conflicted_still_respects_unique_per_key_when_resolved(
    tmp_path: Path,
) -> None:
    """裁决之后仍只能有一条 ACTIVE。"""
    store = SqliteStore(tmp_path / "m.db")
    old = store.insert(_item(value="原值"), reason="init", actor="t")
    rival = store.insert_conflicted(_item(value="新说法"), reason="conflict", actor="t")

    winner, loser = store.resolve_conflict(
        rival.id, old.id, reason="新说法更可信", actor="judge"
    )

    assert winner.status is Status.ACTIVE
    assert loser.status is Status.SUPERSEDED
    current = store.active_at(
        owner="o",
        scope=Scope.PROJECT,
        subject="s",
        relation="r",
        condition=None,
        at=BASE + timedelta(days=1),
    )
    assert current is not None
    assert current.value == "新说法"


def test_retracted_can_overlap_anything(tmp_path: Path) -> None:
    """撤回的条目已作废，不占用时间段。"""
    store = SqliteStore(tmp_path / "m.db")
    first = store.insert(_item(value="错值"), reason="init", actor="t")
    store.retract(first.id, reason="wrong", actor="t")

    store.insert(_item(value="正确值"), reason="fix", actor="t")

    assert store.count() == 2
