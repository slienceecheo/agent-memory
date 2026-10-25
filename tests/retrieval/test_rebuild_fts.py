"""FTS 重建脚本的行为契约。

FTS5 虚拟表不支持加列，要让索引包含原文必须 DROP 重建。
这个过程必须可验证：条目数不变、原文可检索、失败可回滚。
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
from evals.tools.rebuild_fts import rebuild

from memory.store.models import Authority, MemoryItem, Scope, Source, Status
from memory.store.sqlite import SqliteStore

NOW = datetime(2026, 1, 1, tzinfo=UTC)


def _item(*, value: str, text: str | None, subject: str = "user:a") -> MemoryItem:
    return MemoryItem(
        owner="o",
        scope=Scope.PROJECT,
        subject=subject,
        relation="note",
        value=value,
        condition=None,
        status=Status.ACTIVE,
        valid_from=NOW,
        valid_to=None,
        recorded_at=NOW,
        authority=Authority.USER_DIRECT,
        source=Source(session_id="s1"),
        text=text,
    )


def _seed(path: Path) -> SqliteStore:
    store = SqliteStore(path)
    store.insert(_item(value="C区第三排", text="就是靠窗那一排"), reason="r", actor="t")
    store.insert(_item(value="第二个", text="另一个位置", subject="user:b"), reason="r", actor="t")
    return store


def test_rebuild_preserves_item_count(tmp_path: Path) -> None:
    db = tmp_path / "m.db"
    store = _seed(db)
    before = store.count()
    store.close()

    stats = rebuild(db)

    assert stats["items"] == before
    assert stats["fts_after"] == before


def test_rebuild_makes_text_searchable(tmp_path: Path) -> None:
    """这是重建的唯一目的：让只在原文里出现的词能命中。"""
    db = tmp_path / "m.db"
    store = _seed(db)
    store.close()

    rebuild(db)

    reopened = SqliteStore(db)
    hits = reopened.search_text("靠窗")
    reopened.close()

    assert len(hits) == 1
    assert hits[0].value == "C区第三排"


def test_rebuild_reports_items_with_text(tmp_path: Path) -> None:
    db = tmp_path / "m.db"
    store = _seed(db)
    store.close()

    stats = rebuild(db)

    assert stats["with_text"] == 2


def test_dry_run_does_not_modify(tmp_path: Path) -> None:
    db = tmp_path / "m.db"
    store = _seed(db)
    store.close()

    stats = rebuild(db, dry_run=True)

    assert stats["fts_after"] == -1
    assert stats["items"] == 2


def test_missing_database_raises(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError, match="找不到数据库"):
        rebuild(tmp_path / "nope.db")


def test_rebuild_is_idempotent(tmp_path: Path) -> None:
    """重复执行不该产生重复索引行。"""
    db = tmp_path / "m.db"
    store = _seed(db)
    store.close()

    rebuild(db)
    stats = rebuild(db)

    assert stats["fts_after"] == stats["items"]


def test_rebuild_empty_database(tmp_path: Path) -> None:
    db = tmp_path / "m.db"
    SqliteStore(db).close()

    stats = rebuild(db)

    assert stats["items"] == 0
    assert stats["fts_after"] == 0


def test_items_without_text_are_indexed(tmp_path: Path) -> None:
    """旧条目没有原文，仍应被结构字段索引，不能被漏掉。"""
    db = tmp_path / "m.db"
    store = SqliteStore(db)
    store.insert(_item(value="pnpm", text=None), reason="r", actor="t")
    store.close()

    rebuild(db)

    reopened = SqliteStore(db)
    hits = reopened.search_text("pnpm")
    reopened.close()

    assert len(hits) == 1
