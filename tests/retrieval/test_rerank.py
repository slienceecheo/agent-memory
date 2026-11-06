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
        RerankWeights(base=0.5, authority=0.5, cosine=0.5)


def test_weights_accept_valid_set() -> None:
    weights = RerankWeights(base=0.4, authority=0.4, cosine=0.2)

    assert weights.total() == pytest.approx(1.0)


def test_weights_reject_negative() -> None:
    with pytest.raises(ValueError):
        RerankWeights(base=1.2, authority=-0.2, cosine=0.0)


def test_preregistered_weights_exist_and_sum_to_one() -> None:
    """预注册的权重组合必须都合法。"""
    from memory.retrieval.rerank import PREREGISTERED_WEIGHTS

    for name, weights in PREREGISTERED_WEIGHTS.items():
        assert weights.total() == pytest.approx(1.0), name


def test_preregistered_count_is_five() -> None:
    """审查要求：预注册不超过 5 组，避免网格搜索选噪声。"""
    from memory.retrieval.rerank import PREREGISTERED_WEIGHTS

    assert len(PREREGISTERED_WEIGHTS) <= 5


def test_preregistered_weights_are_all_valid() -> None:
    """预注册表里每一组都必须是合法权重（和 == 1、非负）。

    **数值本身的断言在 `test_preregistered_naming.py`**——
    那里按"这一组回答什么问题"来组织，并区分默认/mixed/cosine_only。
    这里只守"表里没有不合法的构造"。

    **为什么不在两处都断言数值**：那会让同一个事实有两条判据，
    而 commit ③ 改默认值时它们在两个文件里同时红——
    读者会以为是两个问题。**一个事实一条判据。**
    """
    from memory.retrieval.rerank import PREREGISTERED_WEIGHTS

    for name, w in PREREGISTERED_WEIGHTS.items():
        assert w.base >= 0.0 and w.authority >= 0.0 and w.cosine >= 0.0, name
        assert w.total() == pytest.approx(1.0), name
        assert not hasattr(w, "condition"), f"{name} 有 condition 字段"
        assert not hasattr(w, "status"), f"{name} 有 status 字段"


# ---------- 组合与消融 ----------


class _Candidate:
    def __init__(
        self,
        item_id: str,
        *,
        base: float,
        condition: float,
        authority: float,
        cosine: float,
    ):
        self.item_id = item_id
        self.features = FeatureScores(
            base=base, condition=condition, authority=authority, cosine=cosine
        )


def test_base_only_reproduces_fusion_order() -> None:
    """只开基础项时，排序必须与纯 RRF 一致。"""
    candidates = [
        _Candidate("a", base=1.0, condition=0.0, authority=0.0, cosine=1.0),
        _Candidate("b", base=0.5, condition=1.0, authority=1.0, cosine=1.0),
    ]
    weights = RerankWeights(base=1.0, authority=0.0, cosine=0.0)

    ranked = rerank(candidates, weights=weights)

    assert [item.item_id for item in ranked] == ["a", "b"]


def test_feature_can_override_base_when_heavy() -> None:
    candidates = [
        _Candidate("a", base=1.0, condition=0.0, authority=0.0, cosine=0.0),
        _Candidate("b", base=0.9, condition=1.0, authority=1.0, cosine=1.0),
    ]
    weights = RerankWeights(base=0.2, authority=0.4, cosine=0.4)

    ranked = rerank(candidates, weights=weights)

    assert ranked[0].item_id == "b"


def test_base_only_falls_back_to_fusion_order() -> None:
    """**只开融合分**时，排序退化为融合分顺序。

    **这条原来的名字是 `test_all_off_falls_back_to_base`，而那个名字是错的**：
    `disabled_weights()` 返回 `base=1, authority=0, cosine=0`，
    语义是"只开融合分"，不是"全部关闭"。

    而"全部关闭"**根本不可构造**：`RerankWeights` 要求权重和为 1，
    三个都关意味着和为 0，会直接被拒。这条测试改名的同时补了那个断言，
    否则"全部关闭"这个场景会继续留在 spec 里而没有对应实现。
    """
    from memory.retrieval.rerank import disabled_weights

    weights = disabled_weights()
    # 语义明确的断言：它不是"全关"
    assert (weights.base, weights.authority, weights.cosine) == (1.0, 0.0, 0.0)

    candidates = [
        _Candidate("a", base=1.0, condition=0.0, authority=0.0, cosine=0.0),
        _Candidate("b", base=0.5, condition=1.0, authority=1.0, cosine=1.0),
    ]

    ranked = rerank(candidates, weights=weights)

    assert [item.item_id for item in ranked] == ["a", "b"]


def test_all_zero_weights_are_rejected() -> None:
    """**全零权重不可构造**——所以"三个特征全部关闭"这个状态不存在。

    这条是 spec 场景「全零权重被拒绝」的实体，
    也是删掉旧场景「全部特征关闭」的依据。
    """
    from memory.retrieval.rerank import RerankWeights

    with pytest.raises(ValueError, match="权重之和必须为 1"):
        RerankWeights(base=0.0, authority=0.0, cosine=0.0)


def test_scores_stay_in_unit_interval() -> None:
    candidates = [
        _Candidate("a", base=1.0, condition=1.0, authority=1.0, cosine=1.0),
        _Candidate("b", base=0.0, condition=0.0, authority=0.0, cosine=0.0),
    ]
    weights = RerankWeights(base=0.4, authority=0.3, cosine=0.3)

    ranked = rerank(candidates, weights=weights)

    for item in ranked:
        assert 0.0 <= item.score <= 1.0


def test_feature_value_out_of_range_raises() -> None:
    """特征越界必须报错：未限定值域时大数会压过权重，搜索失去意义。"""
    candidates = [_Candidate("a", base=2.0, condition=0.0, authority=0.0, cosine=0.0)]
    weights = RerankWeights(base=1.0, authority=0.0, cosine=0.0)

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
        _Candidate("b", base=0.5, condition=0.5, authority=0.5, cosine=0.5),
        _Candidate("a", base=0.5, condition=0.5, authority=0.5, cosine=0.5),
    ]
    weights = RerankWeights(base=0.4, authority=0.3, cosine=0.3)

    ranked = rerank(candidates, weights=weights)

    assert [item.item_id for item in ranked] == ["b", "a"]


def test_ties_are_deterministic_given_the_same_input() -> None:
    """同一输入两次调用给出同一顺序——这是"可复现"的真正含义。

    与上一条的区别：上一条锁"保持输入顺序"，这条锁"跨调用稳定"。
    两者都要，因为"保持输入顺序"如果实现成随机洗牌，也会满足上一条的单次断言。
    """
    candidates = [
        _Candidate("x", base=0.5, condition=0.5, authority=0.5, cosine=0.5),
        _Candidate("y", base=0.5, condition=0.5, authority=0.5, cosine=0.5),
        _Candidate("z", base=0.5, condition=0.5, authority=0.5, cosine=0.5),
    ]
    weights = RerankWeights(base=0.4, authority=0.3, cosine=0.3)

    first = [item.item_id for item in rerank(candidates, weights=weights)]
    second = [item.item_id for item in rerank(candidates, weights=weights)]

    assert first == second == ["x", "y", "z"]
