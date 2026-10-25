"""检索指标的行为契约。

两个指标必须分开报告：

- **SEH@K**：gold 是否进前 K（集合命中）
- **SRS**：gold 的排名分位（`1/rank`），未召回为 0

只报 SEH@K 会掩盖排序差异：两个系统都让 gold 进前 5，
但一个排第 1、另一个排第 5，能力完全不同。
"""

from __future__ import annotations

import pytest
from evals.metrics.retrieval import (
    Attribution,
    attribute_failure,
    attribution_breakdown,
    seh_at_k,
    srs,
)

# ---------- SEH@K ----------


def test_seh_hit_within_k() -> None:
    assert seh_at_k(rank=3, k=5) is True


def test_seh_at_exact_k_is_hit() -> None:
    assert seh_at_k(rank=5, k=5) is True


def test_seh_miss_beyond_k() -> None:
    assert seh_at_k(rank=6, k=5) is False


def test_seh_not_recalled_is_miss() -> None:
    assert seh_at_k(rank=None, k=5) is False


def test_seh_rejects_invalid_k() -> None:
    with pytest.raises(ValueError, match="k"):
        seh_at_k(rank=1, k=0)


# ---------- SRS ----------


def test_srs_definitions() -> None:
    """`1/rank`，排名从 1 开始。"""
    assert srs(rank=1) == pytest.approx(1.0)
    assert srs(rank=2) == pytest.approx(0.5)
    assert srs(rank=5) == pytest.approx(0.2)


def test_srs_not_recalled_is_zero() -> None:
    assert srs(rank=None) == 0.0


def test_srs_distinguishes_rank_1_from_rank_5() -> None:
    """这是 SRS 存在的理由：两者 SEH@5 相同，能力不同。"""
    assert seh_at_k(rank=1, k=5) is True
    assert seh_at_k(rank=5, k=5) is True
    assert srs(rank=1) > srs(rank=5)


def test_srs_rejects_zero_rank() -> None:
    with pytest.raises(ValueError, match="rank"):
        srs(rank=0)


def test_srs_is_bounded() -> None:
    for rank in range(1, 50):
        assert 0.0 <= srs(rank=rank) <= 1.0


# ---------- 归因 ----------


def test_failure_not_in_pool() -> None:
    result = attribute_failure(
        gold_in_pool=False, rank_after_fusion=None, rank_after_rerank=None, k=5
    )

    assert result is Attribution.NOT_IN_POOL


def test_failure_ranked_too_low() -> None:
    result = attribute_failure(
        gold_in_pool=True, rank_after_fusion=8, rank_after_rerank=8, k=5
    )

    assert result is Attribution.LOW_RANK


def test_failure_dropped_by_rerank() -> None:
    result = attribute_failure(
        gold_in_pool=True, rank_after_fusion=3, rank_after_rerank=7, k=5
    )

    assert result is Attribution.RERANK_DROPPED


def test_success_returns_none() -> None:
    result = attribute_failure(
        gold_in_pool=True, rank_after_fusion=1, rank_after_rerank=1, k=5
    )

    assert result is None


def test_attribution_classes_are_disjoint_and_exhaustive() -> None:
    """三类必须互斥且覆盖全部失败情形。"""
    cases = [
        (False, None, None),
        (True, 8, 8),
        (True, 3, 7),
    ]
    results = [
        attribute_failure(
            gold_in_pool=in_pool,
            rank_after_fusion=fusion,
            rank_after_rerank=rerank_rank,
            k=5,
        )
        for in_pool, fusion, rerank_rank in cases
    ]

    assert all(result is not None for result in results)
    assert len(set(results)) == 3


def test_attribution_requires_untracated_fusion_rank() -> None:
    """要能区分"融合后就在 K 外"和"融合后在 K 内但被重排挤掉"，

    必须保留未截断的融合排名。否则两类无法区分。
    """
    low = attribute_failure(
        gold_in_pool=True, rank_after_fusion=9, rank_after_rerank=9, k=5
    )
    dropped = attribute_failure(
        gold_in_pool=True, rank_after_fusion=4, rank_after_rerank=9, k=5
    )

    assert low is not dropped


def test_breakdown_sums_to_total() -> None:
    results = [
        Attribution.NOT_IN_POOL,
        Attribution.LOW_RANK,
        Attribution.LOW_RANK,
        Attribution.RERANK_DROPPED,
        None,
    ]

    breakdown = attribution_breakdown(results)

    assert breakdown["NOT_IN_POOL"] == 1
    assert breakdown["LOW_RANK"] == 2
    assert breakdown["RERANK_DROPPED"] == 1
    assert sum(breakdown.values()) == 4


def test_breakdown_has_all_keys_even_when_zero() -> None:
    """报告要能稳定取到三类，缺键会让表格崩掉。"""
    breakdown = attribution_breakdown([None])

    for kind in Attribution:
        assert kind.value in breakdown
