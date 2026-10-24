"""内容指纹的行为契约。

指纹决定"什么算重复"。搞错了会有两种后果：
- 太宽：用户改主意后写回旧值，被视为重复而丢失
- 太严：用户重复确认同一件事，产生一堆重复记忆

所以每个字段的取舍都对应一个具体场景。
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from memory.store.fingerprint import fingerprint
from memory.store.models import Authority, MemoryItem, Scope, Source, Status

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


def test_same_content_same_fingerprint() -> None:
    """指纹不稳定会让幂等完全失效。"""
    assert fingerprint(_item()) == fingerprint(_item())


def test_owner_matters() -> None:
    assert fingerprint(_item()) != fingerprint(_item(owner="other"))


def test_scope_matters() -> None:
    """project 级的包管理器与 user 级的偏好是两件事。"""
    assert fingerprint(_item()) != fingerprint(_item(scope=Scope.USER))


def test_subject_and_relation_matter() -> None:
    assert fingerprint(_item()) != fingerprint(_item(subject="project:other"))
    assert fingerprint(_item()) != fingerprint(_item(relation="test_runner"))


def test_value_matters() -> None:
    assert fingerprint(_item()) != fingerprint(_item(value="npm"))


def test_condition_matters() -> None:
    """条件不同是不同的事实，不能互相覆盖。"""
    assert fingerprint(_item()) != fingerprint(_item(condition="morning"))


def test_condition_none_equals_empty_string() -> None:
    """空串已在模型层归一为 None；指纹必须与之一致。"""
    assert fingerprint(_item(condition=None)) == fingerprint(_item(condition=""))


def test_authority_matters() -> None:
    """用户自述与工单备注不是同一件事：置信度不同，冲突处理也不同。"""
    assert fingerprint(_item()) != fingerprint(
        _item(authority=Authority.THIRD_PARTY)
    )


def test_source_session_does_not_matter() -> None:
    """同一事实从不同 session 说出应视为同一条，否则重复确认会造出一堆记忆。"""
    assert fingerprint(_item()) == fingerprint(
        _item(source=Source(session_id="totally-different", turn_id=9))
    )


def test_recorded_at_does_not_matter() -> None:
    """含时间戳会让每次写入都不同，幂等必然失效。"""
    later = NOW + timedelta(hours=5)
    assert fingerprint(_item()) == fingerprint(_item(recorded_at=later))


def test_status_does_not_matter() -> None:
    """指纹描述"内容"，不描述"状态"。状态由幂等逻辑另行判断。"""
    assert fingerprint(_item()) == fingerprint(_item(status=Status.SUPERSEDED))


def test_valid_from_does_not_matter() -> None:
    """同一事实的两个不重叠有效期由 supersede 的区间逻辑处理，不靠指纹区分。

    若纳入指纹，"重复确认同一事实"每次都会产生新版本。
    """
    assert fingerprint(_item()) == fingerprint(_item(valid_from=NOW + timedelta(days=1)))


def test_fingerprint_is_hex_of_64_chars() -> None:
    value = fingerprint(_item())
    assert len(value) == 64
    assert set(value) <= set("0123456789abcdef")


def test_field_separator_prevents_collision() -> None:
    """("ab","c") 与 ("a","bc") 不能撞成同一个指纹。"""
    a = _item(subject="ab", relation="c")
    b = _item(subject="a", relation="bc")
    assert fingerprint(a) != fingerprint(b)


def test_unicode_is_stable() -> None:
    assert fingerprint(_item(value="北京")) == fingerprint(_item(value="北京"))
    assert fingerprint(_item(value="北京")) != fingerprint(_item(value="上海"))
