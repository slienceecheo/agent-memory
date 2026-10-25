"""候选池构建。

检索指标要求"gold 在候选中排第几"，因此必须有一个大小大于 K 的候选池。
否则排名恒为 1，SEH@K 与 SRS 都失去意义。

三条硬约束：

1. **gold 必在池中**，否则该条无法评估
2. **所有条目的逻辑键互不相同**，否则写入 `SqliteStore` 时会撞 `ux_active`
   （实测：直接合并场景文件会有 17 个重复键）
3. **池大小必须大于 K**，否则 SEH 恒为 1
"""

from __future__ import annotations

import random
from dataclasses import dataclass

from memory.store.models import MemoryItem


class PoolTooSmall(ValueError):
    """候选池小于等于评估用的 K。"""


def _key(item: MemoryItem) -> tuple[str, str, str, str, str | None]:
    return (item.owner, item.scope.value, item.subject, item.relation, item.condition)


@dataclass(frozen=True, slots=True)
class CandidatePool:
    items: tuple[MemoryItem, ...]
    gold_id: str

    @property
    def gold_rank(self) -> int:
        """gold 在未排序池中的位置（从 1 开始）。"""
        for index, item in enumerate(self.items, start=1):
            if item.id == self.gold_id:
                return index
        raise ValueError(f"gold {self.gold_id!r} 不在候选池中")

    def validate_for_k(self, k: int) -> None:
        if len(self.items) <= k:
            raise PoolTooSmall(
                f"候选池只有 {len(self.items)} 条，而 K={k}。"
                "池大小必须严格大于 K，否则 SEH@K 恒为 1。"
            )


def build_pool(
    gold: MemoryItem,
    distractors: list[MemoryItem],
    *,
    seed: int = 0,
) -> CandidatePool:
    """构建 gold + 干扰项的候选池。

    干扰项按以下规则过滤：
    - 逻辑键与 gold 相同的排除（会撞唯一索引）
    - 逻辑键之间的重复去重（数据里确实存在重复）
    - 自身 id 与 gold 相同的排除

    打乱使用 `seed` + gold.id 的稳定哈希，使不同场景的 gold 落在不同位置。
    只用固定 seed 的话，相同长度的池会得到相同的排列——gold 位次恒定，
    等于没有排名空间。
    """
    seen = {_key(gold)}
    kept: list[MemoryItem] = []

    for item in distractors:
        if item.id == gold.id:
            continue
        key = _key(item)
        if key in seen:
            continue
        seen.add(key)
        kept.append(item)

    combined = [gold, *kept]
    rng = random.Random(f"{seed}:{gold.id}")
    rng.shuffle(combined)

    return CandidatePool(items=tuple(combined), gold_id=gold.id)
