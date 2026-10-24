"""规则顺序锁定。

规则表是一串 `if`。重排不会报错，只会静默改变行为——这是最难发现的一类回归。

本文件用"多规则同时匹配"的输入锁定顺序：
同样的输入若顺序被调整，结论会变成另一个类别，测试立即失败。

每个用例都注明"若顺序被改，会变成什么"，这样失败信息本身就是诊断。
"""

from __future__ import annotations

from memory.resolver.rules import (
    Candidate,
    ChangeSource,
    DecisionKind,
    ExistingSnapshot,
    decide_by_rules,
)
from memory.store.models import Authority


def _pair(
    *,
    candidate_value: str,
    existing_value: str,
    candidate_condition: str | None = None,
    existing_condition: str | None = None,
    candidate_authority: Authority = Authority.USER_DIRECT,
    existing_authority: Authority = Authority.USER_DIRECT,
    is_new_state: bool = True,
):
    return Candidate(
        subject="project:x",
        relation="package_manager",
        value=candidate_value,
        condition=candidate_condition,
        authority=candidate_authority,
        is_new_state=is_new_state,
        change_source=ChangeSource.RULE,
    ), ExistingSnapshot(
        id="old",
        subject="project:x",
        relation="package_manager",
        value=existing_value,
        condition=existing_condition,
        authority=existing_authority,
    )


def test_identical_beats_merge() -> None:
    """完全相同的值同时满足"包含关系"。

    若规则 4 排在规则 2 之前：`"pnpm"` 包含于 `"pnpm"`，会被判成 MERGE，
    每次重复确认都产生一个无意义的新版本。
    """
    candidate, existing = _pair(candidate_value="pnpm", existing_value="pnpm")

    decision = decide_by_rules(candidate, existing=existing)

    assert decision.kind is DecisionKind.NOOP, (
        f"顺序被改动了：完全相同的值被判成 {decision.kind.value}。"
        "规则 2（identical）必须排在规则 4（value_extends）之前。"
    )


def test_identical_beats_branch() -> None:
    """值相同但条件也相同时，必须是 NOOP 而不是 BRANCH。

    若条件检查排在相似检查之前且把"无条件对无条件"误判为不同，会产生多余分支。
    """
    candidate, existing = _pair(
        candidate_value="pnpm", existing_value="pnpm", candidate_condition=None
    )

    decision = decide_by_rules(candidate, existing=existing)

    assert decision.kind is DecisionKind.NOOP


def test_branch_beats_lower_authority_conflict() -> None:
    """条件不同 + 权威更低：应判 BRANCH（并存），不是 CONFLICT。

    若规则 5 排在规则 3 之前："用户自述早上的会议时间"与"系统推断的编码时间"
    会被当成矛盾，而它们只是适用于不同场景。
    """
    candidate, existing = _pair(
        candidate_value="深夜",
        existing_value="早上",
        candidate_condition="coding",
        existing_condition="meeting",
        candidate_authority=Authority.SYSTEM_INFERRED,
        existing_authority=Authority.USER_DIRECT,
    )

    decision = decide_by_rules(candidate, existing=existing)

    assert decision.kind is DecisionKind.BRANCH, (
        f"顺序被改动了：条件不同的低权威事实被判成 {decision.kind.value}。"
        "规则 3（different_condition）必须排在规则 5（lower_authority）之前。"
    )


def test_merge_beats_lower_authority_conflict() -> None:
    """补充性质的弱权威信息仍应合并，不是丢弃。

    若规则 5 排在规则 4 之前："用 pnpm"与"推断出 pnpm 加 workspace"
    会被当成冲突，丢掉了有价值的补充。
    """
    candidate, existing = _pair(
        candidate_value="pnpm 加 workspace",
        existing_value="pnpm",
        candidate_authority=Authority.SYSTEM_INFERRED,
        existing_authority=Authority.USER_DIRECT,
    )

    decision = decide_by_rules(candidate, existing=existing)

    assert decision.kind is DecisionKind.MERGE, (
        f"顺序被改动了：低权威的补充被判成 {decision.kind.value}。"
        "规则 4（value_extends）必须排在规则 5（lower_authority）之前。"
    )


def test_lower_authority_beats_supersede() -> None:
    """权威更低时即使声称是新状态，也只能标冲突。

    若规则 6 排在规则 5 之前：工单备注会覆盖用户自述的过敏史。
    这是安全相关的回归。
    """
    candidate, existing = _pair(
        candidate_value="喜欢花生酱",
        existing_value="对花生过敏",
        candidate_authority=Authority.THIRD_PARTY,
        existing_authority=Authority.USER_DIRECT,
        is_new_state=True,
    )

    decision = decide_by_rules(candidate, existing=existing)

    assert decision.kind is DecisionKind.CONFLICT, (
        f"顺序被改动了：低权威的新状态声明被判成 {decision.kind.value}。"
        "规则 5（lower_authority）必须排在规则 6（supersede_new_state）之前。"
    )


def test_supersede_beats_fallback() -> None:
    """确认是新状态时不该掉进兜底冲突。"""
    candidate, existing = _pair(
        candidate_value="npm", existing_value="pnpm", is_new_state=True
    )

    decision = decide_by_rules(candidate, existing=existing)

    assert decision.kind is DecisionKind.SUPERSEDE


def test_fallback_only_when_nothing_else_matches() -> None:
    """兜底必须是最后一条：权威相当、值不同、未确认新状态。"""
    candidate, existing = _pair(
        candidate_value="npm", existing_value="pnpm", is_new_state=False
    )

    decision = decide_by_rules(candidate, existing=existing)

    assert decision.kind is DecisionKind.CONFLICT
    assert decision.rule == "unconfirmed_state_change"


def test_add_rule_only_applies_without_existing() -> None:
    """ADD 是唯一不需要既有条目的规则；有既有条目时它必须让位。"""
    candidate, existing = _pair(candidate_value="npm", existing_value="pnpm")

    with_existing = decide_by_rules(candidate, existing=existing)
    without_existing = decide_by_rules(candidate, existing=None)

    assert with_existing.kind is not DecisionKind.ADD
    assert without_existing.kind is DecisionKind.ADD


def test_rule_names_are_stable() -> None:
    """规则名会进报告与审计，改动会让历史数据无法对照。"""
    expected = {
        "no_existing",
        "identical",
        "different_condition",
        "value_extends",
        "lower_authority",
        "supersede_new_state",
        "unconfirmed_state_change",
    }
    observed = set()

    observed.add(decide_by_rules(*_empty_args(), existing=None).rule)
    for candidate, existing, _ in [
        (*_pair(candidate_value="pnpm", existing_value="pnpm"), None),
        (
            *_pair(
                candidate_value="x",
                existing_value="y",
                candidate_condition="a",
                existing_condition="b",
            ),
            None,
        ),
        (*_pair(candidate_value="pnpm 加 x", existing_value="pnpm"), None),
        (
            *_pair(
                candidate_value="x",
                existing_value="y",
                candidate_authority=Authority.THIRD_PARTY,
            ),
            None,
        ),
        (*_pair(candidate_value="x", existing_value="y"), None),
        (*_pair(candidate_value="x", existing_value="y", is_new_state=False), None),
    ]:
        observed.add(decide_by_rules(candidate, existing=existing).rule)

    assert observed == expected


def _empty_args() -> tuple[Candidate]:
    return (
        Candidate(
            subject="project:x",
            relation="package_manager",
            value="npm",
            change_source=ChangeSource.RULE,
        ),
    )
