"""判定结果对象的行为契约。

`Decision` 是"一等对象"而不是布尔值：它要能解释"为什么是这个结论"。
C1 的教训是"分数高但不知道为什么"，所以 `rule` 字段必须存在。
"""

from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from memory.resolver.normalize import normalize_key
from memory.resolver.rules import ChangeSource, Decision, DecisionKind


def _decision(**overrides: object) -> Decision:
    base: dict[str, object] = {
        "kind": DecisionKind.SUPERSEDE,
        "rule": "supersede_by_newer_state",
        "key": normalize_key("project:x", "package_manager"),
        "existing_id": "old-1",
        "change_source": ChangeSource.RULE,
        "normalized": True,
        "existing_value": "pnpm",
        "candidate_value": "npm",
    }
    base.update(overrides)
    return Decision(**base)  # type: ignore[arg-type]


def test_six_decision_kinds_exist() -> None:
    """六类缺一不可；少了任何一类都会让某种真实情形无出口。"""
    assert {kind.value for kind in DecisionKind} == {
        "NOOP",
        "ADD",
        "MERGE",
        "SUPERSEDE",
        "CONFLICT",
        "BRANCH",
    }


def test_four_change_sources_exist() -> None:
    """四种来源必须可区分，否则"不用模型差多少"无法测量。"""
    assert {source.value for source in ChangeSource} == {
        "rule",
        "llm",
        "disabled",
        "failed",
    }


def test_decision_is_serializable() -> None:
    """判定结果要写进追踪与报告，序列化不能丢语义。"""
    payload = json.loads(json.dumps(_decision().model_dump(mode="json")))

    assert payload["kind"] == "SUPERSEDE"
    assert payload["rule"] == "supersede_by_newer_state"
    assert payload["existing_value"] == "pnpm"
    assert payload["candidate_value"] == "npm"


def test_decision_is_frozen() -> None:
    """判定一旦产生就不该被下游就地修改。"""
    decision = _decision()

    with pytest.raises(ValidationError):
        decision.kind = DecisionKind.ADD  # type: ignore[misc]


def test_conflict_carries_both_values() -> None:
    """上层要据此生成"两种说法"的追问，缺一不可。"""
    decision = _decision(
        kind=DecisionKind.CONFLICT,
        existing_value="对花生过敏",
        candidate_value="喜欢花生酱饼干",
    )

    assert decision.existing_value == "对花生过敏"
    assert decision.candidate_value == "喜欢花生酱饼干"


def test_add_has_no_existing_id() -> None:
    """ADD 的情形下没有可比对象，`existing_id` 必须为空而不是伪造一个。"""
    decision = _decision(kind=DecisionKind.ADD, existing_id=None, existing_value=None)

    assert decision.existing_id is None
    assert decision.existing_value is None


def test_normalized_flag_defaults_to_true_when_alias_hit() -> None:
    key = normalize_key("project:x", "包管理器")

    assert key.normalized is True
