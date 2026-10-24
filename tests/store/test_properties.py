"""属性测试：用 hypothesis 随机构造写入序列，验证不变量恒成立。

为什么需要：示例测试只能覆盖我想到的顺序。属性测试能找到
"某个特定顺序下产生两条 ACTIVE" 这类我没预料到的错误。

每个属性都要能被某个真实的破坏击倒：
- 不变量 → 去掉唯一索引就会失败
- 序号单调 → 改成随机分配就会失败
- 区间相邻 → supersede 少写一个字段就会失败
"""

from __future__ import annotations

import contextlib
from datetime import UTC, datetime, timedelta
from pathlib import Path

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from memory.store.base import ActiveExists, InvariantViolation
from memory.store.models import Authority, MemoryItem, Scope, Source, Status
from memory.store.sqlite import SqliteStore

BASE = datetime(2026, 1, 1, tzinfo=UTC)

VALUES = st.sampled_from(["pnpm", "npm", "yarn", "bun", "cargo"])
SUBJECTS = st.sampled_from(["project:a", "project:b"])
CONDITIONS = st.none() | st.sampled_from(["morning", "night"])


def _item(
    *,
    value: str,
    subject: str,
    condition: str | None,
    offset_days: int,
) -> MemoryItem:
    return MemoryItem(
        owner="o",
        scope=Scope.PROJECT,
        subject=subject,
        relation="r",
        value=value,
        condition=condition,
        status=Status.ACTIVE,
        valid_from=BASE + timedelta(days=offset_days),
        valid_to=None,
        recorded_at=BASE,
        authority=Authority.USER_DIRECT,
        source=Source(session_id="s1"),
    )


def _active_count(store: SqliteStore) -> int:
    import sqlite3

    conn = sqlite3.connect(str(store.path))
    try:
        return int(
            conn.execute("SELECT COUNT(*) FROM items WHERE status = 'ACTIVE'").fetchone()[0]
        )
    finally:
        conn.close()


def _duplicate_active_keys(store: SqliteStore) -> list[tuple[object, ...]]:
    """返回存在多条 ACTIVE 的逻辑键——正常情况下应为空。"""
    import sqlite3

    conn = sqlite3.connect(str(store.path))
    try:
        rows = conn.execute(
            "SELECT owner, scope, subject, relation, IFNULL(condition,''), COUNT(*) AS n"
            " FROM items WHERE status='ACTIVE'"
            " GROUP BY owner, scope, subject, relation, IFNULL(condition,'')"
            " HAVING n > 1"
        ).fetchall()
    finally:
        conn.close()
    return rows


@given(
    steps=st.lists(
        st.tuples(VALUES, SUBJECTS, CONDITIONS, st.integers(min_value=0, max_value=100)),
        min_size=1,
        max_size=25,
    )
)
@settings(
    max_examples=200,
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)
def test_no_key_ever_has_two_active_rows(
    steps: list[tuple[str, str, str | None, int]], tmp_path_factory: object
) -> None:
    """核心不变量。去掉唯一索引，这条会在某个随机序列上失败。"""
    import tempfile

    with tempfile.TemporaryDirectory() as directory:
        store = SqliteStore(Path(directory) / "m.db")
        try:
            for value, subject, condition, offset in steps:
                candidate = _item(
                    value=value, subject=subject, condition=condition, offset_days=offset
                )
                with contextlib.suppress(ActiveExists, InvariantViolation):
                    store.insert(candidate, reason="prop", actor="hypothesis")

            assert _duplicate_active_keys(store) == []
        finally:
            store.close()


