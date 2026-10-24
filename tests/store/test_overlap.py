"""有效区间重叠的行为契约。

区间重叠是最隐蔽的一类错误：写入时看起来都成功，查询时才一次性暴露
——`active_at` 返回两条，而调用方通常取第一条。

**两层防护**：
1. `insert` 发现同键已有 ACTIVE → `ActiveExists`（应用层，语义更友好）
2. 数据库触发器拒绝任何未撤回条目之间的区间重叠（存储层，兜底）

第 2 层主要保护"非 ACTIVE 的历史区间"以及绕过 `insert` 的直接写入。
测试要同时覆盖两层，否则只测第 1 层会让触发器变成死代码。
"""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from memory.store.base import ActiveExists
from memory.store.models import Authority, MemoryItem, Scope, Source, Status
from memory.store.sqlite import SqliteStore

BASE = datetime(2026, 1, 1, tzinfo=UTC)


def _item(
    *,
    value: str = "v1",
    valid_from: datetime = BASE,
    valid_to: datetime | None = None,
    condition: str | None = None,
    subject: str = "s",
) -> MemoryItem:
    return MemoryItem(
        owner="o",
        scope=Scope.PROJECT,
        subject=subject,
        relation="r",
        value=value,
        condition=condition,
        status=Status.ACTIVE,
        valid_from=valid_from,
        valid_to=valid_to,
        recorded_at=BASE,
        authority=Authority.USER_DIRECT,
        source=Source(session_id="s1"),
    )


# ---------- 第 1 层：insert 的语义 ----------


def test_insert_with_existing_active_raises_active_exists(tmp_path: Path) -> None:
    """应用层先拦：报错信息明确告诉调用方改用 supersede。"""
    store = SqliteStore(tmp_path / "m.db")
    store.insert(_item(), reason="init", actor="test")

    with pytest.raises(ActiveExists, match="supersede"):
        store.insert(_item(value="v2"), reason="dup", actor="test")


def test_insert_after_retract_is_allowed(tmp_path: Path) -> None:
    """撤回后该键腾空，可以重新写入。"""
    store = SqliteStore(tmp_path / "m.db")
    first = store.insert(_item(), reason="a", actor="test")
    store.retract(first.id, reason="wrong", actor="test")

    stored = store.insert(_item(value="v2"), reason="b", actor="test")

    assert stored.status is Status.ACTIVE


def test_different_condition_is_allowed(tmp_path: Path) -> None:
    """条件分支是并存的事实，不是区间冲突。"""
    store = SqliteStore(tmp_path / "m.db")
    store.insert(_item(condition=None), reason="a", actor="test")

    stored = store.insert(_item(condition="morning"), reason="b", actor="test")

    assert stored.condition == "morning"


def test_different_subject_is_allowed(tmp_path: Path) -> None:
    store = SqliteStore(tmp_path / "m.db")
    store.insert(_item(subject="s1"), reason="a", actor="test")

    stored = store.insert(_item(subject="s2"), reason="b", actor="test")

    assert stored.subject == "s2"


# ---------- 第 2 层：数据库触发器 ----------


def _raw_insert(
    conn: sqlite3.Connection,
    *,
    item_id: str,
    value: str,
    status: str,
    valid_from: datetime,
    valid_to: datetime | None,
    version: int = 1,
    ordinal: int | None = None,
) -> None:
    conn.execute(
        "INSERT INTO items (id, owner, scope, subject, relation, condition, value,"
        " status, valid_from, valid_to, recorded_at, authority, session_id,"
        " fingerprint, fingerprint_key, ordinal, version)"
        " VALUES (?, 'o','project','s','r',NULL,?,?,?,?,"
        " '2026-01-01T00:00:00.000000+00:00','user_direct','sess',?,?,?,?)",
        (
            item_id,
            value,
            status,
            valid_from.isoformat(timespec="microseconds"),
            valid_to.isoformat(timespec="microseconds") if valid_to else None,
            f"fp-{item_id}",
            f"fk-{item_id}",
            ordinal if ordinal is not None else int(valid_from.timestamp() * 1_000_000),
            version,
        ),
    )


