"""数据模型的行为契约。

每一条断言对应一个具体的破坏：去掉它，某个真实场景会静默出错。
"""

from __future__ import annotations

import dataclasses
from datetime import UTC, datetime, timedelta, timezone

import pytest

from memory.store.models import (
    Authority,
    InvalidItem,
    MemoryItem,
    Scope,
    Source,
    Status,
)

NOW = datetime(2026, 10, 25, 12, 0, tzinfo=UTC)


def _item(**overrides: object) -> MemoryItem:
    base: dict[str, object] = {
        "owner": "default",
        "scope": Scope.PROJECT,
        "subject": "project:agent-memory",
        "relation": "package_manager",
        "value": "pnpm",
        "condition": None,
        "status": Status.ACTIVE,
        "valid_from": NOW,
        "valid_to": None,
        "recorded_at": NOW,
        "authority": Authority.USER_DIRECT,
        "source": Source(session_id="s1", turn_id=1, speaker="user"),
    }
    base.update(overrides)
    return MemoryItem(**base)  # type: ignore[arg-type]


def test_naive_datetime_is_rejected() -> None:
    """无时区时间在 UTC+8 机器上会静默偏差 8 小时，必须拒绝。"""
    with pytest.raises(InvalidItem, match="时区"):
        _item(valid_from=datetime(2026, 10, 25, 12, 0))


def test_naive_recorded_at_is_rejected() -> None:
    with pytest.raises(InvalidItem, match="时区"):
        _item(recorded_at=datetime(2026, 10, 25, 12, 0))


def test_valid_to_must_be_after_valid_from() -> None:
    """零长度区间既查不到又占着有效位，是最难查的那类脏数据。"""
    with pytest.raises(InvalidItem, match="valid_to"):
        _item(valid_to=NOW)


def test_valid_to_before_valid_from_is_rejected() -> None:
    with pytest.raises(InvalidItem, match="valid_to"):
        _item(valid_to=NOW - timedelta(seconds=1))


def test_valid_to_none_is_allowed() -> None:
    """未结束的有效期是正常状态，不能因为缺少结束时间被拒。"""
    assert _item(valid_to=None).valid_to is None


def test_empty_condition_becomes_none() -> None:
    """空串与 None 若并存，唯一索引会把它们当成两条不同的行。"""
    assert _item(condition="").condition is None


def test_whitespace_condition_becomes_none() -> None:
    assert _item(condition="   ").condition is None


def test_condition_is_trimmed() -> None:
    assert _item(condition="  morning  ").condition == "morning"


@pytest.mark.parametrize("field", ["owner", "subject", "relation", "value"])
def test_empty_key_fields_are_rejected(field: str) -> None:
    """键列为空会让唯一索引失去意义（NULL 互不相等）。"""
    with pytest.raises(InvalidItem, match=field):
        _item(**{field: ""})


@pytest.mark.parametrize("field", ["owner", "subject", "relation", "value"])
def test_whitespace_key_fields_are_rejected(field: str) -> None:
    with pytest.raises(InvalidItem, match=field):
        _item(**{field: "   "})


def test_scope_rejects_unknown_value() -> None:
    """自由字符串会让 scope 过滤静默失效。"""
    with pytest.raises(ValueError):
        _item(scope="galaxy")


def test_scope_accepts_all_four_values() -> None:
    for scope in (Scope.USER, Scope.PROJECT, Scope.TASK, Scope.LESSON):
        assert _item(scope=scope).scope is scope


def test_authority_rejects_unknown_value() -> None:
    with pytest.raises(ValueError):
        _item(authority="god")


def test_authority_ordering_is_explicit() -> None:
    """规则表要比较权威高低，必须有一个确定的全序。"""
    assert Authority.USER_DIRECT > Authority.USER_DOCUMENT
    assert Authority.USER_DOCUMENT > Authority.SYSTEM_INFERRED
    assert Authority.SYSTEM_INFERRED > Authority.THIRD_PARTY


def test_different_condition_is_a_different_item() -> None:
    """条件分支必须能与无条件版本区分，否则条件冲突无法表达。"""
    plain = _item()
    branch = _item(condition="morning")

    assert plain.key() != branch.key()


def test_key_ignores_value_and_status() -> None:
    """逻辑键只由定位字段构成；值与状态是被存的内容，不是身份。"""
    a = _item(value="pnpm")
    b = _item(value="npm", status=Status.SUPERSEDED)

    assert a.key() == b.key()


def test_key_includes_owner_and_scope() -> None:
    assert _item().key() != _item(owner="other").key()
    assert _item().key() != _item(scope=Scope.USER).key()


def test_status_roundtrip_from_string() -> None:
    assert Status("ACTIVE") is Status.ACTIVE


def test_times_are_normalized_to_utc() -> None:
    """同一时刻的不同时区表示必须归一，否则字符串比较会错。"""
    tokyo = timezone(timedelta(hours=9))
    local = datetime(2026, 10, 25, 21, 0, tzinfo=tokyo)
    utc = datetime(2026, 10, 25, 12, 0, tzinfo=UTC)

    assert _item(valid_from=local).valid_from == _item(valid_from=utc).valid_from


def test_item_is_frozen() -> None:
    """条目一旦构造就不该被就地修改，否则迁移逻辑会出现隐式状态。"""
    item = _item()
    with pytest.raises(dataclasses.FrozenInstanceError):
        item.value = "npm"  # type: ignore[misc]
