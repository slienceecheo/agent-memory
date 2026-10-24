"""--check-cache 的门禁行为。

这个命令是 A2/A3 的执行入口，必须有明确的退出码语义：
完整=0，缺失/损坏/为空=非零。
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from evals.run import main

from memory.config import Settings
from memory.embedding.cache import EmbeddingCache
from memory.llm.cache import CachedResponse, ResponseCache
from memory.llm.sse import Usage


def _settings(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Settings:
    for key, value in {
        "DASHSCOPE_API_KEY": "sk-test",
        "LLM_BASE_URL": "http://127.0.0.1:3211/api/open-platform-model/v1",
        "LLM_API_KEY": "local",
        "LLM_MODEL": "deepseek-v4.1-flash",
        "EMBEDDING_BASE_URL": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "EMBEDDING_MODEL": "qwen3.7-text-embedding-flash",
        "EMBEDDING_DIMS": "4",
        "MEMORY_CACHE_DIR": str(tmp_path),
    }.items():
        monkeypatch.setenv(key, value)
    return Settings.from_env()


def test_missing_cache_exits_nonzero(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """缓存文件不存在时返回 0 会让门禁永远通过。"""
    _settings(tmp_path, monkeypatch)

    code = main(["--check-cache"])

    assert code != 0


def test_empty_cache_exits_nonzero(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """缓存未建表但存在时，条目数为 0；这也不算"完整"。"""
    _settings(tmp_path, monkeypatch)
    EmbeddingCache(tmp_path / "cache.db").close()

    code = main(["--check-cache"])

    assert code != 0


def test_complete_cache_exits_zero(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """这是 A2 的正例：两种缓存都有条目且无损坏时必须通过。"""
    _settings(tmp_path, monkeypatch)
    emb = EmbeddingCache(tmp_path / "cache.db")
    emb.put("k1", np.asarray([1.0, 2.0, 3.0, 4.0], dtype=np.float32))
    emb.close()
    responses = ResponseCache(tmp_path / "responses.db")
    responses.put(
        "r1",
        CachedResponse(content="x", usage=Usage(), finish_reason="stop", tool_calls=()),
    )
    responses.close()

    code = main(["--check-cache"])

    assert code == 0


def test_missing_llm_cache_exits_nonzero(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """只有 embedding 缓存不够：没有 LLM 缓存，重跑结果必然不同。"""
    _settings(tmp_path, monkeypatch)
    emb = EmbeddingCache(tmp_path / "cache.db")
    emb.put("k1", np.asarray([1.0, 2.0, 3.0, 4.0], dtype=np.float32))
    emb.close()

    code = main(["--check-cache"])

    assert code != 0


def test_corrupt_entry_exits_nonzero(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """损坏条目若被忽略，评测会拿到错误向量而不自知。"""
    import sqlite3

    _settings(tmp_path, monkeypatch)
    db = tmp_path / "cache.db"
    cache = EmbeddingCache(db)
    cache.put("k1", np.asarray([1.0, 2.0, 3.0, 4.0], dtype=np.float32))
    cache.get("k1")
    cache.close()
    conn = sqlite3.connect(str(db))
    with conn:
        conn.execute("UPDATE embeddings SET vector = x'00' WHERE key = 'k1'")
    conn.close()

    reopened = EmbeddingCache(db)
    assert reopened.get("k1") is None
    reopened.close()

    code = main(["--check-cache"])

    assert code != 0
