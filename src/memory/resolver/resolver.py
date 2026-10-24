"""判定编排：把候选事实变成 Decision，再把 Decision 变成存储操作。

两个方法的职责严格分开：

- `decide()` 只读。判定质量的评估需要在不写库的前提下批量跑，
  否则评测会把测试数据写进生产库。
- `apply()` 只写。它接收一个已确定的 Decision，不再重新判断，
  避免"判定与执行基于不同快照"的竞态。

六类到存储动作的映射见 design.md D1。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from memory.resolver.change_marker import ChangeSource, detect_change
from memory.resolver.rules import (
    Candidate,
    Decision,
    DecisionKind,
    ExistingSnapshot,
    decide_by_rules,
)
from memory.store.base import MemoryStore, NotFound
from memory.store.models import Authority, MemoryItem, Scope, Source, Status


@dataclass(frozen=True, slots=True)
class ResolverConfig:
    allow_llm: bool = True
    owner: str = "default"
    scope: Scope = Scope.PROJECT
    session_id: str = "resolver"


class ConflictResolver:
    def __init__(
        self,
        *,
        store: MemoryStore,
        config: ResolverConfig | None = None,
        llm: object | None = None,
    ) -> None:
        self._store = store
        self._config = config or ResolverConfig()
        self._llm = llm
        self.last_normalized: bool = True

    @property
    def config(self) -> ResolverConfig:
        return self._config

    def decide(
        self,
        *,
        subject: str,
        relation: str,
        value: str,
        text: str,
        condition: str | None = None,
        authority: Authority = Authority.USER_DIRECT,
        at: datetime | None = None,
    ) -> Decision:
        """只读判定。不产生任何写入。"""
        existing_item = self._find_existing(
            subject=subject,
            relation=relation,
            condition=condition,
            at=at or datetime.now(UTC),
        )
        existing = (
            ExistingSnapshot(
                id=existing_item.id,
                subject=existing_item.subject,
                relation=existing_item.relation,
                value=existing_item.value,
                condition=existing_item.condition,
                authority=existing_item.authority,
            )
            if existing_item is not None
            else None
        )

        marker = detect_change(
            text,
            llm=self._llm,
            allow_llm=self._config.allow_llm,
        )
        # 如果规则/模型明确说"不是新状态"，则覆盖默认的 is_new_state=True
        is_new_state = marker.is_new_state if marker.source is not ChangeSource.DISABLED else True

        candidate = Candidate(
            subject=subject,
            relation=relation,
            value=value,
            condition=condition,
            authority=authority,
            is_new_state=is_new_state,
            change_source=marker.source,
        )
        decision = decide_by_rules(candidate, existing=existing)
        self.last_normalized = decision.normalized
        return decision

    def apply(
        self,
        decision: Decision,
        *,
        value: str,
        text: str,
        reason: str,
        actor: str,
        condition: str | None = None,
        authority: Authority = Authority.USER_DIRECT,
        valid_from: datetime | None = None,
    ) -> str:
        """按判定结果执行存储操作，返回涉及的条目 id（新增或既有）。"""
        start = valid_from or datetime.now(UTC)
        item = MemoryItem(
            owner=self._config.owner,
            scope=self._config.scope,
            subject=decision.key.subject,
            relation=decision.key.relation,
            value=value,
            condition=condition,
            status=Status.ACTIVE,
            valid_from=start,
            valid_to=None,
            recorded_at=datetime.now(UTC),
            authority=authority,
            source=Source(session_id=self._config.session_id),
        )

        if decision.kind is DecisionKind.NOOP:
            return decision.existing_id or ""

        if decision.kind is DecisionKind.ADD:
            stored = self._store.insert(item, reason=reason, actor=actor)
            return stored.id

        if decision.kind is DecisionKind.BRANCH:
            stored = self._store.insert(item, reason=reason, actor=actor)
            return stored.id

        if decision.kind in (DecisionKind.MERGE, DecisionKind.SUPERSEDE):
            if decision.existing_id is None:
                raise NotFound("取代类判定缺少既有条目 id")
            stored = self._store.supersede(
                decision.existing_id, item, reason=reason, actor=actor
            )
            return stored.id

        if decision.kind is DecisionKind.CONFLICT:
            # 冲突候选直接以 CONFLICTED 落库：它不占用"当前有效值"的位置。
            stored = self._store.insert_conflicted(
                item,
                reason=reason,
                actor=actor,
                related_ids=(decision.existing_id,) if decision.existing_id else (),
            )
            return stored.id

        raise ValueError(f"未处理的判定类型：{decision.kind}")

    def _find_existing(
        self,
        *,
        subject: str,
        relation: str,
        condition: str | None,
        at: datetime,
    ) -> MemoryItem | None:
        """找到用于比较的既有条目。

        查找顺序：
        1. 同键、同条件
        2. 同键、无条件版本（新条目带条件时）
        3. 同键、**任意条件的 ACTIVE 条目**

        第 3 步是 BRANCH 判定的关键：新条目带 condition="rush" 时，
        必须能看见同键下 condition="normal" 的既有版本，否则会误判成 ADD，
        凭空造出重复的键。
        """
        from memory.resolver.normalize import normalize_key

        key = normalize_key(subject, relation)
        candidates = list(
            self._store.active_all(
                owner=self._config.owner,
                scope=self._config.scope,
                subject=key.subject,
                relation=key.relation,
                at=at,
            )
        )
        if not candidates:
            return None

        for item in candidates:
            if item.condition == condition:
                return item
        if condition is not None:
            for item in candidates:
                if item.condition is None:
                    return item
        return candidates[0]
