"""embedding 缓存的行为契约。

缓存是"可复现"的前提：上游对同一文本重复调用不保证逐位一致，
所以命中必须返回入库时那一份，不能重新计算。
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import numpy as np
import pytest

from memory.embedding.cache import EmbeddingCache


def _vec(*values: float) -> np.ndarray:
    return np.asarray(values, dtype=np.float32)


def _corrupt(path: Path, key: str) -> None:
    """测试工具：直接把向量列改成非法长度，模拟磁盘损坏。"""
    conn = sqlite3.connect(str(path))
    with conn:
        conn.execute("UPDATE embeddings SET vector = x'00' WHERE key = ?", (key,))
    conn.close()


def test_store_then_load_returns_exact_values(tmp_path: Path) -> None:
    """若实现改成 float64 或保存成字符串，这里会因精度/类型变化失败。"""
    cache = EmbeddingCache(tmp_path / "cache.db")
    vec = _vec(0.1, -0.25, 3.5)

    cache.put("key-a", vec)
    loaded = cache.get("key-a")

    assert loaded is not None
    assert loaded.dtype == np.float32
    assert np.array_equal(loaded, vec)


def test_missing_key_returns_none(tmp_path: Path) -> None:
    """把未命中当成空向量返回，会让检索静默拿到全零向量。"""
    cache = EmbeddingCache(tmp_path / "cache.db")

    assert cache.get("never-written") is None


def test_put_is_idempotent(tmp_path: Path) -> None:
    """重复写入若报错，批量重试会整批失败。"""
    cache = EmbeddingCache(tmp_path / "cache.db")
    vec = _vec(1.0, 2.0)

    cache.put("key-a", vec)
    cache.put("key-a", vec)

    assert np.array_equal(cache.get("key-a"), vec)


def test_overwrite_replaces_value(tmp_path: Path) -> None:
    """若实现忽略覆盖，换了模型后旧向量会一直生效。"""
    cache = EmbeddingCache(tmp_path / "cache.db")
    cache.put("key-a", _vec(1.0))
    cache.put("key-a", _vec(2.0))

    loaded = cache.get("key-a")

    assert loaded is not None
    assert loaded[0] == pytest.approx(2.0)


def test_corrupt_blob_is_treated_as_miss_and_reported(tmp_path: Path) -> None:
    """损坏条目若直接崩溃，一个坏文件就会让整次评测跑不完。"""
    db = tmp_path / "cache.db"
    cache = EmbeddingCache(db)
    cache.put("key-a", _vec(1.0, 2.0))
    _corrupt(db, "key-a")

    loaded = cache.get("key-a")

    assert loaded is None
    assert cache.corrupt_keys == ["key-a"]


def test_corrupt_entry_can_be_rewritten(tmp_path: Path) -> None:
    """损坏条目必须可被正常写回覆盖，否则会永久失败。"""
    db = tmp_path / "cache.db"
    cache = EmbeddingCache(db)
    cache.put("key-a", _vec(1.0))
    _corrupt(db, "key-a")
    assert cache.get("key-a") is None

    cache.put("key-a", _vec(9.0))

    loaded = cache.get("key-a")
    assert loaded is not None
    assert loaded[0] == pytest.approx(9.0)
    assert cache.corrupt_keys == []


def test_get_many_preserves_input_order(tmp_path: Path) -> None:
    """顺序错位会让问题和向量错配，且完全不可见。"""
    cache = EmbeddingCache(tmp_path / "cache.db")
    cache.put("k1", _vec(1.0))
    cache.put("k3", _vec(3.0))

    result = cache.get_many(["k1", "k2", "k3"])

    assert result[0] is not None and result[0][0] == pytest.approx(1.0)
    assert result[1] is None
    assert result[2] is not None and result[2][0] == pytest.approx(3.0)


def test_put_many_writes_all(tmp_path: Path) -> None:
    """批量写入失败不应留下半批数据。"""
    cache = EmbeddingCache(tmp_path / "cache.db")

    cache.put_many({"k1": _vec(1.0), "k2": _vec(2.0)})

    assert cache.get("k1") is not None
    assert cache.get("k2") is not None


def test_stats_report_entry_count(tmp_path: Path) -> None:
    """--check-cache 需要条目数，取不到就无法判断缓存是否完整。"""
    cache = EmbeddingCache(tmp_path / "cache.db")
    cache.put("k1", _vec(1.0))
    cache.put("k2", _vec(2.0))

    assert cache.stats().entries == 2


def test_missing_keys_reports_gap(tmp_path: Path) -> None:
    """--check-cache 的缺失列表必须准确，否则门禁形同虚设。"""
    cache = EmbeddingCache(tmp_path / "cache.db")
    cache.put("k1", _vec(1.0))

    assert cache.missing_keys(["k1", "k2", "k3"]) == ["k2", "k3"]


def test_reopen_persists(tmp_path: Path) -> None:
    """若实现把缓存放在内存里，重跑必然全部未命中。"""
    db = tmp_path / "cache.db"
    EmbeddingCache(db).put("k1", _vec(1.0, 2.0))

    reopened = EmbeddingCache(db)

    assert reopened.get("k1") is not None
