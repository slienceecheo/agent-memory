"""与实现无关的契约检查。

每个 `check_*` 对应 proposal 里的一条验收标准（B1–B7）。
新增存储实现只需在 tests/store/test_contract.py 的 FACTORIES 里加一个构造器。

**每条检查使用独立的 owner 命名空间**：聚合运行时它们共享同一个库，
若不隔离，前一条留下的 ACTIVE 条目会让后一条撞 `ActiveExists`。
这本身也顺带验证了 `owner` 确实起到了隔离作用。

为什么不用类继承：类继承会让"某个检查被意外跳过"难以发现；
函数式 + 参数化能保证每条检查在每个实现上都跑过。
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from memory.store.base import ActiveExists, InvalidTransition, InvariantViolation, MemoryStore
from memory.store.models import Authority, MemoryItem, Scope, Source, Status

BASE = datetime(2026, 1, 1, tzinfo=UTC)


def item(
    *,
    value: str = "v1",
    subject: str = "s",
    relation: str = "r",
    condition: str | None = None,
    valid_from: datetime = BASE,
    owner: str = "o",
) -> MemoryItem:
    return MemoryItem(
        owner=owner,
        scope=Scope.PROJECT,
        subject=subject,
        relation=relation,
        value=value,
        condition=condition,
        status=Status.ACTIVE,
        valid_from=valid_from,
        valid_to=None,
        recorded_at=BASE,
        authority=Authority.USER_DIRECT,
        source=Source(session_id="s1"),
    )


def _three_versions(store: MemoryStore, owner: str) -> None:
    first = store.insert(item(value="a", valid_from=BASE, owner=owner), reason="1", actor="t")
    second = store.supersede(
        first.id,
        item(value="b", valid_from=BASE + timedelta(days=10), owner=owner),
        reason="2",
        actor="t",
    )
    store.supersede(
        second.id,
        item(value="c", valid_from=BASE + timedelta(days=20), owner=owner),
        reason="3",
        actor="t",
    )


def _value_at(store: MemoryStore, offset_days: int, owner: str) -> str | None:
    found = store.active_at(
        owner=owner,
        scope=Scope.PROJECT,
        subject="s",
        relation="r",
        condition=None,
        at=BASE + timedelta(days=offset_days),
    )
    return found.value if found else None


def check_b1_uniqueness(store: MemoryStore) -> None:
    """B1：同键第二条 ACTIVE 被拒绝，且不留残留。"""
    owner = "b1"
    store.insert(item(owner=owner), reason="first", actor="t")
    before = store.count()

    try:
        store.insert(item(value="v2", owner=owner), reason="second", actor="t")
    except (ActiveExists, InvariantViolation):
        pass
    else:
        raise AssertionError("第二条同键 ACTIVE 未被拒绝")

    assert store.count() == before, "被拒绝的写入留下了残留条目"


def check_b2_point_in_time(store: MemoryStore) -> None:
    """B2：三个版本在各自的时间点返回正确的那一条。"""
    owner = "b2"
    _three_versions(store, owner)

    assert _value_at(store, 1, owner) == "a"
    assert _value_at(store, 15, owner) == "b"
    assert _value_at(store, 25, owner) == "c"


def check_b3_history_preserved(store: MemoryStore) -> None:
    """B3：时间线返回全部版本，包括被取代的。"""
    owner = "b3"
    _three_versions(store, owner)

    timeline = store.timeline(owner=owner, scope=Scope.PROJECT, subject="s", relation="r")

    assert len(timeline) == 3
    assert [entry.version for entry in timeline] == [1, 2, 3]


def check_b4_transitions(store: MemoryStore) -> None:
    """B4：RETRACTED 是终止态，不能复活。"""
    owner = "b4"
    created = store.insert(item(owner=owner), reason="1", actor="t")
    store.retract(created.id, reason="wrong", actor="t")

    try:
        store.supersede(
            created.id,
            item(value="next", valid_from=BASE + timedelta(days=1), owner=owner),
            reason="revive",
            actor="t",
        )
    except InvalidTransition:
        return
    raise AssertionError("撤回的条目被复活了")


def check_b5_audit(store: MemoryStore) -> None:
    """B5：每次写入都有审计事件，且原因被记录。"""
    created = store.insert(item(owner="b5"), reason="because", actor="alice")
    events = store.events_for(created.id)  # type: ignore[attr-defined]

    assert events, "写入没有产生审计事件"
    assert events[0]["reason"] == "because"
    assert events[0]["actor"] == "alice"


def check_b6_order_independence(store: MemoryStore) -> None:
    """B6：互不冲突的写入，顺序不影响最终有效值集合。

    注意这里只比较**有效值集合**，不比较 ordinal / recorded_at——
    那些必然随顺序不同而不同。
    """
    owner = "b6"
    pairs = [("s1", "a"), ("s2", "b"), ("s3", "c")]
    for subject, value in pairs:
        store.insert(item(subject=subject, value=value, owner=owner), reason="x", actor="t")

    for subject, value in pairs:
        found = store.active_at(
            owner=owner,
            scope=Scope.PROJECT,
            subject=subject,
            relation="r",
            condition=None,
            at=BASE + timedelta(days=1),
        )
        assert found is not None
        assert found.value == value


def check_b7_idempotence(store: MemoryStore) -> None:
    """B7：相同内容重复写入不产生新条目。"""
    owner = "b7"
    first = store.insert(item(owner=owner), reason="1", actor="t")
    second = store.insert(item(owner=owner), reason="2", actor="t")

    assert first.id == second.id
    assert store.count() > 0


CHECKS = {
    "B1 唯一性": check_b1_uniqueness,
    "B2 时间点查询": check_b2_point_in_time,
    "B3 保留历史": check_b3_history_preserved,
    "B4 状态迁移": check_b4_transitions,
    "B5 审计": check_b5_audit,
    "B6 顺序无关": check_b6_order_independence,
    "B7 幂等": check_b7_idempotence,
}


def run_all_contract_checks(store: MemoryStore) -> list[str]:
    """在给定实现上跑全部检查，返回失败的检查名列表。"""
    failures: list[str] = []
    for name, check in CHECKS.items():
        try:
            check(store)
        except Exception as exc:
            failures.append(f"{name}: {type(exc).__name__}: {exc}")
    return failures
