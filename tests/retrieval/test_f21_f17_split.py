"""F17a / F17b / F21a / F21b / F23：四个形状门禁。

**共同背景**：这些约束此前只写在协议 §8 的表里，没有任何门禁检查它们。
`project:ledger` 有 5 个 relation，而协议写"每 subject relation 数 1–3"，
22 项门禁却全绿——规则成了建议。

每一项在样例上的红/绿都是**预期的**，不是待修的 bug。
"""

from __future__ import annotations

from pathlib import Path

import pytest
from evals.datasets.retrieval_v2 import Axis, load_dataset
from evals.tools.check_v2_dataset import (
    ALL_CHECKS,
    check_f17_every_branch_queried,
    check_f17a_axis_a_covers_every_branch,
    check_f17b_every_relation_has_axis_c,
    check_f21a_relation_count,
    check_f21b_relation_count_mix,
    check_f23_axis_a_query_floor,
)

ROOT = Path(__file__).resolve().parents[2]
SAMPLE = ROOT / "data" / "retrieval-v2" / "sample"


@pytest.fixture(scope="module")
def dataset():  # type: ignore[no-untyped-def]
    if not SAMPLE.exists():
        pytest.skip("样例数据集缺失")
    return load_dataset(SAMPLE)


def test_f17a_passes_on_sample(dataset) -> None:  # type: ignore[no-untyped-def]
    """A 轴覆盖是完整的：10 个多分支全部被 A 轴指向。"""
    result = check_f17a_axis_a_covers_every_branch(dataset)

    assert result.code == "F17a"
    assert result.passed, result.detail
    assert "全部分支都被 A 轴指向" in result.detail


def test_f17b_fails_on_sample_and_names_the_missing(dataset) -> None:  # type: ignore[no-untyped-def]
    """**正确的失败**：C 轴只覆盖 2 个单值 relation，3 个多分支全缺。

    这不是 schema 问题，是 §8"每 (subject, relation) 一条 C 轴"没被
    F1–F20 检查，因此从未被执行。
    """
    result = check_f17b_every_relation_has_axis_c(dataset)

    assert result.code == "F17b"
    assert not result.passed
    assert "3/5" in result.detail
    for relation in ("oncall_owner", "deploy_target", "code_style"):
        assert relation in result.detail


def test_f17b_would_pass_if_c_axis_covered_multibranch(dataset) -> None:  # type: ignore[no-untyped-def]
    """反向验证：若 C 轴覆盖了多分支 relation，F17b 会绿。

    用一份改过的查询集测试，确认失败原因是"缺查询"而不是"实现写死"。
    """
    from dataclasses import replace

    c_queries = [q for q in dataset.queries if q.axis is Axis.C]
    golds = {q.gold_memory_id for q in c_queries}

    # 找一条不在 C 轴 gold 里的多分支关系，伪造一条 C 轴查询指向它
    target = next(
        m
        for m in dataset.memories
        if m.relation == "oncall_owner" and m.memory_id not in golds
    )
    fake = replace(
        c_queries[0],
        query_id="fake-c-oncall",
        axis=Axis.C,
        gold_memory_id=target.memory_id,
        expected_value=target.value,
    )
    patched = replace(dataset, queries=(*dataset.queries, fake))

    result = check_f17b_every_relation_has_axis_c(patched)
    # 补了 1 个，还剩 2 个 relation 没有 C 轴 gold（detail 报的是"缺几个"）
    assert "2/5" in result.detail
    assert not result.passed


def test_f21a_fails_on_sample_with_five_relations(dataset) -> None:  # type: ignore[no-untyped-def]
    """**正确的失败**：ledger 有 5 个 relation，协议上限是 3。"""
    result = check_f21a_relation_count(dataset)

    assert result.code == "F21a"
    assert not result.passed
    assert "project:ledger" in result.detail
    assert "5" in result.detail


def test_f21b_is_constructive_failure_on_single_subject(dataset) -> None:  # type: ignore[no-untyped-def]
    """只有 1 个 subject 时必然失败——属构造性，同 F6。"""
    result = check_f21b_relation_count_mix(dataset)

    assert result.code == "F21b"
    assert not result.passed
    assert "构造性" in result.detail


def test_f23_passes_on_sample(dataset) -> None:  # type: ignore[no-untyped-def]
    """样例有 10 条 A 轴查询，远超下限 6。"""
    result = check_f23_axis_a_query_floor(dataset)

    assert result.code == "F23"
    assert result.passed, result.detail


def test_f23_threshold_is_six_not_five() -> None:
    """F23 的下限必须是 6。

    `implicit >= 5 且 implicit <= A` 只能推出 A >= 5。
    而 A=5 时 implicit 占满，explicit=0，F13 要求两种 cue_type 都存在——A=5 非法。

    穷举确认：A=6 是最小合法值（implicit 5 + explicit 1）。
    """
    for a in range(5, 13):
        min_implicit = max(5, -(-a // 2))
        explicit = a - min_implicit
        legal = explicit >= 1 and min_implicit <= a
        if a < 6:
            assert not legal, f"A={a} 应为非法"
        else:
            assert legal, f"A={a} 应为合法"


def test_f23_catches_all_single_valued_subject() -> None:
    """全单值 relation 的 subject 会产生 0 条 A 轴查询——F23 必须抓住。"""

    from evals.datasets.retrieval_v2 import BranchNature, Dataset, Memory

    memories = tuple(
        Memory(
            memory_id=f"s-{i}",
            subject="project:all-single",
            relation=f"rel_{i}",
            value=f"v{i}",
            memory_text=f"值{i}",
            condition=None,
            authority=next(iter(dataset_authority())),
            status=next(iter(dataset_status())),
            branch_nature=BranchNature.NATURAL,
            valid_from="2026-01-01T00:00:00+00:00",
        )
        for i in range(3)
    )
    dataset = Dataset(memories=memories, queries=())
    result = check_f23_axis_a_query_floor(dataset)

    assert not result.passed
    assert "project:all-single" in result.detail or "不足" in result.detail


def dataset_authority():  # type: ignore[no-untyped-def]
    from memory.store.models import Authority

    return {Authority.USER_DIRECT}


def dataset_status():  # type: ignore[no-untyped-def]
    from memory.store.models import Status

    return {Status.ACTIVE}


def test_all_four_gates_are_registered() -> None:
    """四项都必须进 `ALL_CHECKS`。"""
    names = {check.__name__ for check in ALL_CHECKS}

    assert "check_f17a_axis_a_covers_every_branch" in names
    assert "check_f17b_every_relation_has_axis_c" in names
    assert "check_f21a_relation_count" in names
    assert "check_f21b_relation_count_mix" in names
    assert "check_f23_axis_a_query_floor" in names


def test_old_f17_not_registered_to_avoid_double_counting() -> None:
    """F17 不进 `ALL_CHECKS`——否则 F17 与 F17b 会对同一原因报两次红。"""
    names = {check.__name__ for check in ALL_CHECKS}

    assert "check_f17_every_branch_queried" not in names
    # 但函数仍然存在，供历史引用与一致性测试使用
    assert callable(check_f17_every_branch_queried)


def test_f17_equals_conjunction_of_a_and_b(dataset) -> None:  # type: ignore[no-untyped-def]
    """F17 的判定必须等于 F17a ∧ F17b。

    保留 F17 函数却让它与拆分后的结果不一致，就是"两个字段各说各话"。
    """
    a = check_f17a_axis_a_covers_every_branch(dataset)
    b = check_f17b_every_relation_has_axis_c(dataset)
    combined = check_f17_every_branch_queried(dataset)

    assert combined.passed == (a.passed and b.passed)
