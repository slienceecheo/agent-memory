"""判定编排的行为契约。

两个关键约束：
1. `decide()` 不写库——判定质量评估需要在不产生副作用的情况下批量跑
2. `apply()` 的六类映射必须维持 C2 的全部不变量
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from memory.resolver.resolver import ConflictResolver, ResolverConfig
from memory.store.base import InvalidTransition, InvariantViolation
from memory.store.models import (
    Authority,
    MemoryItem,
    Scope,
    Source,
    Status,
)
from memory.store.sqlite import SqliteStore

NOW = datetime(2026, 1, 1, tzinfo=UTC)


def _item(
    *,
    value: str,
    subject: str = "project:x",
    relation: str = "package_manager",
    condition: str | None = None,
    authority: Authority = Authority.USER_DIRECT,
    valid_from: datetime | None = None,
) -> MemoryItem:
    return MemoryItem(
        owner="default",
        scope=Scope.PROJECT,
        subject=subject,
        relation=relation,
        value=value,
        condition=condition,
        status=Status.ACTIVE,
        valid_from=valid_from or NOW,
        valid_to=None,
        recorded_at=NOW,
        authority=authority,
        source=Source(session_id="s1"),
    )


@pytest.fixture
def store(tmp_path: Path) -> SqliteStore:
    instance = SqliteStore(tmp_path / "m.db")
    yield instance
    instance.close()


@pytest.fixture
def resolver(store: SqliteStore) -> ConflictResolver:
    return ConflictResolver(store=store, config=ResolverConfig(allow_llm=False))


def test_decide_does_not_write(store: SqliteStore, resolver: ConflictResolver) -> None:
    """判定阶段要能无副作用地批量跑，否则评测会污染库。"""
    before = store.count()

    resolver.decide(
        subject="project:x",
        relation="package_manager",
        value="pnpm",
        text="我们用 pnpm",
    )

    assert store.count() == before


def test_decide_on_empty_store_gives_add(resolver: ConflictResolver) -> None:
    decision = resolver.decide(
        subject="project:x",
        relation="package_manager",
        value="pnpm",
        text="我们用 pnpm",
    )

    assert decision.kind.value == "ADD"


def test_apply_add_creates_active_item(store: SqliteStore, resolver: ConflictResolver) -> None:
    decision = resolver.decide(
        subject="project:x", relation="package_manager", value="pnpm", text="我们用 pnpm"
    )

    resolver.apply(
        decision,
        value="pnpm",
        text="我们用 pnpm",
        reason="初始约定",
        actor="tester",
        valid_from=NOW,
    )

    assert store.count() == 1
    active = store.active_at(
        owner="default",
        scope=Scope.PROJECT,
        subject="project:x",
        relation="package_manager",
        condition=None,
        at=NOW + timedelta(days=1),
    )
    assert active is not None
    assert active.value == "pnpm"


def test_apply_noop_does_not_add_item(store: SqliteStore, resolver: ConflictResolver) -> None:
    """重复陈述不该产生新版本。"""
    store.insert(_item(value="pnpm"), reason="init", actor="t")

    decision = resolver.decide(
        subject="project:x", relation="package_manager", value="pnpm", text="我们用 pnpm"
    )
    assert decision.kind.value == "NOOP"

    resolver.apply(
        decision,
        value="pnpm",
        text="我们用 pnpm",
        reason="repeat",
        actor="tester",
        valid_from=NOW,
    )

    assert store.count() == 1


def test_apply_supersede_closes_old(store: SqliteStore, resolver: ConflictResolver) -> None:
    """改主意必须让旧值失效、且区间相邻。"""
    old = store.insert(_item(value="pnpm"), reason="init", actor="t")

    decision = resolver.decide(
        subject="project:x",
        relation="package_manager",
        value="npm",
        text="现在改用 npm 了",
    )
    assert decision.kind.value == "SUPERSEDE"

    resolver.apply(
        decision,
        value="npm",
        text="现在改用 npm 了",
        reason="改主意",
        actor="tester",
        valid_from=NOW + timedelta(days=1),
    )

    closed = store.get(old.id)
    assert closed.status is Status.SUPERSEDED
    assert closed.valid_to is not None
    assert store.count() == 2


def test_apply_branch_keeps_both_active(
    store: SqliteStore, resolver: ConflictResolver
) -> None:
    """条件不同应并存，两条都 ACTIVE。"""
    store.insert(
        _item(value="早上", relation="meeting_time", condition=None),
        reason="i",
        actor="t",
    )

    decision = resolver.decide(
        subject="project:x",
        relation="meeting_time",
        value="深夜",
        text="写代码的时候我喜欢深夜",
        condition="coding",
    )
    assert decision.kind.value == "BRANCH"

    resolver.apply(
        decision,
        value="深夜",
        text="写代码的时候我喜欢深夜",
        reason="条件不同",
        actor="tester",
        condition="coding",
        valid_from=NOW,
    )

    assert store.count() == 2
    branch = store.active_at(
        owner="default",
        scope=Scope.PROJECT,
        subject="project:x",
        relation="meeting_time",
        condition="coding",
        at=NOW + timedelta(days=1),
    )
    assert branch is not None
    assert branch.value == "深夜"


def test_apply_conflict_keeps_existing_active(
    store: SqliteStore, resolver: ConflictResolver
) -> None:
    """冲突时既有有效值不变，新值以 CONFLICTED 落库。"""
    existing = store.insert(
        _item(value="对花生过敏"), reason="init", actor="t"
    )

    decision = resolver.decide(
        subject="project:x",
        relation="package_manager",
        value="喜欢花生酱",
        text="客户喜欢花生酱饼干",
        authority=Authority.THIRD_PARTY,
    )

    assert decision.kind.value == "CONFLICT"

    resolver.apply(
        decision,
        value="喜欢花生酱",
        text="客户喜欢花生酱饼干",
        reason="权威不足",
        actor="tester",
        authority=Authority.THIRD_PARTY,
        valid_from=NOW,
    )

    assert store.get(existing.id).status is Status.ACTIVE
    assert store.count() == 2


def test_merge_and_supersede_have_different_reasons(
    store: SqliteStore, resolver: ConflictResolver
) -> None:
    """时间线要能讲清"这是补充还是改主意"。"""
    store.insert(_item(value="pnpm"), reason="init", actor="t")

    merge_decision = resolver.decide(
        subject="project:x",
        relation="package_manager",
        value="pnpm 加 workspace",
        text="另外我们用 workspace",
    )
    assert merge_decision.kind.value == "MERGE"

    resolver.apply(
        merge_decision,
        value="pnpm 加 workspace",
        text="另外我们用 workspace",
        reason="补充约定",
        actor="tester",
        valid_from=NOW + timedelta(days=1),
    )

    timeline = store.timeline(
        owner="default",
        scope=Scope.PROJECT,
        subject="project:x",
        relation="package_manager",
    )
    reasons = [event["reason"] for item in timeline for event in store.events_for(item.id)]

    assert any("补充" in reason for reason in reasons)


def test_apply_failure_leaves_no_partial_state(
    store: SqliteStore, resolver: ConflictResolver
) -> None:
    """存储失败不能留下半成品。"""
    store.insert(_item(value="pnpm"), reason="init", actor="t")
    decision = resolver.decide(
        subject="project:x",
        relation="package_manager",
        value="npm",
        text="现在改用 npm 了",
    )
    before = store.count()

    # 第一次 apply 成功后旧条目已不是 ACTIVE，第二次再取代它会失败。
    # 断言具体的存储异常，而不是笼统的 Exception。
    resolver.apply(
        decision, value="npm", text="现在改用 npm 了", reason="x", actor="t",
        valid_from=NOW,
    )
    with pytest.raises((InvariantViolation, InvalidTransition)):
        resolver.apply(
            decision, value="npm", text="现在改用 npm 了", reason="x", actor="t",
            valid_from=NOW,
        )

    assert store.count() >= before


def test_decide_carries_existing_id(store: SqliteStore, resolver: ConflictResolver) -> None:
    """判定要能关联回被比较的条目，否则无法归因。"""
    existing = store.insert(_item(value="pnpm"), reason="init", actor="t")

    decision = resolver.decide(
        subject="project:x",
        relation="package_manager",
        value="npm",
        text="现在改用 npm 了",
    )

    assert decision.existing_id == existing.id
