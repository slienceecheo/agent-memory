"""四特征重排的行为契约。

**为什么只有四个特征**：审查实测，原设计的五个里有四个在 ACTIVE-only
候选集上是常数：

- `temporal_validity`：所有召回路径只返回 ACTIVE，恒为 1.0
- `recency`：场景文件无时间字段，全部同一 `BASE_TIME`
- `source_authority`：34/40 dev 缺失，默认值相同
- `condition_match`：只有 30/90 条有条件

留着常数特征只会制造"重排有效"的假象。所以只保留**有方差**的四个，
并要求每个都有测试断言"在真实候选池上确实有方差"。
"""

from __future__ import annotations

import pytest

from memory.retrieval.rerank import (
    FeatureScores,
    RerankWeights,
    authority_score,
    condition_score,
    rerank,
    rrf_norm,
    status_score,
)
from memory.store.models import Authority, Status

# ---------- 各特征的值域 ----------


def test_rrf_norm_maps_max_to_one() -> None:
    assert rrf_norm(2.0, max_score=2.0) == pytest.approx(1.0)
    assert rrf_norm(1.0, max_score=2.0) == pytest.approx(0.5)


def test_rrf_norm_zero_max_is_safe() -> None:
    """全零时不该除零。"""
    assert rrf_norm(0.0, max_score=0.0) == 0.0


def test_authority_score_ordering() -> None:
    assert authority_score(Authority.USER_DIRECT) > authority_score(Authority.THIRD_PARTY)


def test_authority_score_within_unit_interval() -> None:
    for level in Authority:
        assert 0.0 <= authority_score(level) <= 1.0


def test_status_score_ordering() -> None:
    assert status_score(Status.ACTIVE) > status_score(Status.CONFLICTED)
    assert status_score(Status.CONFLICTED) > status_score(Status.SUPERSEDED)


def test_status_score_within_unit_interval() -> None:
    for status in Status:
        assert 0.0 <= status_score(status) <= 1.0


def test_condition_score_neutral_when_absent() -> None:
    assert condition_score(None, "coding") == pytest.approx(0.5)


def test_condition_score_full_match() -> None:
    assert condition_score("写代码", "coding") == pytest.approx(1.0)


# ---------- 权重 ----------


def test_weights_must_sum_to_one() -> None:
    with pytest.raises(ValueError, match="和"):
        RerankWeights(base=0.5, condition=0.5, authority=0.5, status=0.5)


def test_weights_accept_valid_set() -> None:
    weights = RerankWeights(base=0.4, condition=0.2, authority=0.2, status=0.2)

    assert weights.total() == pytest.approx(1.0)


def test_weights_reject_negative() -> None:
    with pytest.raises(ValueError):
        RerankWeights(base=1.2, condition=-0.2, authority=0.0, status=0.0)


def test_preregistered_weights_exist_and_sum_to_one() -> None:
    """预注册的权重组合必须都合法。"""
    from memory.retrieval.rerank import PREREGISTERED_WEIGHTS

    for name, weights in PREREGISTERED_WEIGHTS.items():
        assert weights.total() == pytest.approx(1.0), name


def test_preregistered_count_is_five() -> None:
    """审查要求：预注册不超过 5 组，避免网格搜索选噪声。"""
    from memory.retrieval.rerank import PREREGISTERED_WEIGHTS

    assert len(PREREGISTERED_WEIGHTS) <= 5


# ---------- 组合与消融 ----------


class _Candidate:
    def __init__(
        self,
        item_id: str,
        *,
        base: float,
        condition: float,
        authority: float,
        status: float,
    ):
        self.item_id = item_id
        self.features = FeatureScores(
            base=base, condition=condition, authority=authority, status=status
        )


def test_base_only_reproduces_fusion_order() -> None:
    """只开基础项时，排序必须与纯 RRF 一致。"""
    candidates = [
        _Candidate("a", base=1.0, condition=0.0, authority=0.0, status=1.0),
        _Candidate("b", base=0.5, condition=1.0, authority=1.0, status=1.0),
    ]
    weights = RerankWeights(base=1.0, condition=0.0, authority=0.0, status=0.0)

    ranked = rerank(candidates, weights=weights)

    assert [item.item_id for item in ranked] == ["a", "b"]


