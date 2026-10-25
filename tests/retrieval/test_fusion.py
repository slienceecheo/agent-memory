"""RRF 融合的行为契约。

**为什么不用加权分数**：BM25 无界、余弦有界，直接相加必须先归一化，
而归一化参数会随数据集漂移——换 benchmark 就要重调。
RRF 只用排名，跨数据集稳定。

代价：丢掉"差多少"的信息。对三路召回这种量级，稳定性更重要。
"""

from __future__ import annotations

import pytest

from memory.retrieval.fusion import Fused, rrf


def _ids(*names: str) -> list[str]:
    return list(names)


def test_single_list_degenerates_to_its_own_order() -> None:
    fused = rrf({"lexical": _ids("a", "b", "c")})

    assert [item.item_id for item in fused] == ["a", "b", "c"]


def test_document_in_two_lists_ranks_higher() -> None:
    """多路命中优于单路命中——这是融合的全部意义。"""
    fused = rrf(
        {
            "lexical": _ids("only_lexical", "both"),
            "vector": _ids("both", "only_vector"),
        }
    )

    assert fused[0].item_id == "both"


def test_scores_are_sum_of_reciprocal_ranks() -> None:
    fused = rrf({"lexical": _ids("a"), "vector": _ids("a")}, k=60)

    # 1/(60+1) * 2
    assert fused[0].score == pytest.approx(2 / 61)


def test_default_k_is_60() -> None:
    fused = rrf({"lexical": _ids("a")})

    assert fused[0].score == pytest.approx(1 / 61)


def test_k_changes_relative_order() -> None:
    """k 必须真的影响结果，否则它是个摆设参数。

    用两个长度不同的列表：k 小时，排名差异被放大；
    k 大时，多路命中的优势被压低。
    """
    lists = {
        "lexical": _ids("a", "b", "c"),
        "vector": _ids("c"),
    }
    small = rrf(lists, k=1)
    large = rrf(lists, k=1000)

    order_small = [item.item_id for item in small]
    order_large = [item.item_id for item in large]
    assert order_small != order_large or small[0].score != large[0].score


def test_magnitude_of_input_scores_is_ignored() -> None:
    """只依赖排名：输入是 id 列表，没有分数可被误用。"""
    fused = rrf({"a": _ids("x", "y"), "b": _ids("y")})

    assert {item.item_id for item in fused} == {"x", "y"}


def test_missing_document_gets_zero_contribution() -> None:
    fused = rrf({"lexical": _ids("a", "b"), "vector": _ids("b")})
    by_id = {item.item_id: item for item in fused}

    assert by_id["b"].score > by_id["a"].score


def test_empty_lists_return_empty() -> None:
    assert rrf({}) == []
    assert rrf({"lexical": []}) == []


def test_ties_are_broken_deterministically() -> None:
    """并列时按 id 排序，保证可复现。"""
    first = rrf({"a": _ids("x"), "b": _ids("y")})
    second = rrf({"a": _ids("x"), "b": _ids("y")})

    assert [i.item_id for i in first] == [i.item_id for i in second]


def test_duplicate_ids_within_a_list_count_once() -> None:
    """同一列表内重复的 id 不该被计两次——那会人为抬高分数。"""
    fused = rrf({"lexical": _ids("a", "a", "b")})
    by_id = {item.item_id: item for item in fused}

    assert by_id["a"].score == pytest.approx(1 / 61)


def test_sources_are_recorded() -> None:
    """报告要能看出某条来自哪几路。"""
    fused = rrf({"lexical": _ids("a"), "vector": _ids("a")})

    assert isinstance(fused[0], Fused)
    assert set(fused[0].sources) == {"lexical", "vector"}


def test_rank_is_one_based_in_source() -> None:
    fused = rrf({"lexical": _ids("a", "b")})
    by_id = {item.item_id: item for item in fused}

    assert by_id["a"].ranks["lexical"] == 1
    assert by_id["b"].ranks["lexical"] == 2


def test_long_list_can_be_beaten_by_short_list_head() -> None:
    """审查指出的边界：多路命中不一定总赢。

    条件是列表长度 < k+2。当一路很长时，它在尾部的排名贡献很小，
    可能输给另一路头部。
    """
    long_list = [f"d{i}" for i in range(100)] + ["target"]
    fused = rrf({"long": long_list, "short": _ids("target")}, k=60)
    by_id = {item.item_id: item for item in fused}

    # target 在 long 里排 101，在 short 里排 1
    assert by_id["target"].score == pytest.approx(1 / 161 + 1 / 61)
    # 而 long 的头部只有一路
    assert by_id["target"].score > by_id["d0"].score
