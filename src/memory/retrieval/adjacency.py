"""条件兄弟邻接召回。

**只做条件兄弟，不做跨关系**。设计审查已证：

- 跨关系那条路的 gold 就是查询命中自身（被"排除自身"规则显式去掉），
  所以它**永远召不回目标**，只会贡献干扰项
- 而条件兄弟是 BRANCH 场景的 gold 唯一可能被召回的路径

因此这条路径的定位很明确：服务 BRANCH，不服务多跳。
"""

from __future__ import annotations

from memory.store.models import MemoryItem, Scope, Status
from memory.store.sqlite import SqliteStore, _row_to_item


def recall_by_adjacency(
    store: SqliteStore,
    *,
    subject: str,
    relation: str,
    condition: str | None,
    owner: str = "o",
    scope: Scope = Scope.PROJECT,
    limit: int = 20,
) -> list[MemoryItem]:
    """返回同逻辑键下**不同条件**的 ACTIVE 条目。

    无条件条目也是兄弟：条件分支与无条件版本可以并存，
    所以 `IFNULL(condition,'') != IFNULL(?,'')` 会把它们互相召回。
    """
    rows = store.conn.execute(
        "SELECT * FROM items"
        " WHERE owner = ? AND scope = ? AND subject = ? AND relation = ?"
        "   AND status = 'ACTIVE'"
        "   AND IFNULL(condition,'') != IFNULL(?,'')"
        " ORDER BY ordinal DESC LIMIT ?",
        (owner, scope.value, subject, relation, condition, limit),
    ).fetchall()

    items = [_row_to_item(row) for row in rows]
    return [item for item in items if item.status is Status.ACTIVE]
