"""v2 数据集的竞争集与随机基线。

**为什么单独成一个模块**：C4 的随机基线从来没被算过，所以"池大小 > K"
被当成了"排名有意义"。实测 independent 上 26/26 条召回集只有 1 条候选，
`SEH` 恒为 1——那不是满分，是空操作（C4 缺陷 3）。

竞争集的定义决定指标有没有意义，所以它必须是**显式函数**：

| 轴 | 竞争集 | 语义 |
|---|---|---|
| A | 同 subject、**同 relation** 的全部记忆 | "多个条件分支里挑对那一条" |
| C | 同 subject 的**全部**记忆 | "这个人多条事实里挑中问的那条" |
| mixed | 同上两者并集（= C，因为 C 已含全部同 subject） | — |

A 轴的竞争集只有 3–5 条，**小于 K=5 时 `SEH@5` 数学上必然等于 1**。
这不是"可能饱和"，是恒等。所以 A 轴的主指标必须是 `SEH@1`。
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass

from evals.datasets.retrieval_v2 import Axis, Dataset, Memory, Query

DEFAULT_K = 5


@dataclass(frozen=True, slots=True)
class AxisBaseline:
    """某个轴上的随机排序期望值。"""

    axis: Axis
    queries: int
    mean_pool_size: float
    seh_at_1: float
    seh_at_k: float
    k: int

    @property
    def saturates_at_k(self) -> bool:
        """随机排序已经拿到满分——该轴上 K 这个指标没有区分力。"""
        return self.seh_at_k >= 1.0 - 1e-9


def competing_set(dataset: Dataset, query: Query) -> tuple[Memory, ...]:
    """一条查询的竞争集：候选池里"可能答错"的那些条目。

    这是**唯一**的竞争集定义。报告、门禁、随机基线都必须用它，
    否则"池大小"与"排名空间"会各说各话（C4 就是这么失去意义的）。
    """
    gold = dataset.memory(query.gold_memory_id)

    if query.axis is Axis.A:
        return tuple(
            m for m in dataset.memories if m.subject == gold.subject and m.relation == gold.relation
        )

    # C 与 mixed 都用"同 subject 全部记忆"：C 轴要区分的是属性，
    # 而同 subject 的其他属性才是真正的干扰项。
    return tuple(m for m in dataset.memories if m.subject == gold.subject)


def random_seh_at_1(pool_size: int) -> float:
    """随机排序下 gold 排第 1 的概率 = 1/N。"""
    if pool_size <= 0:
        return 0.0
    return 1.0 / pool_size


def random_seh_at_k(pool_size: int, k: int = DEFAULT_K) -> float:
    """随机排序下 gold 进入前 K 的概率 = min(K,N)/N。

    N <= K 时为 1.0——**这不是成绩好，是没有排名空间**。
    """
    if pool_size <= 0:
        return 0.0
    return min(k, pool_size) / pool_size


def random_mrr(pool_size: int) -> float:
    """随机排序下 MRR 的期望 = H_N / N。"""
    if pool_size <= 0:
        return 0.0
    return sum(1.0 / rank for rank in range(1, pool_size + 1)) / pool_size


def axis_baseline(
    dataset: Dataset, axis: Axis, *, k: int = DEFAULT_K
) -> AxisBaseline:
    """某个轴上、按该轴竞争集算出的随机排序期望值。

    **逐条查询算再平均**，不是"平均池大小再套公式"——
    两者在池大小不一时不相等，前者才是真实期望。
    """
    selected = [q for q in dataset.queries if q.axis is axis]
    if not selected:
        return AxisBaseline(
            axis=axis, queries=0, mean_pool_size=0.0, seh_at_1=0.0, seh_at_k=0.0, k=k
        )

    sizes = [len(competing_set(dataset, q)) for q in selected]
    return AxisBaseline(
        axis=axis,
        queries=len(selected),
        mean_pool_size=sum(sizes) / len(sizes),
        seh_at_1=sum(random_seh_at_1(n) for n in sizes) / len(sizes),
        seh_at_k=sum(random_seh_at_k(n, k) for n in sizes) / len(sizes),
        k=k,
    )


def all_axis_baselines(dataset: Dataset, *, k: int = DEFAULT_K) -> dict[str, AxisBaseline]:
    return {axis.value: axis_baseline(dataset, axis, k=k) for axis in Axis}


def derived_axis_of(dataset: Dataset, query: Query) -> str:
    """按池结构派生一条查询的轴：`relation_within` / `relation_cross`。

    与 `derive_axis` 同义，但作用于数据集全集（而不是构造出来的池）。
    `n_competitors` = 同 subject 同 relation 的其他记忆数（不含 gold）。
    """
    gold = dataset.memory(query.gold_memory_id)
    n = sum(
        1
        for m in dataset.memories
        if m.memory_id != gold.memory_id
        and m.subject == gold.subject
        and m.relation == gold.relation
    )
    return "relation_within" if n > 0 else "relation_cross"


def axis_baseline_derived(dataset: Dataset) -> dict[str, float]:
    """按**派生轴**分组算随机基线（`SEH@1`）。

    **核心**：`N` MUST 从 `competing_set()` 取，MUST NOT 由 `n_competitors + 1` 推算。

    实测 `n_competitors + 1 == len(competing_set)` 在 5 条查询上不成立
    （全部是 C 轴）：

    | 查询 | `n_competitors` | `competing_set` | `n+1` |
    |---|---|---|---|
    | `ledger-q11/q12` | 0 | **12** | 1 |
    | `billing-c1/c2/c3` | 2 | **9** | 3 |

    按 `n+1` 推会让 cross 基线变成 `1/1 = 1.0`（随机也满分），
    **与真值 `1/12 = 0.0833` 差 12 倍**——任何实测值都"不高于基线"，判据失效。

    **验收**（现有 v2 数据）：

    ```
    axis_baseline_derived(sample) ==
        {"relation_within": 0.3000, "relation_cross": 0.0833}
    ```
    """
    groups: dict[str, list[float]] = {
        "relation_within": [],
        "relation_cross": [],
    }

    for query in dataset.queries:
        axis = derived_axis_of(dataset, query)
        # **N 从竞争集取**，不推公式
        n = len(competing_set(dataset, query))
        groups[axis].append(random_seh_at_1(n))

    return {
        axis: (sum(values) / len(values) if values else 0.0)
        for axis, values in groups.items()
    }


def axis_label_mismatches(dataset: Dataset) -> dict[str, int]:
    """标注轴与派生轴的不一致数。

    **可追溯性来自报告写不写这个数字，不来自门禁用哪套轴。**

    实测基线：`sample` 0/12、`billing` 3/12
    （`billing-c1/c2/c3` 标注为 C，池结构上是 within）。
    """
    mismatch = 0
    for query in dataset.queries:
        derived = derived_axis_of(dataset, query)
        labeled = (
            "relation_within" if query.axis is Axis.A else "relation_cross"
        )
        if derived != labeled:
            mismatch += 1
    return {"mismatch": mismatch, "total": len(dataset.queries)}


def monte_carlo_seh(
    dataset: Dataset,
    axis: Axis,
    *,
    k: int = DEFAULT_K,
    trials: int = 20000,
    seed: int = 0,
) -> tuple[float, float]:
    """随机重排的实测命中率，用于验证 `random_seh_*` 的公式没写错。

    返回 `(seh_at_1, seh_at_k)`。

    **必须用期望命中率，不能用"多数试验是否命中"这类阈值判定**：
    阈值会把 A 轴 0.30 压成 0，而那看起来像是"随机基线为 0"，不是"算错了"。
    """
    selected = [q for q in dataset.queries if q.axis is axis]
    if not selected:
        return 0.0, 0.0

    rng = random.Random(seed)
    hit1 = hitk = 0
    total = 0
    for query in selected:
        pool = list(competing_set(dataset, query))
        for _ in range(trials):
            rng.shuffle(pool)
            # 打乱后按 memory_id 重新定位 gold。不能用打乱前的下标——
            # 那个下标在 shuffle 之后指向的是别的条目，会把命中率压成 0。
            rank = (
                next(
                    i for i, m in enumerate(pool) if m.memory_id == query.gold_memory_id
                )
                + 1
            )
            hit1 += rank <= 1
            hitk += rank <= k
            total += 1

    return hit1 / total, hitk / total


def required_pool_size_for(k: int, target_saturation: float = 0.95) -> int:
    """要让随机 `SEH@k` 低于 `target_saturation`，池至少要多长。

    用来说明"为什么 A 轴不能用 SEH@5"：K=5、要求随机基线 < 0.95 时，
    池至少要 6 条——而 A 轴天然只有 3–5 个分支。
    """
    if not 0.0 < target_saturation < 1.0:
        raise ValueError(f"target_saturation 必须在 (0,1)，收到 {target_saturation}")
    return max(k, math.ceil(k / target_saturation))


__all__ = [
    "DEFAULT_K",
    "AxisBaseline",
    "all_axis_baselines",
    "axis_baseline",
    "competing_set",
    "monte_carlo_seh",
    "random_mrr",
    "random_seh_at_1",
    "random_seh_at_k",
    "required_pool_size_for",
]
