"""为单个 subject 计算样例交付物：池大小与随机排序基线。

这是 F8 的小规模版：**随机排序的 SEH@5 必须 < 1.0**，
否则说明池里只有 1 条候选，指标是死的（C4 缺陷 3）。

用法：
    uv run --no-sync python -m evals.tools.sample_pool_check
"""

from __future__ import annotations

import json
import random
import statistics
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SAMPLE = ROOT / "data" / "retrieval-v2" / "sample"
K = 5
TRIALS = 200


def _rows(path: Path) -> list[dict[str, object]]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def build_pool_for(
    query: dict[str, object],
    memories: list[dict[str, object]],
) -> list[dict[str, object]]:
    """模拟真实池构造：同 subject 下的全部记忆都进池。

    与 C4 不同，这里**不按逻辑键排除**——v2 的难度正来自同 relation
    的多条分支必须互相竞争。
    """
    subject = query["subject"]
    return [m for m in memories if m["subject"] == subject]


def build_competition_set(
    query: dict[str, object],
    memories: list[dict[str, object]],
) -> list[dict[str, object]]:
    """按轴定义的**竞争集**。

    - **A 轴**：同 subject + 同 relation 的分支（3–5 条）。
      它们全部落在前 5 名内，所以 `SEH@5` 恒为 1.000——
      这不是满分，是空操作。A 轴必须看 `SEH@1`。
    - **C 轴**：同 subject 的**全部**记忆。C 轴的难度是"在多个不同 relation
      之间挑对"，所以竞争面是整库而不是单个 relation——
      按 relation 收窄会让竞争集退化为 1 条，指标同样失效。
    """
    gold = next(
        (m for m in memories if m["memory_id"] == query["gold_memory_id"]), None
    )
    if gold is None:
        return []

    subject_pool = [m for m in memories if m["subject"] == gold["subject"]]
    if query["axis"] == "A":
        return [m for m in subject_pool if m["relation"] == gold["relation"]]
    return subject_pool


def main() -> int:
    memories = _rows(SAMPLE / "memories.jsonl")
    queries = _rows(SAMPLE / "queries.jsonl")

    print(f"memories={len(memories)} queries={len(queries)}")
    print()

    sizes: list[int] = []
    expected_at_5 = 0.0
    expected_at_1 = 0.0
    rng = random.Random(0)

    for query in queries:
        pool = build_pool_for(query, memories)
        sizes.append(len(pool))
        gold = query["gold_memory_id"]
        gold_in_pool = any(m["memory_id"] == gold for m in pool)
        if not gold_in_pool:
            print(f"  !! {query['query_id']}: gold {gold} 不在池中")
            continue

        # 随机排序 N 次，取**期望命中率**而不是"是否过半命中"。
        # 用阈值判定会把 0.417 的期望值压成 0.0——那是测量方法的错误，
        # 不是基线的真实值。
        local_at_5 = 0
        local_at_1 = 0
        for _ in range(TRIALS):
            shuffled = pool[:]
            rng.shuffle(shuffled)
            rank = next(
                i for i, m in enumerate(shuffled, start=1) if m["memory_id"] == gold
            )
            if rank <= K:
                local_at_5 += 1
            if rank == 1:
                local_at_1 += 1
        expected_at_5 += local_at_5 / TRIALS
        expected_at_1 += local_at_1 / TRIALS

    n = len(queries)
    random_seh5 = expected_at_5 / n
    random_seh1 = expected_at_1 / n

    print(f"池大小: min={min(sizes)} max={max(sizes)} "
          f"mean={statistics.mean(sizes):.1f}")
    print(f"随机 SEH@5（期望）: {random_seh5:.4f}")
    print(f"随机 SEH@1（期望）: {random_seh1:.4f}")
    print()
    mean_size = statistics.mean(sizes)
    print(f"理论随机值: K/N，N≈{mean_size:.0f} -> "
          f"SEH@5≈{min(1.0, K / mean_size):.3f}")
    print()

    # 按轴分别算：A 轴的分支数 ≤ K，SEH@5 必然饱和，必须看 SEH@1。
    print("=== 按轴（关键）===")
    for axis in ("A", "C"):
        axis_queries = [q for q in queries if q["axis"] == axis]
        if not axis_queries:
            continue
        a5 = a1 = 0.0
        branch_sizes = []
        for query in axis_queries:
            competition = build_competition_set(query, memories)
            branch_sizes.append(len(competition))
            gold = query["gold_memory_id"]
            for _ in range(TRIALS):
                shuffled = competition[:]
                rng.shuffle(shuffled)
                rank = next(
                    i for i, m in enumerate(shuffled, start=1) if m["memory_id"] == gold
                )
                if rank <= K:
                    a5 += 1
                if rank == 1:
                    a1 += 1
        trials_total = TRIALS * len(axis_queries)
        print(
            f"  轴 {axis}: n={len(axis_queries)} "
            f"竞争集={min(branch_sizes)}..{max(branch_sizes)} "
            f"随机 SEH@5={a5 / trials_total:.3f} SEH@1={a1 / trials_total:.3f}"
        )
        if axis == "A" and a5 / trials_total >= 1.0:
            print(
                "  ^ 注意：A 轴 SEH@5 饱和（竞争集 ≤ K），"
                "A 轴指标必须用 SEH@1"
            )
    print()

    if random_seh5 >= 1.0:
        print("FAIL: 随机排序 SEH@5 = 1.0，池是死的")
        return 1
    if abs(random_seh5 - min(1.0, K / mean_size)) > 0.05:
        print(
            f"FAIL: 实测随机 SEH@5={random_seh5:.3f} 与理论值 "
            f"{min(1.0, K / mean_size):.3f} 偏差过大，指标实现有问题"
        )
        return 1
    print("OK: 全池随机基线 < 1.0 且与理论值吻合（F8 小规模版通过）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
