"""写入路径的行为契约。

覆盖：ordinal/version 分配、审计、幂等、A→B→A、错误映射。
每一条都对应一个会让数据变脏的具体破坏。
"""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from memory.store.base import ActiveExists
from memory.store.models import Authority, MemoryItem, Scope, Source, Status
from memory.store.sqlite import SqliteStore

NOW = datetime(2026, 1, 1, tzinfo=UTC)


def _item(
    *,
    value: str = "pnpm",
    subject: str = "project:agent-memory",
    relation: str = "package_manager",
    condition: str | None = None,
    valid_from: datetime = NOW,
    authority: Authority = Authority.USER_DIRECT,
    session_id: str = "s1",
) -> MemoryItem:
    return MemoryItem(
        owner="default",
        scope=Scope.PROJECT,
        subject=subject,
        relation=relation,
        value=value,
        condition=condition,
        status=Status.ACTIVE,
        valid_from=valid_from,
        valid_to=None,
        recorded_at=NOW,
        authority=authority,
        source=Source(session_id=session_id),
    )


# ---------- 4.1 / 4.2 基本写入 ----------


def test_insert_assigns_id_and_ordinal(tmp_path: Path) -> None:
    store = SqliteStore(tmp_path / "m.db")

    stored = store.insert(_item(), reason="init", actor="tester")

    assert stored.id
    assert stored.ordinal == 1
    assert stored.version == 1


def test_ordinals_increase_globally_across_keys(tmp_path: Path) -> None:
    """全局单调：跨键比较写入先后时有意义。"""
    store = SqliteStore(tmp_path / "m.db")

    first = store.insert(_item(subject="a"), reason="1", actor="t")
    second = store.insert(_item(subject="b"), reason="2", actor="t")
    third = store.insert(_item(subject="c"), reason="3", actor="t")

    assert [first.ordinal, second.ordinal, third.ordinal] == [1, 2, 3]


def test_version_increases_within_key(tmp_path: Path) -> None:
    """键内版本号从 1 开始连续递增，时间线读起来才直观。"""
    store = SqliteStore(tmp_path / "m.db")
    v1 = store.insert(_item(value="a"), reason="1", actor="t")
    v2 = store.supersede(v1.id, _item(value="b", valid_from=NOW + timedelta(days=1)),
                         reason="2", actor="t")
    v3 = store.supersede(v2.id, _item(value="c", valid_from=NOW + timedelta(days=2)),
                         reason="3", actor="t")

    assert [v1.version, v2.version, v3.version] == [1, 2, 3]


def test_insert_writes_add_event(tmp_path: Path) -> None:
    """没有审计事件的写入无法追溯"谁在什么时候为什么写的"。"""
    store = SqliteStore(tmp_path / "m.db")
    stored = store.insert(_item(), reason="初次建立约定", actor="alice")

    events = store.events_for(stored.id)

    assert len(events) == 1
    assert events[0]["decision"] == "ADD"
    assert events[0]["reason"] == "初次建立约定"
    assert events[0]["actor"] == "alice"


def test_insert_requires_reason_and_actor_at_runtime(tmp_path: Path) -> None:
    store = SqliteStore(tmp_path / "m.db")

    with pytest.raises(TypeError):
        store.insert(_item())  # type: ignore[call-arg]


# ---------- 4.3 / 4.4 已有有效值 ----------


def test_insert_on_existing_active_raises_active_exists(tmp_path: Path) -> None:
    """这个错误要引导调用方改用 supersede，而不是暴露底层唯一索引冲突。"""
    store = SqliteStore(tmp_path / "m.db")
    store.insert(_item(value="pnpm"), reason="1", actor="t")

    with pytest.raises(ActiveExists, match="supersede"):
        store.insert(_item(value="npm"), reason="2", actor="t")


def test_failed_insert_leaves_no_partial_state(tmp_path: Path) -> None:
    """回滚不彻底会让库里留下一条没有事件、也没有 ACTIVE 的孤儿。"""
    store = SqliteStore(tmp_path / "m.db")
    first = store.insert(_item(value="pnpm"), reason="1", actor="t")
    events_before = store.event_count()

    with pytest.raises(ActiveExists):
        store.insert(_item(value="npm"), reason="2", actor="t")

    assert store.count() == 1
    assert store.event_count() == events_before
    assert store.get(first.id).value == "pnpm"


# ---------- 4.5 / 4.6 幂等 ----------


def test_identical_insert_is_noop(tmp_path: Path) -> None:
    """同一条事实被重复确认时不该产生新版本，否则记忆会无限膨胀。"""
    store = SqliteStore(tmp_path / "m.db")
    first = store.insert(_item(), reason="1", actor="t")

    second = store.insert(_item(), reason="again", actor="t")

    assert second.id == first.id
    assert store.count() == 1
    assert second.version == 1


def test_noop_writes_an_event(tmp_path: Path) -> None:
    """NOOP 也要留痕，否则无法解释"为什么没有更新"。"""
    store = SqliteStore(tmp_path / "m.db")
    stored = store.insert(_item(), reason="1", actor="t")
    store.insert(_item(), reason="repeat", actor="t")

    decisions = [event["decision"] for event in store.events_for(stored.id)]

    assert decisions == ["ADD", "NOOP"]


def test_same_content_from_another_session_is_noop(tmp_path: Path) -> None:
    """同一事实换个会话说一遍，仍是同一事实。"""
    store = SqliteStore(tmp_path / "m.db")
    first = store.insert(_item(session_id="s1"), reason="1", actor="t")

    second = store.insert(_item(session_id="s2"), reason="2", actor="t")

    assert second.id == first.id


