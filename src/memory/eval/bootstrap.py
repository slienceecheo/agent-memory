"""配对 bootstrap 置信区间。

为什么用配对而不是两独立区间：两组基线跑的是同一批样本，
独立区间会高估不确定性，也可能掩盖"A 在同一批题上稳定优于 B"的事实。

实现要点：
- 点估计直接由原始数据算出，与随机种子无关。
- 只对"重采样"消耗随机性，因此同种子必然同结果。
- 极端情形（全对/全错/n=1）自然退化为零宽区间，不做平滑——
  平滑会让"100 条全对"报出 [0.97, 1.0] 这种假的不确定性。

---

## ⚠️ 当前状态：spec 要求了它，但评测路径没有接

**实测（2026-10-31）**：`src/` 与 `evals/` 里**没有任何生产代码 import 本模块**，
只有两个测试用它（`tests/test_bootstrap.py`、`tests/retrieval/test_wilson.py`）。

而 `openspec/specs/evaluation-harness/spec.md` 第 91 行明确要求
"配对 bootstrap 置信区间"。

**这意味着：v2 的所有报告都没有报告过置信区间。** 那是已知缺陷，不是设计选择。

**为什么现在不接**：v2 的报告已发布、结果已冻结（`dataset-v2-frozen`）。
补区间等于改结果，违反协议 §1.2（看到分数后不改）。

**v3 必须接**：验收判据需要区间（见 `evals/metrics/wilson.py` 的说明——
Wilson 适合 `n` 小、`p≈0/1` 的比例；本模块的百分位 bootstrap
在 `2/2`、`9/9` 上会坍缩成零宽，不适合小样本比例）。

## 与 C4 缺陷 7 同形

| | C4 缺陷 7 | 本模块 |
|---|---|---|
| 实现了 | 三路召回 | 区间计算 |
| 单测通过 | ✅ | ✅ |
| 被生产使用 | ❌ 评测入口只接了词面 | ❌ 无人 import |

**这个形态比"实现了但 spec 没要求"（`wilson` 原先的状态）更隐蔽**，
因为它通过了所有基于"存在性"的检查。
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True, slots=True)
class Interval:
    value: float
    low: float
    high: float


def _as_bool_array(values: Sequence[bool] | np.ndarray, *, name: str) -> np.ndarray:
    array = np.asarray(values, dtype=np.float64)
    if array.size == 0:
        raise ValueError(f"{name} 为空，无法计算置信区间。")
    return array


def _percentile_interval(samples: np.ndarray, confidence: float) -> tuple[float, float]:
    tail = (1.0 - confidence) / 2.0
    low, high = np.quantile(samples, [tail, 1.0 - tail])
    return float(low), float(high)


def proportion_ci(
    outcomes: Sequence[bool] | np.ndarray,
    *,
    n_resamples: int = 10000,
    seed: int = 0,
    confidence: float = 0.95,
) -> Interval:
    """单组命中率的置信区间。"""
    array = _as_bool_array(outcomes, name="outcomes")
    if not 0.0 < confidence < 1.0:
        raise ValueError(f"confidence 必须在 (0, 1) 内，收到 {confidence}")

    value = float(array.mean())
    rng = np.random.default_rng(seed)
    indices = rng.integers(0, array.size, size=(n_resamples, array.size))
    resampled = array[indices].mean(axis=1)
    low, high = _percentile_interval(resampled, confidence)
    return Interval(value=value, low=low, high=high)


def paired_difference_ci(
    first: Sequence[bool] | np.ndarray,
    second: Sequence[bool] | np.ndarray,
    *,
    n_resamples: int = 10000,
    seed: int = 0,
    confidence: float = 0.95,
) -> Interval:
    """两组配对差异（first - second）的置信区间。

    按样本索引成对重采样，保留两组间的相关性。
    """
    a = _as_bool_array(first, name="first")
    b = _as_bool_array(second, name="second")
    if a.size != b.size:
        raise ValueError(
            f"两组长度不一致（{a.size} vs {b.size}），配对关系已丢失，无法计算差异。"
        )
    if not 0.0 < confidence < 1.0:
        raise ValueError(f"confidence 必须在 (0, 1) 内，收到 {confidence}")

    value = float(a.mean() - b.mean())
    differences = a - b
    rng = np.random.default_rng(seed)
    indices = rng.integers(0, differences.size, size=(n_resamples, differences.size))
    resampled = differences[indices].mean(axis=1)
    low, high = _percentile_interval(resampled, confidence)
    return Interval(value=value, low=low, high=high)