def test_feature_can_override_base_when_heavy() -> None:
    candidates = [
        _Candidate("a", base=1.0, condition=0.0, authority=0.0, status=0.0),
        _Candidate("b", base=0.9, condition=1.0, authority=1.0, status=1.0),
    ]
    weights = RerankWeights(base=0.1, condition=0.3, authority=0.3, status=0.3)

    ranked = rerank(candidates, weights=weights)

    assert ranked[0].item_id == "b"


def test_all_off_falls_back_to_base() -> None:
    """全关时退化为融合分排序，且不因权重校验失败。"""
    from memory.retrieval.rerank import disabled_weights

    weights = disabled_weights()
    candidates = [
        _Candidate("a", base=1.0, condition=0.0, authority=0.0, status=0.0),
        _Candidate("b", base=0.5, condition=1.0, authority=1.0, status=1.0),
    ]

    ranked = rerank(candidates, weights=weights)

    assert [item.item_id for item in ranked] == ["a", "b"]


def test_scores_stay_in_unit_interval() -> None:
    candidates = [
        _Candidate("a", base=1.0, condition=1.0, authority=1.0, status=1.0),
        _Candidate("b", base=0.0, condition=0.0, authority=0.0, status=0.0),
    ]
    weights = RerankWeights(base=0.25, condition=0.25, authority=0.25, status=0.25)

    ranked = rerank(candidates, weights=weights)

    for item in ranked:
        assert 0.0 <= item.score <= 1.0


def test_feature_value_out_of_range_raises() -> None:
    """特征越界必须报错：未限定值域时大数会压过权重，搜索失去意义。"""
    candidates = [_Candidate("a", base=2.0, condition=0.0, authority=0.0, status=0.0)]
    weights = RerankWeights(base=1.0, condition=0.0, authority=0.0, status=0.0)

    with pytest.raises(ValueError, match="\\[0,1\\]"):
        rerank(candidates, weights=weights)


def test_ties_keep_input_order() -> None:
    """同分时保持**输入顺序**，不是按 id 重排。

    **这条测试的意图变过**：它原本断言"同分按 `item_id` 排序以保证可复现"。
    但那个二级键在实际调用路径里**永远会被覆盖**（调用方按融合顺序重排），
    所以它是一条会被覆盖的判据——留着会让读代码的人误以为它在生效。

    现在的语义是：`rerank` 只按分数排，并列时交给调用方。
    这条测试锁的是"保持输入顺序"这个稳定排序的性质。

    输入 `b, a`（同分）→ 输出仍是 `b, a`。
    若改回按 id 排，会变成 `a, b`，这条测试就会红。
    """
    candidates = [
        _Candidate("b", base=0.5, condition=0.5, authority=0.5, status=0.5),
        _Candidate("a", base=0.5, condition=0.5, authority=0.5, status=0.5),
    ]
    weights = RerankWeights(base=0.25, condition=0.25, authority=0.25, status=0.25)

    ranked = rerank(candidates, weights=weights)

    assert [item.item_id for item in ranked] == ["b", "a"]


def test_ties_are_deterministic_given_the_same_input() -> None:
    """同一输入两次调用给出同一顺序——这是"可复现"的真正含义。

    与上一条的区别：上一条锁"保持输入顺序"，这条锁"跨调用稳定"。
    两者都要，因为"保持输入顺序"如果实现成随机洗牌，也会满足上一条的单次断言。
    """
    candidates = [
        _Candidate("x", base=0.5, condition=0.5, authority=0.5, status=0.5),
        _Candidate("y", base=0.5, condition=0.5, authority=0.5, status=0.5),
        _Candidate("z", base=0.5, condition=0.5, authority=0.5, status=0.5),
    ]
    weights = RerankWeights(base=0.25, condition=0.25, authority=0.25, status=0.25)

    first = [item.item_id for item in rerank(candidates, weights=weights)]
    second = [item.item_id for item in rerank(candidates, weights=weights)]

    assert first == second == ["x", "y", "z"]
