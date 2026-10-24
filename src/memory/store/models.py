"""记忆条目的数据模型。

设计要点（见 openspec/changes/memory-store/design.md）：

- 时间必须带时区，内部统一转 UTC。无时区时间在 UTC+8 机器上会静默偏差 8 小时。
- `condition` 的空串/纯空白统一归一为 `None`，否则唯一索引会把它们视为不同的行
  （SQLite 中 NULL 互不相等，这是唯一索引最大的坑）。
- 键列不允许为空，理由同上。
- 条目冻结（frozen），状态变化一律通过返回新对象完成，避免隐式就地修改。
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any


class InvalidItem(ValueError):
    """条目字段不合法。"""


class Status(StrEnum):
    ACTIVE = "ACTIVE"
    SUPERSEDED = "SUPERSEDED"
    CONFLICTED = "CONFLICTED"
    RETRACTED = "RETRACTED"


class Scope(StrEnum):
    USER = "user"
    PROJECT = "project"
    TASK = "task"
    LESSON = "lesson"


class Authority(StrEnum):
    """来源权威级别。数值越大越可信，用于冲突判定时比较高低。"""

    THIRD_PARTY = "third_party"
    SYSTEM_INFERRED = "system_inferred"
    USER_DOCUMENT = "user_document"
    USER_DIRECT = "user_direct"

    @property
    def rank(self) -> int:
        return _AUTHORITY_RANK[self]

    def __gt__(self, other: object) -> bool:
        if not isinstance(other, Authority):
            return NotImplemented
        return self.rank > other.rank

    def __lt__(self, other: object) -> bool:
        if not isinstance(other, Authority):
            return NotImplemented
        return self.rank < other.rank

    def __ge__(self, other: object) -> bool:
        if not isinstance(other, Authority):
            return NotImplemented
        return self.rank >= other.rank

    def __le__(self, other: object) -> bool:
        if not isinstance(other, Authority):
            return NotImplemented
        return self.rank <= other.rank


_AUTHORITY_RANK: dict[Authority, int] = {
    Authority.THIRD_PARTY: 0,
    Authority.SYSTEM_INFERRED: 1,
    Authority.USER_DOCUMENT: 2,
    Authority.USER_DIRECT: 3,
}


@dataclass(frozen=True, slots=True)
class Source:
    session_id: str
    turn_id: int | None = None
    speaker: str = "user"

    def __post_init__(self) -> None:
        if not self.session_id.strip():
            raise InvalidItem("source.session_id 不能为空。")


def _as_utc(field_name: str, value: datetime) -> datetime:
    if value.tzinfo is None or value.tzinfo.utcoffset(value) is None:
        raise InvalidItem(
            f"{field_name} 必须带时区（例如 timezone.utc），收到无时区的 {value!r}。"
            "无时区时间会在 UTC+8 机器上产生 8 小时的静默偏差。"
        )
    return value.astimezone(UTC)


def normalize_condition(condition: str | None) -> str | None:
    """空串与纯空白统一为 None，其余去首尾空白。"""
    if condition is None:
        return None
    trimmed = condition.strip()
    return trimmed or None


def _require_text(field_name: str, value: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise InvalidItem(f"{field_name} 不能为空或纯空白。")
    return value.strip()


def _coerce_enum(field_name: str, enum_type: Any, value: Any) -> Any:
    """把原始字符串转成枚举；非法值抛 ValueError 并列出可用值。"""
    if isinstance(value, enum_type):
        return value
    try:
        return enum_type(value)
    except ValueError as exc:
        allowed = ", ".join(member.value for member in enum_type)
        raise ValueError(f"{field_name} 只能是 {allowed}，收到 {value!r}。") from exc


@dataclass(frozen=True, slots=True)
class MemoryItem:
    owner: str
    scope: Scope
    subject: str
    relation: str
    value: str
    condition: str | None
    status: Status
    valid_from: datetime
    valid_to: datetime | None
    recorded_at: datetime
    authority: Authority
    source: Source
    id: str = field(default="")
    version: int = field(default=0)
    ordinal: int = field(default=0)
    superseded_by: str | None = field(default=None)
    linked_ids: tuple[str, ...] = field(default=())
    confidence: float = field(default=1.0)

    def __post_init__(self) -> None:
        object.__setattr__(self, "owner", _require_text("owner", self.owner))
        object.__setattr__(self, "subject", _require_text("subject", self.subject))
        object.__setattr__(self, "relation", _require_text("relation", self.relation))
        object.__setattr__(self, "value", _require_text("value", self.value))
        object.__setattr__(self, "condition", normalize_condition(self.condition))

        # StrEnum 继承自 str，所以 "galaxy" 能通过类型检查但语义非法。
        # 必须显式转换，否则非法 scope/status/authority 会静默进入数据库。
        object.__setattr__(self, "scope", _coerce_enum("scope", Scope, self.scope))
        object.__setattr__(self, "status", _coerce_enum("status", Status, self.status))
        object.__setattr__(
            self, "authority", _coerce_enum("authority", Authority, self.authority)
        )

        object.__setattr__(self, "valid_from", _as_utc("valid_from", self.valid_from))
        object.__setattr__(self, "recorded_at", _as_utc("recorded_at", self.recorded_at))

        if self.valid_to is not None:
            normalized_to = _as_utc("valid_to", self.valid_to)
            object.__setattr__(self, "valid_to", normalized_to)
            if normalized_to <= self.valid_from:
                raise InvalidItem(
                    f"valid_to 必须晚于 valid_from，收到 {self.valid_to} <= {self.valid_from}。"
                    "零长度区间既查不到，又会永久占用该键的有效位。"
                )

        if not 0.0 <= self.confidence <= 1.0:
            raise InvalidItem(f"confidence 必须在 [0,1] 内，收到 {self.confidence}")

    def key(self) -> tuple[str, str, str, str, str | None]:
        """逻辑键。只由定位字段构成，不含值、状态、时间。"""
        return (self.owner, self.scope.value, self.subject, self.relation, self.condition)

    def with_status(self, status: Status, **changes: Any) -> MemoryItem:
        return replace(self, status=status, **changes)

    @property
    def is_open_ended(self) -> bool:
        return self.valid_to is None
