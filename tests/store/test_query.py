"""查询路径的行为契约。

三个最容易写错的地方：
1. `t < NULL` 让"当前有效"的条目永远查不到
2. 撤回的事实必须任何时刻都不返回，但仍留在时间线里
3. 中文 FTS5 没有分词，必须自己切 bigram
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
    value: str = "v1",
    valid_from: datetime = BASE,
    condition: str | None = None,
    subject: str = "project:agent-memory",
    relation: str = "package_manager",
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
        recorded_at=BASE,
        authority=Authority.USER_DIRECT,
        source=Source(session_id="s1"),
    )


def _three_versions(store: SqliteStore) -> None:
    v1 = store.insert(_item(value="pnpm", valid_from=BASE), reason="1", actor="t")
    v2 = store.supersede(
        v1.id,
        _item(value="npm", valid_from=BASE + timedelta(days=10)),
        reason="2",
        actor="t",
    )
    store.supersede(
        v2.id,
        _item(value="yarn", valid_from=BASE + timedelta(days=20)),
        reason="3",
        actor="t",
    )


def _active_at(store: SqliteStore, at: datetime, **overrides: object) -> MemoryItem | None:
    kwargs: dict[str, object] = {
        "owner": "default",
        "scope": Scope.PROJECT,
        "subject": "project:agent-memory",
        "relation": "package_manager",
        "condition": None,
        "at": at,
    }
    kwargs.update(overrides)
    return store.active_at(**kwargs)  # type: ignore[arg-type]


# ---------- 6.1 / 6.2 active_at ----------


def test_three_versions_return_correct_one(tmp_path: Path) -> None:
    store = SqliteStore(tmp_path / "m.db")
    _three_versions(store)

    assert _active_at(store, BASE + timedelta(days=1)).value == "pnpm"
    assert _active_at(store, BASE + timedelta(days=15)).value == "npm"
    assert _active_at(store, BASE + timedelta(days=25)).value == "yarn"


def test_open_ended_current_version_is_returned(tmp_path: Path) -> None:
    """`t < NULL` 求值为 NULL，会把"当前有效"的条目整个过滤掉。

    这是审查发现的 P0：不写 `OR valid_to IS NULL`，当前值就查不到。
    """
    store = SqliteStore(tmp_path / "m.db")
    store.insert(_item(value="current"), reason="1", actor="t")

    found = _active_at(store, BASE + timedelta(days=365))

    assert found is not None
    assert found.value == "current"


def test_before_first_record_returns_none(tmp_path: Path) -> None:
    """返回最早那条会让"当时还没这条记忆"变成错误的事实。"""
    store = SqliteStore(tmp_path / "m.db")
    _three_versions(store)

    assert _active_at(store, BASE - timedelta(days=100)) is None


def test_retracted_is_invisible_at_every_time(tmp_path: Path) -> None:
    """撤回的事实从未真正有效，任何时间点都不该返回。"""
    store = SqliteStore(tmp_path / "m.db")
    created = store.insert(_item(value="wrong"), reason="1", actor="t")
    store.retract(created.id, reason="bogus", actor="t")

    assert _active_at(store, BASE + timedelta(days=1)) is None


def test_only_conflicted_returns_none(tmp_path: Path) -> None:
    """冲突未裁决时"当前值未定"，返回空正是要传达的信号。"""
    store = SqliteStore(tmp_path / "m.db")
    created = store.insert(_item(value="disputed"), reason="1", actor="t")
    store.mark_conflict(created.id, reason="conflicting evidence", actor="t")

    assert _active_at(store, BASE + timedelta(days=1)) is None


def test_unconditional_query_does_not_mix_branches(tmp_path: Path) -> None:
    """fixture 必须同时含无条件与条件两条，否则空集也能让断言通过。"""
    store = SqliteStore(tmp_path / "m.db")
    store.insert(_item(value="plain"), reason="1", actor="t")
    store.insert(_item(value="morning", condition="morning"), reason="2", actor="t")

    found = _active_at(store, BASE + timedelta(days=1))

    assert found is not None
    assert found.value == "plain"


def test_conditional_query_returns_branch(tmp_path: Path) -> None:
    store = SqliteStore(tmp_path / "m.db")
    store.insert(_item(value="plain"), reason="1", actor="t")
    store.insert(_item(value="morning", condition="morning"), reason="2", actor="t")

    found = _active_at(store, BASE + timedelta(days=1), condition="morning")

    assert found is not None
    assert found.value == "morning"


def test_at_most_one_row_at_any_time(tmp_path: Path) -> None:
    """这是不变量在查询侧的体现；返回两条时调用方通常只取第一条。"""
    store = SqliteStore(tmp_path / "m.db")
    _three_versions(store)

    for offset in range(0, 40, 3):
        found = _active_at(store, BASE + timedelta(days=offset))
        assert found is not None


def test_naive_datetime_is_rejected(tmp_path: Path) -> None:
    """无时区时间会与 +00:00 字符串比较出 8 小时偏差。"""
    store = SqliteStore(tmp_path / "m.db")
    store.insert(_item(), reason="1", actor="t")

    with pytest.raises(ValueError, match="时区"):
        _active_at(store, datetime(2026, 1, 2))


# ---------- 6.3 / 6.4 timeline ----------


def test_timeline_returns_all_versions_in_order(tmp_path: Path) -> None:
    store = SqliteStore(tmp_path / "m.db")
    _three_versions(store)

    timeline = store.timeline(
        owner="default",
        scope=Scope.PROJECT,
        subject="project:agent-memory",
        relation="package_manager",
    )

    assert [item.version for item in timeline] == [1, 2, 3]
    assert [item.value for item in timeline] == ["pnpm", "npm", "yarn"]
    assert [item.status for item in timeline] == [
        Status.SUPERSEDED,
        Status.SUPERSEDED,
        Status.ACTIVE,
    ]


def test_timeline_includes_condition_branches(tmp_path: Path) -> None:
    store = SqliteStore(tmp_path / "m.db")
    store.insert(_item(value="plain"), reason="1", actor="t")
    store.insert(_item(value="morning", condition="morning"), reason="2", actor="t")

    timeline = store.timeline(
        owner="default",
        scope=Scope.PROJECT,
        subject="project:agent-memory",
        relation="package_manager",
    )

    assert len(timeline) == 2
    assert {item.condition for item in timeline} == {None, "morning"}


def test_empty_timeline_returns_empty_list(tmp_path: Path) -> None:
    store = SqliteStore(tmp_path / "m.db")

    assert store.timeline(
        owner="default",
        scope=Scope.PROJECT,
        subject="never",
        relation="written",
    ) == []


def test_timeline_includes_retracted(tmp_path: Path) -> None:
    """撤回的内容必须留在时间线里，否则审计链断了。"""
    store = SqliteStore(tmp_path / "m.db")
    created = store.insert(_item(), reason="1", actor="t")
    store.retract(created.id, reason="wrong", actor="t")

    timeline = store.timeline(
        owner="default",
        scope=Scope.PROJECT,
        subject="project:agent-memory",
        relation="package_manager",
    )

    assert len(timeline) == 1
    assert timeline[0].status is Status.RETRACTED


# ---------- 6.5 / 6.6 FTS ----------


def test_chinese_bigram_search_hits(tmp_path: Path) -> None:
    """FTS5 的 unicode61 把整段中文当一个 token。

    实测 `项目使用包管理器` 对 `包管理` 查询返回 0 条；必须自己做 bigram。
    """
    store = SqliteStore(tmp_path / "m.db")
    store.insert(_item(value="项目使用包管理器", relation="说明"), reason="1", actor="t")

    hits = store.search_text("包管理")

    assert len(hits) == 1


def test_single_chinese_character_falls_back_to_like(tmp_path: Path) -> None:
    """单字不是 bigram，必须走降级路径，而不是静默返回空。"""
    store = SqliteStore(tmp_path / "m.db")
    store.insert(_item(value="项目使用包管理器", relation="说明"), reason="1", actor="t")

    hits = store.search_text("包")

    assert len(hits) == 1


def test_english_word_search_hits(tmp_path: Path) -> None:
    store = SqliteStore(tmp_path / "m.db")
    store.insert(_item(value="uses pnpm workspace"), reason="1", actor="t")

    assert len(store.search_text("pnpm")) == 1


def test_superseded_not_in_current_search(tmp_path: Path) -> None:
    """被取代的条目不该出现在"当前"检索里，否则检索层又要自己裁决一遍。"""
    store = SqliteStore(tmp_path / "m.db")
    v1 = store.insert(_item(value="pnpm"), reason="1", actor="t")
    store.supersede(
        v1.id, _item(value="npm", valid_from=BASE + timedelta(days=1)), reason="2", actor="t"
    )

    hits = store.search_text("pnpm")

    assert hits == []


def test_retracted_not_in_current_search(tmp_path: Path) -> None:
    store = SqliteStore(tmp_path / "m.db")
    created = store.insert(_item(value="pnpm"), reason="1", actor="t")
    store.retract(created.id, reason="wrong", actor="t")

    assert store.search_text("pnpm") == []


def test_fts_survives_reopen(tmp_path: Path) -> None:
    """FTS 若只在内存里，重启后检索全部落空。"""
    db = tmp_path / "m.db"
    store = SqliteStore(db)
    store.insert(_item(value="项目使用包管理器"), reason="1", actor="t")
    store.close()

    reopened = SqliteStore(db)

    assert len(reopened.search_text("包管理")) == 1
