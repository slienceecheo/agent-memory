"""审计只追加的行为契约。

三个触发器缺一不可。少了 `events_no_replace` 这条，`INSERT OR REPLACE`
会绕过 BEFORE DELETE（实测：recursive_triggers=OFF 时覆盖成功）。
审计一旦可被覆盖，"可追溯"就是假的。
"""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from pathlib import Path

import pytest

from memory.store.models import Authority, MemoryItem, Scope, Source, Status
from memory.store.sqlite import SqliteStore

NOW = datetime(2026, 1, 1, tzinfo=UTC)


def _item(value: str = "v") -> MemoryItem:
    return MemoryItem(
        owner="o",
        scope=Scope.PROJECT,
        subject="s",
        relation="r",
        value=value,
        condition=None,
        status=Status.ACTIVE,
        valid_from=NOW,
        valid_to=None,
        recorded_at=NOW,
        authority=Authority.USER_DIRECT,
        source=Source(session_id="s1"),
    )


def _seed_event(store: SqliteStore) -> None:
    store.insert(_item(), reason="initial", actor="tester")


def test_events_can_be_inserted(tmp_path: Path) -> None:
    """前置：正常写入必须成功，否则后面的"被拒绝"毫无意义。"""
    store = SqliteStore(tmp_path / "m.db")
    _seed_event(store)

    assert store.event_count() == 1


def test_update_is_rejected(tmp_path: Path) -> None:
    """若能改 reason，审计的价值就不存在了。"""
    store = SqliteStore(tmp_path / "m.db")
    _seed_event(store)
    conn = sqlite3.connect(str(store.path))

    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        conn.execute("UPDATE events SET reason = 'tampered' WHERE seq = 1")


def test_delete_is_rejected(tmp_path: Path) -> None:
    store = SqliteStore(tmp_path / "m.db")
    _seed_event(store)
    conn = sqlite3.connect(str(store.path))

    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        conn.execute("DELETE FROM events WHERE seq = 1")


def test_insert_or_replace_is_rejected(tmp_path: Path) -> None:
    """这是最隐蔽的一条：REPLACE 的隐式删除不触发 BEFORE DELETE。

    实测：recursive_triggers=OFF 时覆盖成功，值被改写。
    """
    store = SqliteStore(tmp_path / "m.db")
    _seed_event(store)
    conn = sqlite3.connect(str(store.path))
    conn.execute("PRAGMA recursive_triggers = ON")

    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        conn.execute(
            "INSERT OR REPLACE INTO events (seq, item_id, decision, reason, actor, at)"
            " VALUES (1, 'x', 'ADD', 'overwritten', 'attacker',"
            " '2026-01-01T00:00:00.000000+00:00')"
        )


def test_replacement_without_recursive_triggers_would_succeed(tmp_path: Path) -> None:
    """反证：不开 pragma 时同一操作会成功。

    这条测试锁定"为什么必须在连接上开 recursive_triggers"，
    防止有人把它当成无关紧要的性能开关删掉。
    """
    db = tmp_path / "plain.db"
    conn = sqlite3.connect(str(db))
    conn.executescript(
        """
        CREATE TABLE ev (seq INTEGER PRIMARY KEY, txt TEXT);
        CREATE TRIGGER no_del BEFORE DELETE ON ev
        BEGIN SELECT RAISE(ABORT, 'append-only'); END;
        INSERT INTO ev VALUES (1, 'original');
        """
    )
    conn.execute("PRAGMA recursive_triggers = OFF")

    conn.execute("INSERT OR REPLACE INTO ev VALUES (1, 'overwritten')")

    assert conn.execute("SELECT txt FROM ev WHERE seq = 1").fetchone()[0] == "overwritten"


def test_store_connection_has_recursive_triggers_on(tmp_path: Path) -> None:
    store = SqliteStore(tmp_path / "m.db")

    assert store.recursive_triggers_enabled() is True


def test_event_sequence_grows(tmp_path: Path) -> None:
    """seq 必须单调，否则"按时间顺序读审计"会乱。"""
    store = SqliteStore(tmp_path / "m.db")
    _seed_event(store)
    other = _item("v2")
    import dataclasses

    store.insert(dataclasses.replace(other, subject="s2"), reason="second", actor="tester")

    sequences = store.event_sequences()

    assert sequences == sorted(sequences)
    assert len(sequences) == len(set(sequences))
