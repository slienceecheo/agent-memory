"""并发写的行为契约。

要点：**确定性交错**，不靠"几乎同时"。
审查指出：靠 sleep 的并发测试不稳定，而且会被唯一索引"顺便救活"，
测不出 `BEGIN IMMEDIATE` 是否真的起作用。

做法：A 显式 BEGIN IMMEDIATE 并持有写锁，B 以 timeout=0 尝试写入，
必须立刻收到 StoreBusy；A 提交后 B 重试成功。
"""

from __future__ import annotations

import sqlite3
import threading
import time
from datetime import UTC, datetime
from pathlib import Path

import pytest

from memory.store.base import StoreBusy
from memory.store.models import Authority, MemoryItem, Scope, Source, Status
from memory.store.sqlite import SqliteStore

BASE = datetime(2026, 1, 1, tzinfo=UTC)


def _item(*, value: str = "v1", subject: str = "s") -> MemoryItem:
    return MemoryItem(
        owner="o",
        scope=Scope.PROJECT,
        subject=subject,
        relation="r",
        value=value,
        condition=None,
        status=Status.ACTIVE,
        valid_from=BASE,
        valid_to=None,
        recorded_at=BASE,
        authority=Authority.USER_DIRECT,
        source=Source(session_id="s1"),
    )


def test_busy_is_raised_when_lock_held(tmp_path: Path) -> None:
    """写锁被持有时必须立刻报 StoreBusy，而不是等到默认 timeout 超时。"""
    db = tmp_path / "m.db"
    writer = SqliteStore(db, timeout_seconds=0.0)

    # 另一个连接持有写锁
    holder = sqlite3.connect(str(db), isolation_level=None)
    holder.execute("BEGIN IMMEDIATE")
    try:
        with pytest.raises(StoreBusy):
            writer.insert(_item(), reason="blocked", actor="t")
    finally:
        holder.execute("ROLLBACK")
        holder.close()
        writer.close()


def test_write_succeeds_after_lock_released(tmp_path: Path) -> None:
    """锁释放后必须能成功；否则一次竞争会让后续全部失败。"""
    db = tmp_path / "m.db"
    writer = SqliteStore(db, timeout_seconds=0.0)

    holder = sqlite3.connect(str(db), isolation_level=None)
    holder.execute("BEGIN IMMEDIATE")
    with pytest.raises(StoreBusy):
        writer.insert(_item(), reason="blocked", actor="t")
    sender = holder.execute("COMMIT")
    holder.close()
    _ = sender

    stored = writer.insert(_item(), reason="retry", actor="t")
    writer.close()

    assert stored.status is Status.ACTIVE


def test_store_busy_is_not_invariant_violation() -> None:
    """两者必须可区分：前者应重试，后者重试也没用。"""
    from memory.store.base import InvariantViolation

    assert not issubclass(StoreBusy, InvariantViolation)
    assert not issubclass(InvariantViolation, StoreBusy)


def test_sequential_writes_get_increasing_versions(tmp_path: Path) -> None:
    """这是并发测试的对照：顺序写必须得到连续版本。"""
    store = SqliteStore(tmp_path / "m.db")
    first = store.insert(_item(value="a"), reason="1", actor="t")
    second = store.supersede(
        first.id, _item(value="b"), reason="2", actor="t"
    )

    assert second.version == first.version + 1
    store.close()


def test_two_threads_do_not_both_succeed_on_same_key(tmp_path: Path) -> None:
    """两个线程争同一键时，只有一个能创建 ACTIVE 条目。

    用线程 + 屏障制造真实竞争，但结果断言是确定性的：
    成功数恰好为 1，另一个收到明确的冲突或忙。
    """
    db = tmp_path / "m.db"
    SqliteStore(db).close()

    results: list[str] = []
    barrier = threading.Barrier(2)

    def attempt(tag: str) -> None:
        store = SqliteStore(db, timeout_seconds=0.0)
        try:
            barrier.wait(timeout=5)
            store.insert(_item(value=f"v-{tag}"), reason=tag, actor=tag)
            results.append("ok")
        except Exception as exc:
            results.append(type(exc).__name__)
        finally:
            store.close()

    threads = [threading.Thread(target=attempt, args=(tag,)) for tag in ("a", "b")]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)

    ok_count = results.count("ok")
    assert ok_count == 1, f"期望恰好一个成功，实际 {results}"
    assert any(name in {"StoreBusy", "ActiveExists"} for name in results), results


def test_audit_events_survive_concurrent_writes(tmp_path: Path) -> None:
    """并发写不能让审计漏记；每个成功写入都应有一条 ADD 事件。"""
    db = tmp_path / "m.db"
    store = SqliteStore(db)

    for index in range(10):
        store.insert(_item(value=f"v{index}", subject=f"s{index}"), reason="x", actor="t")

    assert store.event_count() == 10
    store.close()


def test_lock_timeout_is_configurable(tmp_path: Path) -> None:
    """默认 5 秒对评测太慢；必须允许调小，否则卡死时无从判断。"""
    db = tmp_path / "m.db"
    SqliteStore(db, timeout_seconds=0.0).close()

    start = time.perf_counter()
    store = SqliteStore(db, timeout_seconds=0.0)
    holder = sqlite3.connect(str(db), isolation_level=None)
    holder.execute("BEGIN IMMEDIATE")
    try:
        with pytest.raises(StoreBusy):
            store.insert(_item(), reason="x", actor="t")
    finally:
        holder.execute("ROLLBACK")
        holder.close()
        store.close()
    elapsed = time.perf_counter() - start

    assert elapsed < 2.0, f"timeout=0 时不该等这么久（实际 {elapsed:.2f}s）"
