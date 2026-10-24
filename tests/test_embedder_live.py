"""真实网络冒烟测试。

默认被 `-m 'not network'` 排除。手动运行：
    uv run pytest tests/test_embedder_live.py -q -m network

它验证的是"我们的配置与真实服务对得上"，而不是业务逻辑——
所以只断言维度、确定性与 text_type 的影响方向。
"""

from __future__ import annotations

import numpy as np
import pytest

from memory.config import Settings
from memory.embedding.cache import EmbeddingCache
from memory.embedding.dashscope import DashScopeEmbedder


@pytest.fixture
def live_embedder(tmp_path) -> DashScopeEmbedder:
    settings = Settings.load()
    return DashScopeEmbedder(
        settings=settings,
        cache=EmbeddingCache(tmp_path / "cache.db"),
    )


@pytest.mark.network
def test_embedding_live_returns_configured_dims(live_embedder: DashScopeEmbedder) -> None:
    vector = live_embedder.embed_query("项目使用 pnpm 作为包管理器")

    assert vector.shape == (live_embedder._settings.embedding_dims,)
    assert vector.dtype == np.float32
    assert float(np.linalg.norm(vector)) > 0


@pytest.mark.network
def test_query_and_document_encodings_differ(live_embedder: DashScopeEmbedder) -> None:
    """若 text_type 被服务端忽略，两者会完全相同，我们的一条核心设计前提就不成立。"""
    text = "开会我喜欢早上"
    as_query = live_embedder.embed_query(text)
    as_document = live_embedder.embed_documents([text])[0]

    cosine = float(
        np.dot(as_query, as_document)
        / (np.linalg.norm(as_query) * np.linalg.norm(as_document))
    )
    assert cosine < 0.999, f"query 与 document 编码几乎相同（cos={cosine}），text_type 可能未生效"