def test_different_authority_is_not_noop(tmp_path: Path) -> None:
    """用户自述与工单备注可信度不同，不该互相吞并。"""
    store = SqliteStore(tmp_path / "m.db")
    store.insert(_item(authority=Authority.USER_DIRECT), reason="1", actor="t")

    with pytest.raises(ActiveExists):
        store.insert(_item(authority=Authority.THIRD_PARTY), reason="2", actor="t")


# ---------- 4.7 / 4.8 A→B→A ----------


def test_aba_produces_third_version(tmp_path: Path) -> None:
    """用户改回旧值时，不能因为"内容与旧版本相同"被当作重复而丢弃。

    这是审查发现的 P0：指纹命中的是已 SUPERSEDED 的旧行，于是新值永远不生效。
    """
    store = SqliteStore(tmp_path / "m.db")
    v1 = store.insert(_item(value="pnpm"), reason="1", actor="t")
    v2 = store.supersede(
        v1.id, _item(value="npm", valid_from=NOW + timedelta(days=1)), reason="2", actor="t"
    )
    v3 = store.supersede(
        v2.id, _item(value="pnpm", valid_from=NOW + timedelta(days=2)), reason="3", actor="t"
    )

    assert v3.id != v1.id
    assert v3.version == 3
    assert v3.status is Status.ACTIVE
    assert store.active_at(
        owner="default",
        scope=Scope.PROJECT,
        subject="project:agent-memory",
        relation="package_manager",
        condition=None,
        at=NOW + timedelta(days=3),
    ).value == "pnpm"


def test_aba_timeline_has_three_entries(tmp_path: Path) -> None:
    store = SqliteStore(tmp_path / "m.db")
    v1 = store.insert(_item(value="pnpm"), reason="1", actor="t")
    v2 = store.supersede(
        v1.id, _item(value="npm", valid_from=NOW + timedelta(days=1)), reason="2", actor="t"
    )
    store.supersede(
        v2.id, _item(value="pnpm", valid_from=NOW + timedelta(days=2)), reason="3", actor="t"
    )

    timeline = store.timeline(
        owner="default",
        scope=Scope.PROJECT,
        subject="project:agent-memory",
        relation="package_manager",
    )

    assert [item.version for item in timeline] == [1, 2, 3]
    assert [item.status for item in timeline] == [
        Status.SUPERSEDED,
        Status.SUPERSEDED,
        Status.ACTIVE,
    ]


# ---------- 4.9 / 4.10 错误映射 ----------


def test_check_violation_is_not_reported_as_invariant(tmp_path: Path) -> None:
    """把 CHECK 失败报成"重复 ACTIVE"会让 C3 的冲突处理走错分支。"""
    store = SqliteStore(tmp_path / "m.db")
    conn = sqlite3.connect(str(store.path))

    with pytest.raises(sqlite3.IntegrityError) as excinfo:
        conn.execute(
            "INSERT INTO items (id, owner, scope, subject, relation, condition, value,"
            " status, valid_from, recorded_at, authority, session_id, fingerprint,"
            " fingerprint_key, ordinal, version)"
            " VALUES ('x','o','project','s','r',NULL,'v','NONSENSE',"
            " '2026-01-01T00:00:00.000000+00:00','2026-01-01T00:00:00.000000+00:00',"
            " 'user_direct','sess','fp','fk',99,99)"
        )
    assert getattr(excinfo.value, "sqlite_errorcode", None) == sqlite3.SQLITE_CONSTRAINT_CHECK


def test_supersede_same_instant_is_auto_advanced(tmp_path: Path) -> None:
    """同一时刻改主意是正常场景（同一分钟内改两次），不该报错。

    实现把新条目起点推到旧起点之后 1 微秒，保证区间不倒挂。
    """
    store = SqliteStore(tmp_path / "m.db")
    first = store.insert(_item(value="pnpm", valid_from=NOW), reason="1", actor="t")

    second = store.supersede(
        first.id,
        _item(value="npm", valid_from=NOW),
        reason="changed same minute",
        actor="t",
    )

    assert second.valid_from > first.valid_from
    assert store.get(first.id).valid_to == second.valid_from


def test_supersede_earlier_start_is_auto_advanced(tmp_path: Path) -> None:
    """即使调用方给了更早的时间，也不能让区间倒挂。"""
    store = SqliteStore(tmp_path / "m.db")
    first = store.insert(_item(value="pnpm", valid_from=NOW), reason="1", actor="t")

    second = store.supersede(
        first.id,
        _item(value="npm", valid_from=NOW - timedelta(days=1)),
        reason="bad timestamp",
        actor="t",
    )

    assert second.valid_from > first.valid_from
    assert store.get(first.id).valid_to == second.valid_from


def test_error_codes_are_distinguishable(tmp_path: Path) -> None:
    """实测：unique=2067、notnull=1299、check=275。三者必须能分开。"""
    import sqlite3 as s

    conn = s.connect(":memory:")
    conn.executescript(
        "CREATE TABLE t (a TEXT NOT NULL, b TEXT CHECK (b IN ('x','y')));"
        "CREATE UNIQUE INDEX ux ON t(a);"
        "INSERT INTO t VALUES ('k','x');"
    )
    codes: dict[str, int] = {}
    for label, sql in [
        ("unique", "INSERT INTO t VALUES ('k','y')"),
        ("notnull", "INSERT INTO t VALUES (NULL,'y')"),
        ("check", "INSERT INTO t VALUES ('other','z')"),
    ]:
        try:
            conn.execute(sql)
        except s.IntegrityError as exc:
            codes[label] = exc.sqlite_errorcode

    assert codes["unique"] == s.SQLITE_CONSTRAINT_UNIQUE
    assert codes["notnull"] == s.SQLITE_CONSTRAINT_NOTNULL
    assert codes["check"] == s.SQLITE_CONSTRAINT_CHECK
