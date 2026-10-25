"""Reciprocal Rank Fusion。

`score(d) = Σ_i 1 / (k + rank_i(d))`，其中 `rank_i` 从 1 开始。

**为什么只用排名**：BM25 分数无界、余弦有界，加权前必须归一化，
而归一化参数随数据集漂移。RRF 跨数据集稳定，代价是丢掉"差多少"。

**为什么默认 k=60**：这是原论文的经验值。k 越大，排名差异被压得越平，
多路共识的优势越弱；k 越小则相反。本变更会做 k ∈ {30, 60, 100} 的对照。
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

DEFAULT_K = 60


@dataclass(frozen=True, slots=True)
class Fused:
    item_id: str
    score: float
    ranks: dict[str, int] = field(default_factory=dict)

    @property
    def sources(self) -> tuple[str, ...]:
        return tuple(sorted(self.ranks))


def rrf(
    ranked_lists: Mapping[str, Sequence[str]],
    *,
    k: int = DEFAULT_K,
) -> list[Fused]:
    """融合多路排名。

    参数：
        ranked_lists: 路径名 -> 按相关性降序的 id 列表
        k: RRF 常数

    同一列表内的重复 id 只计首次出现（否则会人为抬高分数）。
    """
    if k <= 0:
        raise ValueError(f"k 必须为正整数，收到 {k}")

    scores: dict[str, float] = {}
    ranks: dict[str, dict[str, int]] = {}

    for source, ids in ranked_lists.items():
        seen: set[str] = set()
        for position, item_id in enumerate(ids, start=1):
            if item_id in seen:
                continue
            seen.add(item_id)
            scores[item_id] = scores.get(item_id, 0.0) + 1.0 / (k + position)
            ranks.setdefault(item_id, {})[source] = position

    ordered = sorted(scores.items(), key=lambda pair: (-pair[1], pair[0]))
    return [
        Fused(item_id=item_id, score=score, ranks=ranks[item_id])
        for item_id, score in ordered
    ]
