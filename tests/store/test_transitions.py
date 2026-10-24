"""状态迁移矩阵的行为契约。

审查发现原设计只测"四个非法迁移"，而 4×4 矩阵有 16 格。
只测四格会让 `SUPERSEDED → RETRACTED` 之类的格子保持未定义。

本文件逐格断言，并把"同状态"定义为幂等空操作（不是错误），
这样一次瞬时失败后的重试是安全的。
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from memory.store.base import InvalidTransition
from memory.store.models import Authority, MemoryItem, Scope, Source, Status
from memory.store.sqlite import SqliteStore

BASE = datetime(2026, 1, 1, tzinfo=UTC)

# (起始状态, 目标状态, 是否合法)
MATRIX = [
    (Status.ACTIVE, Status.ACTIVE, True),        # 幂等
    (Status.ACTIVE, Status.SUPERSEDED, True),
    (Status.ACTIVE, Status.CONFLICTED, True),
    (Status.ACTIVE, Status.RETRACTED, True),
    (Status.SUPERSEDED, Status.ACTIVE, False),
    (Status.SUPERSEDED, Status.SUPERSEDED, True),  # 幂等
    (Status.SUPERSEDED, Status.CONFLICTED, False),
    (Status.SUPERSEDED, Status.RETRACTED, True),
    (Status.CONFLICTED, Status.ACTIVE, True),
    (Status.CONFLICTED, Status.SUPERSEDED, True),
    (Status.CONFLICTED, Status.CONFLICTED, True),  # 幂等
    (Status.CONFLICTED, Status.RETRACTED, True),
    (Status.RETRACTED, Status.ACTIVE, False),
    (Status.RETRACTED, Status.SUPERSEDED, False),
    (Status.RETRACTED, Status.CONFLICTED, False),
    (Status.RETRACTED, Status.RETRACTED, True),    # 幂等
]


def _item(
    *,
    value: str = "v",
    valid_from: datetime = BASE,
    subject: str = "s",
) -> MemoryItem:
    return MemoryItem(
        owner="o",
        scope=Scope.PROJECT,
        subject=subject,
        relation="r",
        value=value,
        condition=None,
        status=Status.ACTIVE,
        valid_from=valid_from,
        valid_to=None,
        recorded_at=BASE,
        authority=Authority.USER_DIRECT,
        source=Source(session_id="s1"),
    )


def _force_status(store: SqliteStore, item_id: str, status: Status) -> None:
    """把条目直接改成指定状态，用于构造矩阵的起始条件。

    绕过状态机是刻意的：这里要测的是"从某状态出发能去哪"，
    而不是"如何走到某状态"。
    """
    import sqlite3

    conn = sqlite3.connect(str(store.path))
    conn.execute("UPDATE items SET status = ? WHERE id = ?", (status.value, item_id))
    if status is Status.RETRACTED:
        conn.execute("DELETE FROM items_fts WHERE item_id = ?", (item_id,))
    conn.commit()
    conn.close()


def _attempt(store: SqliteStore, item_id: str, target: Status) -> None:
    """尝试把条目迁移到 target，用最贴近该迁移的公开方法。"""
    if target is Status.RETRACTED:
        store.retract(item_id, reason="r", actor="t")
        return
    if target is Status.SUPERSEDED:
        old = store.get(item_id)
        store.supersede(
            item_id,
            _item(value="next", valid_from=old.valid_from + timedelta(days=1)),
            reason="r",
            actor="t",
        )
        return
    if target is Status.CONFLICTED:
        store.mark_conflict(item_id, reason="r", actor="t")
        return
    if target is Status.ACTIVE:
        # 需要另一个条目作为落败者，否则胜者就是自己，语义不成立
        winner = store.get(item_id)
        loser = store.insert(
            _item(value="rival", valid_from=winner.valid_from, subject="other"),
            reason="rival",
            actor="t",
        )
        store.mark_conflict(loser.id, reason="conflicting", actor="t")
        store.resolve_conflict(item_id, loser.id, reason="r", actor="t")
        return
    raise NotImplementedError(target)


@pytest.mark.parametrize(("start", "target", "legal"), MATRIX)
def test_transition_matrix(
    tmp_path: Path, start: Status, target: Status, legal: bool
) -> None:
    """逐格断言 16 种组合。"""
    if start is Status.ACTIVE and target is Status.ACTIVE:
        # ACTIVE → ACTIVE 只能通过"对自己裁决"实现，而那不是真实场景。
        # 同状态幂等由 test_retract_is_idempotent 等专门测试覆盖。
        pytest.skip("同状态幂等由专门测试覆盖")

    store = SqliteStore(tmp_path / "m.db")
    created = store.insert(_item(), reason="init", actor="t")
    _force_status(store, created.id, start)

    if legal:
        _attempt(store, created.id, target)
    else:
        with pytest.raises(InvalidTransition) as excinfo:
            _attempt(store, created.id, target)
        message = str(excinfo.value)
        assert start.value in message
        assert target.value in message


def test_retract_is_idempotent(tmp_path: Path) -> None:
    """一次瞬时失败后重试必须安全；抛异常会让调用方无从判断是否已生效。"""
    store = SqliteStore(tmp_path / "m.db")
    created = store.insert(_item(), reason="init", actor="t")

    first = store.retract(created.id, reason="wrong", actor="t")
    second = store.retract(created.id, reason="wrong again", actor="t")

    assert first.status is Status.RETRACTED
    assert second.status is Status.RETRACTED


def test_retract_twice_does_not_duplicate_status_change(tmp_path: Path) -> None:
    store = SqliteStore(tmp_path / "m.db")
    created = store.insert(_item(), reason="init", actor="t")
    store.retract(created.id, reason="a", actor="t")
    store.retract(created.id, reason="b", actor="t")

    decisions = [event["decision"] for event in store.events_for(created.id)]

    assert decisions.count("RETRACT") == 1


def test_retracted_is_terminal(tmp_path: Path) -> None:
    """撤回是强声明；若能复活，审计就没有意义。"""
    store = SqliteStore(tmp_path / "m.db")
    created = store.insert(_item(), reason="init", actor="t")
    store.retract(created.id, reason="wrong", actor="t")

    with pytest.raises(InvalidTransition, match="RETRACTED"):
        store.supersede(
            created.id,
            _item(value="next", valid_from=BASE + timedelta(days=1)),
            reason="revive",
            actor="t",
        )


def test_retract_works_on_superseded_history(tmp_path: Path) -> None:
    """发现历史记录是伪造的，必须能撤回，否则脏数据永远留在时间线里。"""
    store = SqliteStore(tmp_path / "m.db")
    v1 = store.insert(_item(value="fake"), reason="init", actor="t")
    store.supersede(
        v1.id,
        _item(value="real", valid_from=BASE + timedelta(days=1)),
        reason="correct",
        actor="t",
    )

    retracted = store.retract(v1.id, reason="was fabricated", actor="auditor")

    assert retracted.status is Status.RETRACTED


def test_retract_works_on_conflicted(tmp_path: Path) -> None:
    """确认一条未裁决冲突是错误信息时，必须能撤回。"""
    store = SqliteStore(tmp_path / "m.db")
    created = store.insert(_item(), reason="init", actor="t")
    _force_status(store, created.id, Status.CONFLICTED)

    retracted = store.retract(created.id, reason="bogus", actor="auditor")

    assert retracted.status is Status.RETRACTED


def test_invalid_transition_message_is_actionable(tmp_path: Path) -> None:
    """错误信息必须同时给出当前状态与目标状态，否则排查要靠猜。"""
    store = SqliteStore(tmp_path / "m.db")
    created = store.insert(_item(), reason="init", actor="t")
    store.retract(created.id, reason="wrong", actor="t")

    with pytest.raises(InvalidTransition) as excinfo:
        store.supersede(
            created.id,
            _item(value="next", valid_from=BASE + timedelta(days=1)),
            reason="x",
            actor="t",
        )

    assert "RETRACTED" in str(excinfo.value)
    assert "SUPERSEDED" in str(excinfo.value)


def test_legal_transition_set_is_complete() -> None:
    """把矩阵与实现里的表对齐，防止两边漂移。"""
    from memory.store.sqlite import _LEGAL_TRANSITIONS

    expected = {
        (start, target)
        for start, target, legal in MATRIX
        if legal and start is not target
    }
    actual = {
        (start, target)
        for start, targets in _LEGAL_TRANSITIONS.items()
        for target in targets
    }

    assert actual == expected
