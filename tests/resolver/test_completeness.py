"""规则集的完备性。

任何合法输入都必须落入六类之一，不得抛出异常或返回未定义值。
这不是"锦上添花"的测试：缺一条兜底，某个罕见组合就会让判定崩掉，
而崩掉的路径通常在真实数据里才会被触发。
"""

from __future__ import annotations

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from memory.resolver.rules import (
    Candidate,
    ChangeSource,
    DecisionKind,
    ExistingSnapshot,
    decide_by_rules,
)
from memory.store.models import Authority

VALUES = st.sampled_from(["pnpm", "npm", "pnpm 加 workspace", "", "  ", "PNPM"])
CONDITIONS = st.none() | st.sampled_from(["coding", "meeting", "", "  "])
AUTHORITIES = st.sampled_from(list(Authority))
SUBJECTS = st.sampled_from(["project:x", "project:y", "Project:X"])
RELATIONS = st.sampled_from(["package_manager", "包管理器", "unknown_thing"])


@given(
    candidate_value=VALUES,
    candidate_condition=CONDITIONS,
    candidate_authority=AUTHORITIES,
    existing_value=VALUES,
    existing_condition=CONDITIONS,
    existing_authority=AUTHORITIES,
    is_new_state=st.booleans(),
    omit_existing=st.booleans(),
)
@settings(max_examples=200, deadline=None, suppress_health_check=list(HealthCheck))
def test_any_input_yields_exactly_one_known_decision(
    candidate_value: str,
    candidate_condition: str | None,
    candidate_authority: Authority,
    existing_value: str,
    existing_condition: str | None,
    existing_authority: Authority,
    is_new_state: bool,
    omit_existing: bool,
) -> None:
    """随机组合输入，断言总能得到一个合法类别且不抛异常。"""
    candidate = Candidate(
        subject="project:x",
        relation="package_manager",
        value=candidate_value,
        condition=candidate_condition,
        authority=candidate_authority,
        is_new_state=is_new_state,
        change_source=ChangeSource.RULE,
    )
    existing = (
        None
        if omit_existing
        else ExistingSnapshot(
            id="old",
            subject="project:x",
            relation="package_manager",
            value=existing_value,
            condition=existing_condition,
            authority=existing_authority,
        )
    )

    decision = decide_by_rules(candidate, existing=existing)

    assert decision.kind in set(DecisionKind)
    assert decision.rule
    assert decision.candidate_value is not None


@given(
    subject=SUBJECTS,
    relation=RELATIONS,
    value=VALUES,
    condition=CONDITIONS,
)
@settings(max_examples=100, deadline=None, suppress_health_check=list(HealthCheck))
def test_decision_always_carries_a_normalized_key(
    subject: str, relation: str, value: str, condition: str | None
) -> None:
    """键必须始终存在，否则无法把它映射到存储层。"""
    candidate = Candidate(
        subject=subject,
        relation=relation,
        value=value,
        condition=condition,
        change_source=ChangeSource.RULE,
    )

    decision = decide_by_rules(candidate, existing=None)

    assert decision.key.subject
    assert decision.key.relation


@given(
    value=VALUES,
    authority=AUTHORITIES,
    is_new_state=st.booleans(),
)
@settings(max_examples=100, deadline=None, suppress_health_check=list(HealthCheck))
def test_never_supersedes_lower_authority(
    value: str, authority: Authority, is_new_state: bool
) -> None:
    """安全性质：权威更低的陈述永远不会取代权威更高的既有事实。

    这条不依赖第六类是否存在，是跨所有输入都必须成立的不变量。
    """
    candidate = Candidate(
        subject="project:x",
        relation="package_manager",
        value=value,
        authority=authority,
        is_new_state=is_new_state,
        change_source=ChangeSource.RULE,
    )
    existing = ExistingSnapshot(
        id="old",
        subject="project:x",
        relation="package_manager",
        value="完全不同的旧值",
        condition=None,
        authority=Authority.USER_DIRECT,
    )

    decision = decide_by_rules(candidate, existing=existing)

    if authority < Authority.USER_DIRECT and decision.kind is DecisionKind.SUPERSEDE:
        # 唯一允许的例外：新值只是旧值的补充（MERGE 已在前一条规则处理）
        raise AssertionError(
            f"低权威（{authority.value}）的陈述取代了高权威事实：{decision.rule}"
        )


def test_empty_condition_is_treated_as_none() -> None:
    """空串条件与 None 必须等价，否则会凭空造出分支。"""
    candidate = Candidate(
        subject="project:x",
        relation="package_manager",
        value="pnpm",
        condition="  ",
    )
    existing = ExistingSnapshot(
        id="old",
        subject="project:x",
        relation="package_manager",
        value="pnpm",
        condition=None,
    )

    decision = decide_by_rules(candidate, existing=existing)

    assert decision.kind is DecisionKind.NOOP


@pytest.mark.parametrize("source", list(ChangeSource))
def test_every_change_source_is_propagated(source: ChangeSource) -> None:
    """归因信息不能在判定过程中丢失，否则消融实验无法统计。"""
    candidate = Candidate(
        subject="project:x",
        relation="package_manager",
        value="npm",
        change_source=source,
    )

    decision = decide_by_rules(candidate, existing=None)

    assert decision.change_source is source
