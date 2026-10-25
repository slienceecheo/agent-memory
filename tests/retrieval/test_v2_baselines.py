"""竞争集与随机基线的行为契约。

三条必须锁住的性质：

1. **竞争集定义唯一**：报告、门禁、随机基线用同一个函数，
   否则"池大小"与"排名空间"会各说各话——C4 就是这么失去意义的。
2. **随机基线用精确公式**，不是阈值判定：
   用"多数试验是否命中"会把 A 轴的 0.30 压成 0，而那看起来像"随机基线为 0"。
3. **A 轴在 K=5 上必然饱和**：分支数 ≤ K 时随机 `SEH@5` 恒等于 1，
   所以 A 轴主指标只能是 `SEH@1`。
"""

from __future__ import annotations

from pathlib import Path

import pytest
from evals.datasets.retrieval_v2 import Axis, load_dataset
from evals.metrics.v2_baselines import (
    all_axis_baselines,
    axis_baseline,
    competing_set,
    monte_carlo_seh,
    random_mrr,
    random_seh_at_1,
    random_seh_at_k,
    required_pool_size_for,
)

ROOT = Path(__file__).resolve().parents[2]
SAMPLE = ROOT / "data" / "retrieval-v2" / "sample"


# ---------- 纯公式 ----------


def test_random_seh_at_1_is_inverse_pool_size() -> None:
    assert random_seh_at_1(4) == pytest.approx(0.25)
    assert random_seh_at_1(12) == pytest.approx(1 / 12)


def test_random_seh_at_k_saturates_when_pool_fits_in_k() -> None:
    """N <= K 时随机 SEH@K 恒为 1——这不是成绩，是没有排名空间。"""
    assert random_seh_at_k(3, 5) == pytest.approx(1.0)
    assert random_seh_at_k(5, 5) == pytest.approx(1.0)
    assert random_seh_at_k(6, 5) == pytest.approx(5 / 6)


def test_random_mrr_is_harmonic_over_n() -> None:
    assert random_mrr(1) == pytest.approx(1.0)
    assert random_mrr(4) == pytest.approx((1 + 1 / 2 + 1 / 3 + 1 / 4) / 4)


def test_required_pool_size_explains_why_k_is_unusable() -> None:
    """要在 K=5 上让随机基线低于 0.95，池至少要 6 条。

    A 轴天然只有 3–5 个分支，所以它永远到不了——这不是数据不够多，是轴的性质。
    """
    assert required_pool_size_for(5, 0.95) == 6


def test_zero_pool_is_handled() -> None:
    assert random_seh_at_1(0) == 0.0
    assert random_seh_at_k(0, 5) == 0.0
    assert random_mrr(0) == 0.0


# ---------- 样例数据上 ----------


@pytest.fixture(scope="module")
def sample():
    if not SAMPLE.exists():
        pytest.skip("样例数据集尚未生成")
    return load_dataset(SAMPLE)


def test_axis_a_competes_within_relation(sample) -> None:
    """A 轴的竞争集只含同 subject、**同 relation** 的分支。"""
    query = next(q for q in sample.queries if q.axis is Axis.A)
    gold = sample.memory(query.gold_memory_id)
    pool = competing_set(sample, query)

    assert all(m.relation == gold.relation for m in pool)
    assert all(m.subject == gold.subject for m in pool)
    assert any(m.memory_id == query.gold_memory_id for m in pool)


def test_axis_c_competes_within_subject(sample) -> None:
    """C 轴的竞争集是同 subject 的全部记忆，跨 relation。"""
    query = next(q for q in sample.queries if q.axis is Axis.C)
    gold = sample.memory(query.gold_memory_id)
    pool = competing_set(sample, query)

    assert all(m.subject == gold.subject for m in pool)
    assert len({m.relation for m in pool}) > 1


def test_gold_is_always_in_its_own_competing_set(sample) -> None:
    for query in sample.queries:
        pool = competing_set(sample, query)

        assert any(m.memory_id == query.gold_memory_id for m in pool)


def test_axis_a_saturates_at_k_on_sample(sample) -> None:
    """A 轴分支 3–4 条，随机 SEH@5 必然 = 1.0。

    这个断言锁的是**几何事实**，不是缺陷：只要 A 轴分支数 ≤ K，
    `SEH@5` 在 A 轴上就没有区分力。所以协议规定 A 轴主指标是 `SEH@1`。
    """
    baseline = axis_baseline(sample, Axis.A)

    assert baseline.mean_pool_size < 5
    assert baseline.seh_at_k == pytest.approx(1.0)
    assert baseline.saturates_at_k
    assert baseline.seh_at_1 < 0.5


def test_axis_c_does_not_saturate_on_sample(sample) -> None:
    baseline = axis_baseline(sample, Axis.C)

    assert baseline.seh_at_k < 1.0
    assert not baseline.saturates_at_k


def test_formula_matches_monte_carlo(sample) -> None:
    """精确公式与实测重排必须一致（偏差 < 0.02）。

    这条抓的是"公式写错但看起来合理"。C4 的随机基线从来没被算过，
    所以这类错误可以一直藏着。
    """
    for axis in (Axis.A, Axis.C):
        mc_1, mc_5 = monte_carlo_seh(sample, axis, trials=2000, seed=0)
        expected = axis_baseline(sample, axis)

        assert mc_1 == pytest.approx(expected.seh_at_1, abs=0.02), f"{axis} SEH@1 偏差过大"
        assert mc_5 == pytest.approx(expected.seh_at_k, abs=0.02), f"{axis} SEH@5 偏差过大"


def test_all_axis_baselines_covers_every_axis(sample) -> None:
    baselines = all_axis_baselines(sample)

    assert set(baselines) == {"A", "C", "mixed"}


def test_mixed_baseline_is_not_a_silent_average(sample) -> None:
    """混合池不得把 A 轴的饱和混进总分。

    这里只断言它与 A 轴不同——报告层面的"禁止合并"由 R10/F14 管。
    """
    baselines = all_axis_baselines(sample)

    assert baselines["mixed"].queries == 0  # 样例里没有 mixed 查询
