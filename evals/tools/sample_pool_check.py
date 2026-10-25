"""为单个 subject 计算样例交付物：池大小与随机排序基线。

这是 F8 的小规模版：**随机排序的 SEH@5 必须 < 1.0**，
否则说明池里只有 1 条候选，指标是死的（C4 缺陷 3）。

**本脚本只做"池与基线"这一件事。** 反泄漏与 F 门禁由
`evals/tools/check_v2_dataset.py` 负责，竞争集定义复用
`evals/metrics/v2_baselines.py::competing_set`——不在这里另写一套，
否则"池大小"与"排名空间"会各说各话（C4 就是这么失去意义的）。

用法：
    uv run --no-sync python -m evals.tools.sample_pool_check
"""

from __future__ import annotations

import statistics
from pathlib import Path

from evals.datasets.retrieval_v2 import Axis, load_dataset
from evals.metrics.v2_baselines import (
    axis_baseline,
    competing_set,
    monte_carlo_seh,
    random_seh_at_1,
    random_seh_at_k,
)

ROOT = Path(__file__).resolve().parents[2]
SAMPLE = ROOT / "data" / "retrieval-v2" / "sample"
K = 5


def main() -> int:
    dataset = load_dataset(SAMPLE)
    queries = dataset.queries

    print(f"memories={len(dataset.memories)} queries={len(queries)}")
    print()

    sizes = [len(competing_set(dataset, q)) for q in queries]
    print(
        f"竞争集: min={min(sizes)} max={max(sizes)} mean={statistics.mean(sizes):.2f}"
    )

    # 逐查询取精确期望再平均，不套"平均池大小"的单一常数：
    # 池大小不一时两者不相等，前者才是真实期望。
    seh1 = sum(random_seh_at_1(n) for n in sizes) / len(sizes)
    seh5 = sum(random_seh_at_k(n, K) for n in sizes) / len(sizes)
    print(f"随机 SEH@5（期望）: {seh5:.4f}")
    print(f"随机 SEH@1（期望）: {seh1:.4f}")
    print()

    print("=== 按轴（关键）===")
    saturated_axes: list[str] = []
    for axis in Axis:
        base = axis_baseline(dataset, axis, k=K)
        if base.queries == 0:
            continue
        mc1, mc5 = monte_carlo_seh(dataset, axis, k=K, trials=20000, seed=0)
        print(
            f"  轴 {axis.value}: n={base.queries} "
            f"竞争集均值={base.mean_pool_size:.2f} "
            f"随机 SEH@5={base.seh_at_k:.4f} SEH@1={base.seh_at_1:.4f} "
            f"｜MC 复核 @5={mc5:.4f} @1={mc1:.4f}"
        )
        if base.saturates_at_k:
            saturated_axes.append(axis.value)
            print(
                f"  ^ {axis.value} 轴 SEH@5 饱和（竞争集 ≤ K={K}），"
                f"该轴主指标必须用 SEH@1"
            )
        if abs(mc1 - base.seh_at_1) > 0.02 or abs(mc5 - base.seh_at_k) > 0.02:
            print(f"  FAIL: {axis.value} 轴实测与公式偏差 > 0.02，指标实现有问题")
            return 1
    print()

    if seh5 >= 1.0:
        print("FAIL: 全池随机 SEH@5 = 1.0，池是死的")
        return 1
    if not saturated_axes:
        print("NOTE: 没有轴饱和；无需强制 SEH@1")
    print("OK: 随机基线与公式吻合（F16），饱和轴已标记（F15）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

