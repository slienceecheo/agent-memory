"""embedding 磁盘缓存。

用 SQLite 而不是文件树：
- 自带事务，批量写入要么全成要么全败
- 单文件，方便 `--check-cache` 与提交进仓库
- 键是 64 位十六进制串，天然适合做主键

向量按 float32 裸字节存储，读取时校验长度是否与 dtype 匹配：
长度不对说明条目损坏（例如被截断），视为未命中而不是抛错——
一个坏条目不该让整次评测跑不完。
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path

import numpy as np

_SCHEMA = """
CREATE TABLE IF NOT EXISTS embeddings (
    key    TEXT PRIMARY KEY,
    vector BLOB NOT NULL,
    dims   INTEGER NOT NULL
);
"""

_DTYPE = np.float32


@dataclass(frozen=True, slots=True)
class CacheStats:
    entries: int


class EmbeddingCache:
    """一个键 → 一个 float32 向量的持久化映射。"""

    def __init__(self, path: Path | str) -> None:
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self._path))
        self._conn.execute(_SCHEMA)
        self._conn.commit()
        self.corrupt_keys: list[str] = []

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> EmbeddingCache:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    def put(self, key: str, vector: np.ndarray) -> None:
        self.put_many({key: vector})

    def put_many(self, items: dict[str, np.ndarray]) -> None:
        """单事务写入，避免半批数据。"""
        rows = [
            (key, np.asarray(vector, dtype=_DTYPE).tobytes(), int(np.asarray(vector).shape[-1]))
            for key, vector in items.items()
        ]
        with self._conn:
            self._conn.executemany(
                "INSERT INTO embeddings (key, vector, dims) VALUES (?, ?, ?) "
                "ON CONFLICT(key) DO UPDATE SET vector = excluded.vector, dims = excluded.dims",
                rows,
            )
        if self.corrupt_keys:
            written = set(items)
            self.corrupt_keys = [key for key in self.corrupt_keys if key not in written]

    def get(self, key: str) -> np.ndarray | None:
        row = self._conn.execute(
            "SELECT vector, dims FROM embeddings WHERE key = ?", (key,)
        ).fetchone()
        if row is None:
            return None

        blob, dims = row
        vector = self._decode(key, blob, dims)
        return vector

    def get_many(self, keys: list[str]) -> list[np.ndarray | None]:
        return [self.get(key) for key in keys]

    def stats(self) -> CacheStats:
        (count,) = self._conn.execute("SELECT COUNT(*) FROM embeddings").fetchone()
        return CacheStats(entries=int(count))

    def verify_all(self) -> tuple[int, list[str]]:
        """全量校验所有条目，返回 (检查条目数, 损坏键列表)。

        `get()` 只在被读取时才发现损坏；`--check-cache` 必须主动扫描，
        否则一个从未被读过的坏条目会静默通过门禁。
        """
        rows = self._conn.execute("SELECT key, vector, dims FROM embeddings").fetchall()
        corrupt: list[str] = []
        for key, blob, dims in rows:
            if self._decode(key, blob, dims) is None:
                corrupt.append(key)
        return len(rows), corrupt

    def missing_keys(self, keys: list[str]) -> list[str]:
        return [key for key in keys if self.get(key) is None]

    def _decode(self, key: str, blob: bytes, dims: int) -> np.ndarray | None:
        expected = dims * np.dtype(_DTYPE).itemsize
        if dims <= 0 or len(blob) != expected:
            if key not in self.corrupt_keys:
                self.corrupt_keys.append(key)
            return None
        return np.frombuffer(blob, dtype=_DTYPE).copy()
