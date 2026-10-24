"""判定的数据模型与七条有序规则。

规则顺序是关键：一串 `if` 重排不会报错，只会静默改变行为。
因此顺序在代码里有编号注释，并有专门的测试锁定（tests/resolver/test_rule_order.py）。

七条规则的顺序依据见 openspec/changes/conflict-resolver/design.md D2。
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from memory.resolver.normalize import NormalizedKey, normalize_key
from memory.store.models import Authority


class DecisionKind(StrEnum):
    NOOP = "NOOP"
    ADD = "ADD"
    MERGE = "MERGE"
    SUPERSEDE = "SUPERSEDE"
    CONFLICT = "CONFLICT"
    BRANCH = "BRANCH"


class ChangeSource(StrEnum):
    """'是否陈述新状态'这个判断的来源。"""

    RULE = "rule"
    LLM = "llm"
    DISABLED = "disabled"
    FAILED = "failed"


class Decision(BaseModel):
    model_config = ConfigDict(frozen=True)

    kind: DecisionKind
    rule: str
    key: NormalizedKey
    existing_id: str | None = None
    change_source: ChangeSource = ChangeSource.DISABLED
    normalized: bool = True
    existing_value: str | None = None
    candidate_value: str = ""
    detail: dict[str, Any] = Field(default_factory=dict)

    @property
    def is_conflict(self) -> bool:
        return self.kind is DecisionKind.CONFLICT

    @property
    def produces_new_version(self) -> bool:
        return self.kind in {
            DecisionKind.ADD,
            DecisionKind.MERGE,
            DecisionKind.SUPERSEDE,
            DecisionKind.CONFLICT,
            DecisionKind.BRANCH,
        }


class Candidate(BaseModel):
    """待判定的候选事实。"""

    model_config = ConfigDict(frozen=True)

    subject: str
    relation: str
    value: str
    condition: str | None = None
    authority: Authority = Authority.USER_DIRECT
    is_new_state: bool = True
    change_source: ChangeSource = ChangeSource.DISABLED

    def normalized_key(self) -> NormalizedKey:
        return normalize_key(self.subject, self.relation)

    def clean_value(self) -> str:
        return self.value.strip()


class ExistingSnapshot(BaseModel):
    """被比较的既有条目（只取判定需要的字段）。"""

    model_config = ConfigDict(frozen=True)

    id: str
    subject: str
    relation: str
    value: str
    condition: str | None = None
    authority: Authority = Authority.USER_DIRECT

    def normalized_key(self) -> NormalizedKey:
        return normalize_key(self.subject, self.relation)

    def clean_value(self) -> str:
        return self.value.strip()


def _norm_condition(condition: str | None) -> str | None:
    if condition is None:
        return None
    trimmed = condition.strip()
    return trimmed or None


def _contains(candidate_value: str, existing_value: str) -> bool:
    """新值是否包含旧值的信息（旧值仍成立，只是不完整）。

    只做两种判定：字符串包含与词集包含。不做词形还原——
    那引入的误判比解决的问题多。
    """
    new = candidate_value.casefold().strip()
    old = existing_value.casefold().strip()
    if not new or not old or new == old:
        return False
    if old in new:
        return True
    old_tokens = set(old.split())
    new_tokens = set(new.split())
    return bool(old_tokens) and old_tokens.issubset(new_tokens)


def decide_by_rules(
    candidate: Candidate,
    *,
    existing: ExistingSnapshot | None,
) -> Decision:
    """按固定顺序应用七条规则，命中即短路。

    顺序不可随意调整；依据见 design.md D2，顺序由
    tests/resolver/test_rule_order.py 锁定。
    """
    key = candidate.normalized_key()
    base: dict[str, Any] = {
        "key": key,
        "normalized": key.normalized,
        "candidate_value": candidate.clean_value(),
        "change_source": candidate.change_source,
    }

    # 规则 1：该键下没有任何有效事实
    if existing is None:
        return Decision(kind=DecisionKind.ADD, rule="no_existing", **base)

    snapshot: dict[str, Any] = {
        **base,
        "existing_id": existing.id,
        "existing_value": existing.clean_value(),
    }

    same_condition = _norm_condition(candidate.condition) == _norm_condition(
        existing.condition
    )

    # 规则 2：完全相同的陈述（必须在"值包含"之前，否则会误判成 MERGE）
    if (
        same_condition
        and candidate.clean_value() == existing.clean_value()
        and candidate.authority == existing.authority
    ):
        return Decision(kind=DecisionKind.NOOP, rule="identical", **snapshot)

    # 规则 3：条件不同 → 并存（必须在"权威更低"之前，否则条件分支会被误判成冲突）
    if not same_condition:
        return Decision(kind=DecisionKind.BRANCH, rule="different_condition", **snapshot)

    # 规则 4：旧值仍成立，只是不完整（必须在"权威更低"之前，
    # 否则"推断出的补充信息"会因为权威低而被丢弃）
    if _contains(candidate.clean_value(), existing.clean_value()):
        return Decision(kind=DecisionKind.MERGE, rule="value_extends", **snapshot)

    # 规则 5：权威更低 → 标记冲突，不覆盖
    if candidate.authority < existing.authority:
        return Decision(kind=DecisionKind.CONFLICT, rule="lower_authority", **snapshot)

    # 规则 6：权威不低且确认是新状态 → 取代
    if candidate.is_new_state:
        return Decision(kind=DecisionKind.SUPERSEDE, rule="supersede_new_state", **snapshot)

    # 规则 7：兜底——无法确认是否新状态时宁可标冲突
    return Decision(
        kind=DecisionKind.CONFLICT, rule="unconfirmed_state_change", **snapshot
    )
