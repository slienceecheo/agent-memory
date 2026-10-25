"""词面召回。

包装 C2 的 `search_text`：它已按 BM25 排序、索引原文、只返回 ACTIVE。
本模块只做一层薄封装，保证三路召回的签名一致。
"""

from __future__ import annotations

from memory.store.models import MemoryItem
from memory.store.sqlite import SqliteStore


def recall_by_lexical(
    store: SqliteStore, query: str, *, limit: int = 20
) -> list[MemoryItem]:
    """按 BM25 相关性召回。

    空查询返回空列表而不是全表——否则"没问任何东西"会变成"什么都相关"。
    """
    if not query.strip():
        return []
    return store.search_text(query, limit=limit)
