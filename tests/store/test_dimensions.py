"""向量维度校验的行为契约。

维度不符若被静默接受，错误会拖到 C4 计算点积时才爆发，且错误信息
完全指不出方向（"shapes (1024,) and (768,) not aligned"）。
写时就拒绝，才能定位。
"""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pytest

from memory.store.base import DimensionMismatch
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


def test_correct_dimensions_are_stored(tmp_path: Path) -> None:
    store = SqliteStore(tmp_path / "m.db", embedding_dims=4)

    stored = store.insert(_item(), reason="x", actor="t", embedding=[0.1, 0.2, 0.3, 0.4])

    vector = store.embedding_of(stored.id)
    assert vector is not None
    assert vector.shape == (4,)
    assert vector.dtype == np.float32


def test_wrong_dimensions_raise_dimension_mismatch(tmp_path: Path) -> None:
    """必须是 DimensionMismatch，不能混成 InvariantViolation（重试逻辑会做错决定）。"""
    store = SqliteStore(tmp_path / "m.db", embedding_dims=4)

    with pytest.raises(DimensionMismatch, match="维度"):
        store.insert(_item(), reason="x", actor="t", embedding=[0.1, 0.2])


def test_wrong_dimensions_roll_back_the_item(tmp_path: Path) -> None:
    """维度错误时整条写入必须回滚，不能留下一条没有向量的记忆。"""
    store = SqliteStore(tmp_path / "m.db", embedding_dims=4)

    with pytest.raises(DimensionMismatch):
        store.insert(_item(), reason="x", actor="t", embedding=[0.1, 0.2])

    assert store.count() == 0


def test_no_embedding_is_allowed(tmp_path: Path) -> None:
    """向量可选：C2 只存文本时不该强制要求向量。"""
    store = SqliteStore(tmp_path / "m.db", embedding_dims=4)

    stored = store.insert(_item(), reason="x", actor="t")

    assert store.embedding_of(stored.id) is None


def test_reopening_with_different_dims_is_rejected(tmp_path: Path) -> None:
    """同一个库用不同维度打开，已有向量会与新写入的不可比。"""
    db = tmp_path / "m.db"
    SqliteStore(db, embedding_dims=4).close()

    with pytest.raises(ValueError, match="维度"):
        SqliteStore(db, embedding_dims=8)


def test_dimension_is_persisted(tmp_path: Path) -> None:
    store = SqliteStore(tmp_path / "m.db", embedding_dims=768)
    assert store.embedding_dims() == 768

    conn = sqlite3.connect(str(store.path))
    value = conn.execute(
        "SELECT value FROM meta WHERE key = 'embedding_dims'"
    ).fetchone()[0]
    assert value == "768"


def test_embedding_survives_reopen(tmp_path: Path) -> None:
    """向量存在数据库里，不能只留在内存。"""
    db = tmp_path / "m.db"
    store = SqliteStore(db, embedding_dims=2)
    stored = store.insert(_item(), reason="x", actor="t", embedding=[1.0, -1.0])
    store.close()

    reopened = SqliteStore(db, embedding_dims=2)
    vector = reopened.embedding_of(stored.id)

    assert vector is not None
    assert np.array_equal(vector, np.array([1.0, -1.0], dtype=np.float32))
