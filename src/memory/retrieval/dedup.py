"""等义去重。

这是语义等价判断的**唯一消费者**。没有它，等价判断不可能改变任何被测量的结果。

规则：
- 只比较前 `top_k` 条内部的两两配对（`top_k` 默认 5 → 最多 10 对）
- 判为"等义"的一对只保留融合分更高者
- 判为"互补"的**不合并**——互补意味着两者都有价值，合并会丢信息
- 判断失败时保守不合并

产出必须可观测：`DedupStats.before` 与 `.after` 的差就是去重的实际效果。
"""

from __future__ import annotations

from dataclasses import dataclass
from itertools import combinations

from memory.retrieval.equivalence import Equivalence, EquivalenceJudge


@dataclass(frozen=True, slots=True)
class DedupStats:
    before: int
    after: int
    compared: int
    merged: int

    @property
    def reduction(self) -> int:
        return self.before - self.after


def dedup(
    ranked: list[tuple[str, str, float]],
    *,
    judge: EquivalenceJudge,
    top_k: int = 5,
) -> tuple[list[tuple[str, str, float]], DedupStats]:
    """对前 `top_k` 条做等义合并。

    参数：
        ranked: `(item_id, text, score)` 列表。**函数内部会按分数降序排序**，
                不依赖调用方保证顺序——顺序错会导致保留错的那一条。
        judge: 等价判断器（可能有缓存与开关）
        top_k: 参与比较的范围

    返回：
        合并后的列表（按分数降序）与统计
    """
    ordered = sorted(ranked, key=lambda entry: (-entry[2], entry[0]))
    before = len(ordered)
    window = ordered[:top_k]

    dropped: set[str] = set()
    compared = 0

    for (id_a, text_a, _), (id_b, text_b, _) in combinations(window, 2):
        if id_a in dropped or id_b in dropped:
            continue
        if not judge.enabled:
            break
        compared += 1
        result = judge.judge(text_a, text_b)
        if result.equivalence is not Equivalence.EQUIVALENT:
            continue
        # 两个都判为等义时保留分数更高的：`ordered` 已降序，先出现的更高
        dropped.add(id_b)

    kept = [entry for entry in ordered if entry[0] not in dropped]
    stats = DedupStats(
        before=before,
        after=len(kept),
        compared=compared,
        merged=len(dropped),
    )
    return kept, stats


__all__ = ["DedupStats", "dedup"]
