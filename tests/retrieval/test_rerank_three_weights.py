"""v3 装置：三权重重排。

**这是 TDD 的第一个失败测试**（tasks 1.1）。当前产品代码的 `RerankWeights`
有四个字段，所以构造三权重会 `TypeError`——这就是预期的红。

改完之后（1.2），`RerankWeights` 只有三个字段，且 `rerank()` 的得分
等于 `w.base*base + w.authority*authority + w.status*status`。
"""

from __future__ import annotations

import pytest

from memory.retrieval.rerank import (
    FeatureScores,
    Ranked,
    RerankWeights,
    rerank,
)


class _Cand:
    def __init__(self, item_id: str, features: FeatureScores) -> None:
        self.item_id = item_id
        self.features = features


def test_weights_have_exactly_three_fields() -> None:
    """`RerankWeights` 必须只有三个字段，`condition` 已移除。"""
    fields = set(RerankWeights.__dataclass_fields__)

    assert fields == {"base", "authority", "status"}, f"字段变成 {sorted(fields)}"
    assert "condition" not in fields


def test_feature_scores_keep_four_fields() -> None:
    """`FeatureScores` **保留**四个字段——它是观测，不是策略。

    `condition` 仍可读，用于审计条件分布；只是不参与加权。
    """
    fields = set(FeatureScores.__dataclass_fields__)

    assert fields == {"base", "condition", "authority", "status"}


def test_three_weights_sum_to_one_is_accepted() -> None:
    """三权重和为 1 应被接受。"""
    w = RerankWeights(base=0.4, authority=0.3, status=0.3)

    assert w.total() == pytest.approx(1.0)


def test_score_is_three_term_weighted_sum() -> None:
    """得分必须等于三特征加权和，`condition` 不参与。"""
    w = RerankWeights(base=0.4, authority=0.3, status=0.3)
    features = FeatureScores(
        base=0.9, condition=0.1, authority=0.8, status=0.7
    )

    ranked = rerank([_Cand("x", features)], weights=w)
    expected = 0.4 * 0.9 + 0.3 * 0.8 + 0.3 * 0.7

    assert ranked[0].score == pytest.approx(expected)


def test_condition_does_not_affect_score() -> None:
    """`condition` 变化不改变得分，但仍可读取。

    **断言比 `score`，不比 `Ranked`**——`Ranked` 的相等性包含 `features`，
    两条候选的 `condition` 不同会让 `Ranked` 永远不等（见 design D3 的陷阱小节）。
    """
    w = RerankWeights(base=0.4, authority=0.3, status=0.3)
    a = FeatureScores(base=0.5, condition=0.0, authority=1.0, status=1.0)
    b = FeatureScores(base=0.5, condition=1.0, authority=1.0, status=1.0)

    ra = rerank([_Cand("x", a)], weights=w)[0]
    rb = rerank([_Cand("x", b)], weights=w)[0]

    assert ra.score == pytest.approx(rb.score)
    # 但仍可读取
    assert ra.features.condition == pytest.approx(0.0)
    assert rb.features.condition == pytest.approx(1.0)
    # 而 Ranked 本身不相等——这是设计使然，不是 bug
    assert ra != rb


def test_three_weights_must_still_sum_to_one() -> None:
    """三权重和不为 1 必须拒绝。"""
    with pytest.raises(ValueError, match="1"):
        RerankWeights(base=0.5, authority=0.5, status=0.5)


def test_rerank_returns_ranked_with_features() -> None:
    """返回值仍是 `Ranked`，且携带原始 `features`（用于审计）。"""
    w = RerankWeights(base=0.4, authority=0.3, status=0.3)
    features = FeatureScores(base=0.5, condition=0.25, authority=1.0, status=1.0)

    ranked = rerank([_Cand("x", features)], weights=w)

    assert isinstance(ranked[0], Ranked)
    assert ranked[0].features is features