@given(
    count=st.integers(min_value=1, max_value=15),
)
@settings(
    max_examples=50,
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)
def test_ordinals_are_strictly_increasing(count: int) -> None:
    """序号必须是写入序的全序，否则时间线无法稳定排序。"""
    import tempfile

    with tempfile.TemporaryDirectory() as directory:
        store = SqliteStore(Path(directory) / "m.db")
        try:
            ordinals = []
            for index in range(count):
                stored = store.insert(
                    _item(
                        value=f"v{index}",
                        subject=f"subject-{index}",
                        condition=None,
                        offset_days=0,
                    ),
                    reason="prop",
                    actor="hypothesis",
                )
                ordinals.append(stored.ordinal)

            assert ordinals == sorted(ordinals)
            assert len(set(ordinals)) == len(ordinals)
        finally:
            store.close()


@given(versions=st.integers(min_value=2, max_value=8))
@settings(
    max_examples=40,
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)
def test_supersede_keeps_intervals_adjacent(versions: int) -> None:
    """相邻性是 `active_at` 在边界点返回新条目的前提。

    若 supersede 漏写 `valid_to` 或写错值，边界点上要么返回旧条目，
    要么两个都返回。
    """
    import tempfile

    with tempfile.TemporaryDirectory() as directory:
        store = SqliteStore(Path(directory) / "m.db")
        try:
            current = store.insert(
                _item(value="v0", subject="s", condition=None, offset_days=0),
                reason="init",
                actor="hypothesis",
            )
            for index in range(1, versions):
                new_offset = index * 10
                previous = store.get(current.id)
                current = store.supersede(
                    current.id,
                    _item(
                        value=f"v{index}",
                        subject="s",
                        condition=None,
                        offset_days=new_offset,
                    ),
                    reason="next",
                    actor="hypothesis",
                )
                closed = store.get(previous.id)
                assert closed.valid_to is not None
                assert closed.valid_to == current.valid_from, "新旧区间必须相邻"

                at_boundary = store.active_at(
                    owner="o",
                    scope=Scope.PROJECT,
                    subject="s",
                    relation="r",
                    condition=None,
                    at=current.valid_from,
                )
                assert at_boundary is not None
                assert at_boundary.id == current.id, "边界点应返回新条目"
        finally:
            store.close()


@given(
    offset=st.integers(min_value=-50, max_value=500),
    versions=st.integers(min_value=1, max_value=6),
)
@settings(
    max_examples=120,
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)
def test_at_most_one_row_at_any_time(offset: int, versions: int) -> None:
    """任意随机时间点，`active_at` 至多返回一条。

    这是"区间不重叠"这条不变量在查询侧的体现。
    """
    import tempfile

    with tempfile.TemporaryDirectory() as directory:
        store = SqliteStore(Path(directory) / "m.db")
        try:
            current = store.insert(
                _item(value="v0", subject="s", condition=None, offset_days=0),
                reason="init",
                actor="hypothesis",
            )
            for index in range(1, versions):
                current = store.supersede(
                    current.id,
                    _item(
                        value=f"v{index}",
                        subject="s",
                        condition=None,
                        offset_days=index * 20,
                    ),
                    reason="next",
                    actor="hypothesis",
                )

            temporal = store.active_at(
                owner="o",
                scope=Scope.PROJECT,
                subject="s",
                relation="r",
                condition=None,
                at=BASE + timedelta(days=offset),
            )
            # 若实现返回多条，上面这个调用会抛 MultipleResults 或静默取第一条；
            # 这里再用 SQL 直接确认区间不重叠。
            import sqlite3

            conn = sqlite3.connect(str(store.path))
            try:
                overlapping = conn.execute(
                    "SELECT COUNT(*) FROM items a JOIN items b"
                    " ON a.id < b.id AND a.subject = b.subject AND a.relation = b.relation"
                    " AND a.status != 'RETRACTED' AND b.status != 'RETRACTED'"
                    " AND a.valid_from < COALESCE(b.valid_to,'9999-12-31T23:59:59+00:00')"
                    " AND COALESCE(a.valid_to,'9999-12-31T23:59:59+00:00') > b.valid_from"
                ).fetchone()[0]
            finally:
                conn.close()

            assert overlapping == 0
            if temporal is not None:
                assert temporal.status in (Status.ACTIVE, Status.SUPERSEDED)
        finally:
            store.close()
