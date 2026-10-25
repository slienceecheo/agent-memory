"""向量召回：暴力余弦。

**为什么不引入 ANN**：候选在 10^4 量级时，全库点积 < 5ms，
FAISS/HNSW 的收益为零，而代价是一个 C 依赖与 Windows 的 wheel 兼容问题。

**宣告的边界**：超过 10^6 条时应重构此层。这个数字写进文档，
而不是含糊地说"将来再优化"。

**维度必须校验**：审查指出静默跳过维度不符的行会掩盖损坏的 `vec_items`。
查询向量的维度错误要报错；单条候选的维度错误则跳过（它已经坏了，
不该让整个检索崩溃，但也不能假装正常）。
"""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np

from memory.store.models import MemoryItem
from memory.store.sqlite import SqliteStore


def recall_by_vector(
    store: SqliteStore,
    query_vector: Sequence[float],
    *,
    limit: int = 20,
) -> list[MemoryItem]:
    expected = store.embedding_dims()
    vector = np.asarray(query_vector, dtype=np.float32)
    if vector.shape != (expected,):
        raise ValueError(
            f"查询向量维度 {vector.shape} 与库声明 {expected} 不一致。"
            "维度不符时必须报错，否则会静默算出错误的相似度。"
        )

    norm = float(np.linalg.norm(vector))
    if norm == 0.0:
        return []

    rows = store.conn.execute(
        "SELECT v.item_id, v.vector FROM vec_items v"
        " JOIN items i ON i.id = v.item_id"
        " WHERE i.status = 'ACTIVE'"
    ).fetchall()
    if not rows:
        return []

    scored: list[tuple[float, str]] = []
    for item_id, blob in rows:
        candidate = np.frombuffer(blob, dtype=np.float32)
        if candidate.shape != (expected,):
            continue  # 损坏或维度不符的行：跳过，不让整个检索崩溃
        candidate_norm = float(np.linalg.norm(candidate))
        if candidate_norm == 0.0:
            continue
        score = float(np.dot(vector, candidate) / (norm * candidate_norm))
        scored.append((score, item_id))

    scored.sort(key=lambda pair: (-pair[0], pair[1]))
    return [store.get(item_id) for _, item_id in scored[:limit]]
