"""检索指标与失败归因。

**SEH@K 与 SRS 必须分开报告**：
两个系统都让 gold 进前 5，但一个排第 1、另一个排第 5，能力完全不同。
只报 SEH 会把这个差异抹平。

**归因必须规则化、不调用模型**：归因结果要进报告，必须可复算。
模型归因会引入第二层不确定性——"归因错了"比"检索错了"更难发现。

三类归因（互斥且完备）：

| 类 | 判定 |
|---|---|
| `NOT_IN_POOL` | gold 不在候选池（池构建问题） |
| `LOW_RANK` | gold 在池中，但融合后排名就 > K |
| `RERANK_DROPPED` | 融合后在 K 内，被重排挤出 K |

**只统计检索失败**，不复用 C3 的判定错误——那是写路径的问题。
"""

from __future__ import annotations

from enum import StrEnum


class Attribution(StrEnum):
    NOT_IN_POOL = "NOT_IN_POOL"
    LOW_RANK = "LOW_RANK"
    RERANK_DROPPED = "RERANK_DROPPED"


def seh_at_k(*, rank: int | None, k: int) -> bool:
    """gold 是否进入前 K。`rank` 为 None 表示未召回。"""
    if k <= 0:
        raise ValueError(f"k 必须为正整数，收到 {k}")
    if rank is None:
        return False
    return 1 <= rank <= k


def srs(*, rank: int | None) -> float:
    """Success Rank Score = 1/rank；未召回为 0。

    **定义必须唯一**：`1/rank`、`1-(rank-1)/N`、`1-rank/N` 三种都会让中间排名
    顺序一致但数值不同，跨查询不可比。这里固定用 `1/rank`。
    """
    if rank is None:
        return 0.0
    if rank < 1:
        raise ValueError(f"rank 从 1 开始，收到 {rank}")
    return 1.0 / rank


def attribute_failure(
    *,
    gold_in_pool: bool,
    rank_after_fusion: int | None,
    rank_after_rerank: int | None,
    k: int,
) -> Attribution | None:
    """归因一条样本。成功（gold 进入重排后前 K）返回 None。

    判定顺序：先看池，再看融合，最后看重排。
    这是**显式的优先级**，避免三类同时命中。
    """
    if not gold_in_pool or rank_after_fusion is None:
        return Attribution.NOT_IN_POOL

    if rank_after_fusion > k:
        return Attribution.LOW_RANK

    if rank_after_rerank is None or rank_after_rerank > k:
        return Attribution.RERANK_DROPPED

    return None


def attribution_breakdown(
    results: list[Attribution | None],
) -> dict[str, int]:
    """统计三类失败的计数。

    返回的字典**包含全部三个键**（即使计数为 0），
    否则报告的表格在某一类缺席时会取不到值。
    """
    counts = {kind.value: 0 for kind in Attribution}
    for result in results:
        if result is None:
            continue
        counts[result.value] += 1
    return counts
