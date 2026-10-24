"""存储协议与异常类型。

为什么要有协议：C4 可能换 Postgres，C7 可能需要接远程存储。
契约测试通过 fixture 参数化，新增实现只需注册，不用改测试。

异常分类的设计理由：
- `ActiveExists`：调用 insert 但该键已有有效值——这是**用法错误**，应引导改用 supersede
- `InvariantViolation`：数据库层拒绝写入（唯一索引/重叠区间）——这是**不变量被违反**
- `InvalidTransition`：状态机不允许的迁移——这是**逻辑错误**
- `NotFound`：按 id 查不到
- `StoreBusy`：写锁竞争——这是**可重试的瞬时状态**

`StoreBusy` 与 `InvariantViolation` 必须分开：前者应重试，后者重试也没用。
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import Protocol, runtime_checkable

from memory.store.models import MemoryItem, Scope


class StoreError(Exception):
    """存储层错误基类。"""


class NotFound(StoreError):
    """按 id 或键找不到条目。"""


class ActiveExists(StoreError):
    """该逻辑键已有 ACTIVE 条目；调用方应改用 supersede。"""


class InvariantViolation(StoreError):
    """不变量被违反（唯一索引冲突、有效区间重叠）。"""


class InvalidTransition(StoreError):
    """非法的状态迁移。"""


class DimensionMismatch(StoreError):
    """向量维度与存储声明不一致。"""


class StoreBusy(StoreError):
    """写锁竞争导致本次操作失败；调用方可重试。"""


@runtime_checkable
class MemoryStore(Protocol):
    def insert(
        self,
        item: MemoryItem,
        *,
        reason: str,
        actor: str,
        embedding: Sequence[float] | None = None,
    ) -> MemoryItem:
        """插入一条新条目。该键已有 ACTIVE 时抛 `ActiveExists`。"""
        ...

    def insert_conflicted(
        self,
        item: MemoryItem,
        *,
        reason: str,
        actor: str,
        related_ids: Sequence[str] = (),
    ) -> MemoryItem:
        """插入一条 CONFLICTED 条目。

        它不占用"当前有效值"的位置，所以不受"同键已有 ACTIVE"的限制，
        但仍受唯一索引与区间重叠约束保护。
        """
        ...

    def supersede(
        self,
        old_id: str,
        new_item: MemoryItem,
        *,
        reason: str,
        actor: str,
        embedding: Sequence[float] | None = None,
    ) -> MemoryItem:
        """原子地把 old 关掉并插入 new。单事务完成。"""
        ...

    def mark_conflict(
        self,
        item_id: str,
        *,
        reason: str,
        actor: str,
        related_ids: Sequence[str] = (),
    ) -> MemoryItem:
        """把一条 ACTIVE 条目标记为未裁决冲突。

        冲突记录不占用"当前有效值"的位置：同键的 ACTIVE 条目仍然保留，
        这由唯一索引保证（CONFLICTED 不在 ux_active 的覆盖范围内）。
        """
        ...

    def retract(self, item_id: str, *, reason: str, actor: str) -> MemoryItem:
        """撤回一条条目（终止态）。"""
        ...

    def resolve_conflict(
        self,
        winner_id: str,
        loser_id: str,
        *,
        reason: str,
        actor: str,
    ) -> tuple[MemoryItem, MemoryItem]:
        """裁决冲突：胜者转 ACTIVE，败者转 SUPERSEDED 并写入 valid_to。"""
        ...

    def get(self, item_id: str) -> MemoryItem:
        """按 id 读取。"""
        ...

    def active_at(
        self,
        *,
        owner: str,
        scope: Scope,
        subject: str,
        relation: str,
        condition: str | None,
        at: datetime,
    ) -> MemoryItem | None:
        """查询某现实时间点有效的条目。"""
        ...

    def active_all(
        self,
        *,
        owner: str,
        scope: Scope,
        subject: str,
        relation: str,
        at: datetime,
    ) -> list[MemoryItem]:
        """同键下所有在 `at` 时刻有效的条目（含各条件分支）。

        判定 BRANCH 需要看到全部现存分支；只查精确匹配会把它们漏掉，
        从而把"并存"误判成"全新事实"。
        """
        ...

    def timeline(
        self,
        *,
        owner: str,
        scope: Scope,
        subject: str,
        relation: str,
    ) -> list[MemoryItem]:
        """返回该键下全部版本，按 version 升序。"""
        ...

    def count(self) -> int:
        """条目总数（含所有状态）。"""
        ...
