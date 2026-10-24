"""七条规则的行为契约。

每条规则至少两个用例：一个应当命中，一个形似但不该命中。
只写正例会让"规则过度匹配"这类错误漏过去。
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from memory.resolver.rules import (
    Candidate,
    ChangeSource,
    DecisionKind,
    ExistingSnapshot,
    decide_by_rules,
)
from memory.store.models import Authority

NOW = datetime(2026, 1, 1, tzinfo=UTC)


def _candidate(
    *,
    value: str = "npm",
    condition: str | None = None,
    authority: Authority = Authority.USER_DIRECT,
    is_new_state: bool = True,
    change_source: ChangeSource = ChangeSource.RULE,
) -> Candidate:
    return Candidate(
        subject="project:x",
        relation="package_manager",
        value=value,
        condition=condition,
        authority=authority,
        is_new_state=is_new_state,
        change_source=change_source,
    )


def _existing(
    *,
    value: str = "pnpm",
    condition: str | None = None,
    authority: Authority = Authority.USER_DIRECT,
    item_id: str = "old-1",
) -> ExistingSnapshot:
    return ExistingSnapshot(
        id=item_id,
        subject="project:x",
        relation="package_manager",
        value=value,
        condition=condition,
        authority=authority,
    )


# ---------- 规则 1：ADD ----------


def test_rule1_no_existing_gives_add() -> None:
    decision = decide_by_rules(_candidate(), existing=None)

    assert decision.kind is DecisionKind.ADD
    assert decision.rule == "no_existing"


def test_rule1_does_not_fire_when_existing_present() -> None:
    """有既有条目时绝不能判 ADD，否则会撞唯一索引。"""
    decision = decide_by_rules(_candidate(), existing=_existing())

    assert decision.kind is not DecisionKind.ADD


# ---------- 规则 2：NOOP ----------


def test_rule2_identical_value_gives_noop() -> None:
    decision = decide_by_rules(
        _candidate(value="pnpm", authority=Authority.USER_DIRECT),
        existing=_existing(value="pnpm", authority=Authority.USER_DIRECT),
    )

    assert decision.kind is DecisionKind.NOOP
    assert decision.rule == "identical"


def test_rule2_different_authority_is_not_noop() -> None:
    """权威不同意味着可信度不同，不该被当作同一件事。"""
    decision = decide_by_rules(
        _candidate(value="pnpm", authority=Authority.THIRD_PARTY),
        existing=_existing(value="pnpm", authority=Authority.USER_DIRECT),
    )

    assert decision.kind is not DecisionKind.NOOP


def test_rule2_whitespace_difference_is_still_noop() -> None:
    """值的首尾空白不该制造新版本。"""
    decision = decide_by_rules(
        _candidate(value="  pnpm  "),
        existing=_existing(value="pnpm"),
    )

    assert decision.kind is DecisionKind.NOOP


# ---------- 规则 3：BRANCH ----------


def test_rule3_different_condition_gives_branch() -> None:
    """条件不同是并存，不是矛盾。"""
    decision = decide_by_rules(
        _candidate(value="深夜", condition="coding"),
        existing=_existing(value="早上", condition="meeting"),
    )

    assert decision.kind is DecisionKind.BRANCH
    assert decision.rule == "different_condition"


def test_rule3_unconditional_against_conditional_branches() -> None:
    """无条件版本与条件分支共存，不该互相取代。"""
    decision = decide_by_rules(
        _candidate(value="早上", condition=None),
        existing=_existing(value="深夜", condition="coding"),
    )

    assert decision.kind is DecisionKind.BRANCH


def test_rule3_same_condition_does_not_branch() -> None:
    """条件相同就不该走 BRANCH，否则同一条件下的更新永远无法生效。"""
    decision = decide_by_rules(
        _candidate(value="npm", condition="coding"),
        existing=_existing(value="pnpm", condition="coding"),
    )

    assert decision.kind is not DecisionKind.BRANCH


# ---------- 规则 4：MERGE ----------


def test_rule4_value_contains_old_gives_merge() -> None:
    """旧值仍成立，只是不完整。"""
    decision = decide_by_rules(
        _candidate(value="pnpm 加 workspace"),
        existing=_existing(value="pnpm"),
    )

    assert decision.kind is DecisionKind.MERGE
    assert decision.rule == "value_extends"


def test_rule4_unrelated_value_is_not_merge() -> None:
    decision = decide_by_rules(
        _candidate(value="npm"),
        existing=_existing(value="pnpm"),
    )

    assert decision.kind is not DecisionKind.MERGE


def test_rule4_old_contains_new_is_not_merge() -> None:
    """反向包含（新值更短）意味着信息减少，不是补充。"""
    decision = decide_by_rules(
        _candidate(value="pnpm"),
        existing=_existing(value="pnpm 加 workspace"),
    )

    assert decision.kind is not DecisionKind.MERGE


@pytest.mark.parametrize(
    ("candidate_value", "existing_value"),
    [
        ("不吃牛肉", "吃牛肉"),
        ("不能吃海鲜", "能吃海鲜"),
        ("不用 ruff", "用 ruff"),
        ("没有 workspace", "workspace"),
        ("cannot use pnpm", "use pnpm"),
    ],
)
def test_rule4_negation_is_never_merge(
    candidate_value: str, existing_value: str
) -> None:
    """中文加一个"不"字就把肯定变否定，但字符串包含关系仍然成立。

    若不排除否定词，"吃牛肉" 是 "不吃牛肉" 的子串，会被判成"补充"，
    语义上却是完全相反。这是最容易静默出错的一类。
    """
    decision = decide_by_rules(
        _candidate(value=candidate_value),
        existing=_existing(value=existing_value),
    )

    assert decision.kind is not DecisionKind.MERGE, (
        f"{existing_value!r} → {candidate_value!r} 被判成 MERGE，"
        "但两者否定状态不同，语义已反转"
    )


def test_rule4_same_negation_can_still_merge() -> None:
    """两侧都不带否定时，正常的补充关系仍然成立。"""
    decision = decide_by_rules(
        _candidate(value="不吃牛肉 只吃鸡肉"),
        existing=_existing(value="不吃牛肉"),
    )

    assert decision.kind is DecisionKind.MERGE


def test_rule4_mid_value_negation_does_not_block_merge() -> None:
    """否定词出现在值的**中间**时不是否定，而是补充说明。

    这是修正否定词检测时踩的坑：最初用"前 N 个字符里包含否定词"，
    导致 `"张三 周三不在"` 被判成否定，把 MERGE 错判成 SUPERSEDE。
    正确做法是只检查开头。
    """
    decision = decide_by_rules(
        _candidate(value="张三 周三不在"),
        existing=_existing(value="张三"),
    )

    assert decision.kind is DecisionKind.MERGE, (
        "「周三不在」是对值班安排的补充，不是对「张三是值班人」的否定"
    )


def test_rule4_mid_value_negation_with_other_markers() -> None:
    """同类情形：否定词出现在中间的多条变体都不该阻断合并。"""
    cases = [
        ("k8s 不用 helm", "k8s"),
        ("pnpm 不锁版本", "pnpm"),
        ("pytest 不要覆盖率", "pytest"),
    ]
    for candidate, existing in cases:
        decision = decide_by_rules(
            _candidate(value=candidate), existing=_existing(value=existing)
        )
        assert decision.kind is DecisionKind.MERGE, candidate


# ---------- 规则 5：CONFLICT（权威更低） ----------


def test_rule5_lower_authority_gives_conflict() -> None:
    """工单备注不该覆盖用户自述。这是安全相关的核心规则。"""
    decision = decide_by_rules(
        _candidate(value="喜欢花生酱", authority=Authority.THIRD_PARTY),
        existing=_existing(value="对花生过敏", authority=Authority.USER_DIRECT),
    )

    assert decision.kind is DecisionKind.CONFLICT
    assert decision.rule == "lower_authority"


def test_rule5_equal_authority_is_not_low_authority_conflict() -> None:
    """权威相当不该归到这条规则。"""
    decision = decide_by_rules(
        _candidate(value="npm", authority=Authority.USER_DIRECT),
        existing=_existing(value="pnpm", authority=Authority.USER_DIRECT),
    )

    assert decision.rule != "lower_authority"


# ---------- 规则 6：SUPERSEDE ----------


def test_rule6_new_state_supersedes() -> None:
    """用户改主意是主路径。"""
    decision = decide_by_rules(
        _candidate(value="npm", is_new_state=True),
        existing=_existing(value="pnpm"),
    )

    assert decision.kind is DecisionKind.SUPERSEDE
    assert decision.rule == "supersede_new_state"


def test_rule6_higher_authority_supersedes() -> None:
    """权威更高且陈述新状态时也应取代。"""
    decision = decide_by_rules(
        _candidate(value="npm", authority=Authority.USER_DIRECT, is_new_state=True),
        existing=_existing(value="pnpm", authority=Authority.SYSTEM_INFERRED),
    )

    assert decision.kind is DecisionKind.SUPERSEDE


# ---------- 规则 7：兜底 CONFLICT ----------


def test_rule7_fallback_when_state_change_unconfirmed() -> None:
    """无法确认是否新状态时，宁可标冲突也不猜覆盖。"""
    decision = decide_by_rules(
        _candidate(value="npm", is_new_state=False),
        existing=_existing(value="pnpm"),
    )

    assert decision.kind is DecisionKind.CONFLICT
    assert decision.rule == "unconfirmed_state_change"


def test_rule7_carries_both_values() -> None:
    decision = decide_by_rules(
        _candidate(value="npm", is_new_state=False),
        existing=_existing(value="pnpm"),
    )

    assert decision.existing_value == "pnpm"
    assert decision.candidate_value == "npm"


# ---------- 元信息 ----------


def test_decision_records_existing_id() -> None:
    """没有它就无法把判定关联回被比较的条目，也就无法归因。"""
    decision = decide_by_rules(_candidate(), existing=_existing(item_id="abc-123"))

    assert decision.existing_id == "abc-123"


def test_decision_records_change_source() -> None:
    decision = decide_by_rules(
        _candidate(change_source=ChangeSource.LLM),
        existing=_existing(),
    )

    assert decision.change_source is ChangeSource.LLM


@pytest.mark.parametrize(
    ("condition", "value", "expected"),
    [
        (None, "pnpm", DecisionKind.NOOP),
        ("coding", "pnpm", DecisionKind.BRANCH),
    ],
)
def test_condition_branch_beats_noop_only_when_different(
    condition: str | None, value: str, expected: DecisionKind
) -> None:
    """条件相同时 NOOP 优先；条件不同时 BRANCH 优先。

    这条把"第 2 条必须在第 3 条之前"落成可执行的断言。
    """
    decision = decide_by_rules(
        _candidate(value=value, condition=condition),
        existing=_existing(value="pnpm", condition=None),
    )

    assert decision.kind is expected
