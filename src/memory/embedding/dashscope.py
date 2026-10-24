"""DashScope（OpenAI 兼容端点）embedding 实现。

三个必须做对的地方：
1. `text_type` 区分 document / query —— 实测同文本两者余弦仅 0.842。
2. 分片后顺序必须回到输入顺序。
3. 任一分片失败整体失败，且不能把半截结果写进缓存。
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Literal

import httpx
import numpy as np

from memory.config import Settings
from memory.embedding.cache import EmbeddingCache
from memory.embedding.cache_keys import cache_key

TextType = Literal["document", "query"]

_DEFAULT_MAX_BATCH = 10  # 官方标称 20，保守取 10


class DashScopeEmbedder:
    def __init__(
        self,
        *,
        settings: Settings,
        cache: EmbeddingCache,
        client: httpx.Client | None = None,
        max_batch: int = _DEFAULT_MAX_BATCH,
    ) -> None:
        if max_batch <= 0:
            raise ValueError("max_batch 必须为正整数")
        self._settings = settings
        self._cache = cache
        self._client = client or httpx.Client(
            timeout=60.0,
            proxy=settings.https_proxy or settings.http_proxy or None,
        )
        self._max_batch = max_batch
        self.network_calls = 0

    @property
    def cache(self) -> EmbeddingCache:
        return self._cache

    def _key(self, text: str, text_type: TextType) -> str:
        return cache_key(
            model=self._settings.embedding_model,
            dims=self._settings.embedding_dims,
            text_type=text_type,
            text=text,
        )

    def embed(self, text: str, *, text_type: TextType) -> np.ndarray:
        if text_type not in ("document", "query"):
            raise ValueError(f"text_type 只能是 document 或 query，收到 {text_type!r}")
        return self.embed_many([text], text_type=text_type)[0]

    def embed_query(self, text: str) -> np.ndarray:
        return self.embed(text, text_type="query")

    def embed_documents(self, texts: Sequence[str]) -> list[np.ndarray]:
        return self.embed_many(list(texts), text_type="document")

    def embed_many(self, texts: Sequence[str], *, text_type: TextType) -> list[np.ndarray]:
        if text_type not in ("document", "query"):
            raise ValueError(f"text_type 只能是 document 或 query，收到 {text_type!r}")
        if not texts:
            return []

        keys = [self._key(text, text_type) for text in texts]
        cached = self._cache.get_many(keys)

        pending: dict[str, str] = {}
        for key, text, vector in zip(keys, texts, cached, strict=True):
            if vector is None and key not in pending:
                pending[key] = text

        if pending:
            fresh = self._fetch(list(pending.values()), text_type=text_type)
            self._cache.put_many(dict(zip(pending.keys(), fresh, strict=True)))

        filled = self._cache.get_many(keys)
        missing = [key for key, vector in zip(keys, filled, strict=True) if vector is None]
        if missing:
            raise RuntimeError(f"缓存写入后仍有 {len(missing)} 条缺失，疑似持久化失败")
        return [vector for vector in filled if vector is not None]

    def _fetch(self, texts: list[str], *, text_type: TextType) -> list[np.ndarray]:
        """按批发送；任一批失败即抛出，不返回部分结果。"""
        collected: list[np.ndarray] = []
        for start in range(0, len(texts), self._max_batch):
            chunk = texts[start : start + self._max_batch]
            collected.extend(self._fetch_one(chunk, text_type=text_type))
        return collected

    def _fetch_one(self, chunk: list[str], *, text_type: TextType) -> list[np.ndarray]:
        payload = {
            "model": self._settings.embedding_model,
            "input": chunk,
            "dimensions": self._settings.embedding_dims,
            "encoding_format": "float",
            "text_type": text_type,
        }
        self.network_calls += 1
        response = self._client.post(
            f"{self._settings.embedding_base_url.rstrip('/')}/embeddings",
            headers={
                "Authorization": f"Bearer {self._settings.dashscope_api_key}",
                "Content-Type": "application/json",
            },
            json=payload,
        )
        response.raise_for_status()
        body = response.json()

        entries = sorted(body["data"], key=lambda item: item["index"])
        if len(entries) != len(chunk):
            raise RuntimeError(f"服务端返回 {len(entries)} 条向量，请求了 {len(chunk)} 条")

        expected = self._settings.embedding_dims
        vectors: list[np.ndarray] = []
        for entry in entries:
            vector = np.asarray(entry["embedding"], dtype=np.float32)
            if vector.shape != (expected,):
                raise ValueError(
                    f"向量维度不符：期望 {expected}，实际 {vector.shape}。"
                    "请检查 EMBEDDING_DIMS 与模型是否匹配。"
                )
            vectors.append(vector)
        return vectors