def test_trigger_rejects_overlap_between_history_rows(tmp_path: Path) -> None:
    """历史区间（SUPERSEDED）同样不得重叠。

    这是触发器存在的真正理由：`insert` 的 ActiveExists 只挡 ACTIVE，
    而一条 SUPERSEDED 与新 ACTIVE 若区间重叠，active_at 会返回两条。
    """
    store = SqliteStore(tmp_path / "m.db")
    conn = sqlite3.connect(str(store.path))
    _raw_insert(
        conn,
        item_id="h1",
        value="old",
        status="SUPERSEDED",
        valid_from=BASE,
        valid_to=BASE + timedelta(days=30),
    )

    with pytest.raises(sqlite3.IntegrityError, match="overlapping"):
        _raw_insert(
            conn,
            item_id="h2",
            value="new",
            status="SUPERSEDED",
            valid_from=BASE + timedelta(days=10),
            valid_to=BASE + timedelta(days=20),
        )


def test_trigger_treats_open_ended_as_infinite(tmp_path: Path) -> None:
    """`valid_to` 为 NULL 必须被视为延伸到无穷远。

    若用裸 `<` 比较，SQL 里 NULL 会让这条永远不参与重叠检测（实测）。
    """
    store = SqliteStore(tmp_path / "m.db")
    conn = sqlite3.connect(str(store.path))
    _raw_insert(
        conn,
        item_id="h1",
        value="open",
        status="SUPERSEDED",
        valid_from=BASE,
        valid_to=None,
    )

    with pytest.raises(sqlite3.IntegrityError, match="overlapping"):
        _raw_insert(
            conn,
            item_id="h2",
            value="later",
            status="SUPERSEDED",
            valid_from=BASE + timedelta(days=365),
            valid_to=None,
        )


def test_trigger_allows_adjacent_intervals(tmp_path: Path) -> None:
    """前一段结束恰好等于后一段开始，不算重叠。

    这是 supersede 产生的正常形态；若被误判，整个写路径不可用。
    """
    store = SqliteStore(tmp_path / "m.db")
    conn = sqlite3.connect(str(store.path))
    _raw_insert(
        conn,
        item_id="h1",
        value="a",
        status="SUPERSEDED",
        valid_from=BASE,
        valid_to=BASE + timedelta(days=10),
    )
    _raw_insert(
        conn,
        item_id="h2",
        value="b",
        status="SUPERSEDED",
        valid_from=BASE + timedelta(days=10),
        valid_to=None,
        version=2,
    )

    assert conn.execute("SELECT COUNT(*) FROM items").fetchone()[0] == 2


def test_trigger_ignores_retracted_rows(tmp_path: Path) -> None:
    """撤回的条目已作废，不该继续占用时间段。"""
    store = SqliteStore(tmp_path / "m.db")
    conn = sqlite3.connect(str(store.path))
    _raw_insert(
        conn,
        item_id="h1",
        value="wrong",
        status="RETRACTED",
        valid_from=BASE,
        valid_to=None,
        ordinal=1,
    )
    _raw_insert(
        conn,
        item_id="h2",
        value="ok",
        status="ACTIVE",
        valid_from=BASE,
        valid_to=None,
        ordinal=2,
        version=2,
    )

    assert conn.execute("SELECT COUNT(*) FROM items").fetchone()[0] == 2


def test_update_into_overlap_is_rejected(tmp_path: Path) -> None:
    """通过更新改区间同样受限，否则可以绕过插入时的检查。"""
    store = SqliteStore(tmp_path / "m.db")
    conn = sqlite3.connect(str(store.path))
    _raw_insert(
        conn,
        item_id="h1",
        value="a",
        status="SUPERSEDED",
        valid_from=BASE,
        valid_to=BASE + timedelta(days=10),
    )
    _raw_insert(
        conn,
        item_id="h2",
        value="b",
        status="SUPERSEDED",
        valid_from=BASE + timedelta(days=20),
        valid_to=None,
        version=2,
    )

    with pytest.raises(sqlite3.IntegrityError, match="overlapping"):
        conn.execute(
            "UPDATE items SET valid_from = ? WHERE id = 'h2'",
            ((BASE + timedelta(days=5)).isoformat(timespec="microseconds"),),
        )


def test_insert_after_supersede_is_allowed(tmp_path: Path) -> None:
    """supersede 产生的相邻区间是合法形态，不能因为重叠触发器而失败。"""
    store = SqliteStore(tmp_path / "m.db")
    old = store.insert(_item(valid_from=BASE), reason="a", actor="test")

    new = store.supersede(old.id, _item(value="v2", valid_from=BASE + timedelta(days=5)),
                          reason="changed", actor="test")

    assert new.status is Status.ACTIVE
    assert store.get(old.id).valid_to == new.valid_from
