"""Wilson 区间：比例的正态近似修正，小样本下仍保留不确定性。

**为什么不用 bootstrap 百分位区间**（项目里已有 `proportion_ci`）：

它在 `p≈0/1` 且 `n` 小时坍缩成零宽：

| 情形 | bootstrap | Wilson |
|---|---|---|
| `2/2` | `[1.0, 1.0]` 宽 0 | `[0.342, 1.0]` |
| `9/9` | `[1.0, 1.0]` 宽 0 | `[0.701, 1.0]` |
| `6/9` | `[0.333, 1.0]` | `[0.354, 0.879]` |

`6/9` 那一行是关键：bootstrap 的下界 `0.3333` 恰好等于基线，
而它正是 `k/n` 网格的量化产物（第 5 百分位落在 `3/9`），不是统计事实。

**工具选型错，不是工具实现错。** `proportion_ci` 没错，
百分位 bootstrap 不适合 `n=9` 且 `p≈1` 的比例区间。

Wilson 的三个好处：
- 闭式解，不需要 `seed`，结果完全确定（可复算性更强）
- 不坍缩：`n=2` 全对时仍报 `[0.342, 1.0]`
- 对 `n ≥ 5` 稳定
"""

from __future__ import annotations

import math
from dataclasses import dataclass

Z_95 = 1.959963984540054


@dataclass(frozen=True, slots=True)
class WilsonInterval:
    value: float
    low: float
    high: float
    n: int

    @property
    def width(self) -> float:
        return self.high - self.low


def wilson_interval(hits: int, n: int, *, z: float = Z_95) -> WilsonInterval:
    """命中数 `hits` / 总数 `n` 的 Wilson 区间。

    `n == 0` 时报 `[0, 1]`——"没有任何观测"不是"0%"，与本项目
    `path_returns` 用 `null` 而非 `0` 是同一条原则。
    """
    if n < 0:
        raise ValueError(f"n 不能为负：{n}")
    if hits < 0 or hits > n:
        raise ValueError(f"hits={hits} 不在 [0, {n}] 内")
    if n == 0:
        return WilsonInterval(value=0.0, low=0.0, high=1.0, n=0)

    p = hits / n
    denom = 1.0 + z * z / n
    center = (p + z * z / (2.0 * n)) / denom
    margin = z * math.sqrt(p * (1.0 - p) / n + z * z / (4.0 * n * n)) / denom

    return WilsonInterval(
        value=p,
        low=max(0.0, center - margin),
        high=min(1.0, center + margin),
        n=n,
    )


def minimum_hits_to_beat(baseline: float, n: int, *, z: float = Z_95) -> int | None:
    """在该 `n` 下，要通过"Wilson 下界 > baseline"至少需要几次命中。

    返回 `None` 表示该 `n` 下无论多少命中都不通过。

    **为什么需要这个函数**：判据本身随 `n` 自动变严，而"有多严"是
    读者判断结论强度的必要信息。实测（基线 1/3）：

    | n | 最小命中 | 命中率 |
    |---|---|---|
    | 4 | **4/4**（满分，与 F24 冲突） | 1.000 |
    | 5 | 4/5 | 0.800 |
    | 6 | 5/6 | 0.833 |
    | 9 | 6/9 | 0.667 |
    | 10 | 7/10 | 0.700 |
    | 20 | 11/20 | 0.550 |
    """
    for hits in range(n + 1):
        if wilson_interval(hits, n, z=z).low > baseline:
            return hits
    return None


__all__ = ["WilsonInterval", "minimum_hits_to_beat", "wilson_interval"]
