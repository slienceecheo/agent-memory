"""SQLite 存储实现。

四个实测坑与对应做法（验证见 docs/store.md）：

1. NULL 在唯一索引中互不相等 → 键列 NOT NULL + 非空 CHECK，
   且唯一索引对 `condition` 用 `IFNULL(condition,'')`。
2. `t < NULL` 求值为 NULL → 区间比较一律用
   `(:t < valid_to OR valid_to IS NULL)` 或 `COALESCE(valid_to, 哨兵)`。
3. `INSERT OR REPLACE` 绕过 BEFORE DELETE 触发器 → 开 `recursive_triggers`
   并加 BEFORE INSERT 触发器拒绝重复 seq。
4. FTS5 无中文分词 → Python 侧 bigram 切词，写入与查询共用同一函数。

事务管理：连接以 `isolation_level=None` 打开，所有写操作显式
`BEGIN IMMEDIATE`，保证 `MAX(ordinal)+1` 与唯一性检查之间不被插入别的写入。
"""

from __future__ import annotations

import dataclasses
import json
import sqlite3
import uuid
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from memory.store.base import (
    ActiveExists,
    DimensionMismatch,
    InvalidTransition,
    InvariantViolation,
    NotFound,
    StoreBusy,
)
from memory.store.fingerprint import fingerprint
from memory.store.models import Authority, MemoryItem, Scope, Source, Status

_FAR_FUTURE = "9999-12-31T23:59:59.999999+00:00"
_EPOCH = "0001-01-01T00:00:00.000000+00:00"
# 区间退化时使用的最小宽度：1 微秒。保证 valid_to 严格大于 valid_from。
_MIN_DURATION = timedelta(microseconds=1)

# 状态迁移矩阵的前驱集合（同状态视为幂等空操作，另行判断）
_LEGAL_TRANSITIONS: dict[Status, frozenset[Status]] = {
    Status.ACTIVE: frozenset({Status.SUPERSEDED, Status.CONFLICTED, Status.RETRACTED}),
    Status.CONFLICTED: frozenset(
        {Status.ACTIVE, Status.SUPERSEDED, Status.RETRACTED}
    ),
    Status.SUPERSEDED: frozenset({Status.RETRACTED}),
    Status.RETRACTED: frozenset(),
}

_SCHEMA = f"""
CREATE TABLE IF NOT EXISTS items (
    id            TEXT PRIMARY KEY,
    owner         TEXT NOT NULL CHECK (length(trim(owner)) > 0),
    scope         TEXT NOT NULL CHECK (scope IN ('user','project','task','lesson')),
    subject       TEXT NOT NULL CHECK (length(trim(subject)) > 0),
    relation      TEXT NOT NULL CHECK (length(trim(relation)) > 0),
    condition     TEXT,
    value         TEXT NOT NULL CHECK (length(trim(value)) > 0),
    status        TEXT NOT NULL CHECK (
                    status IN ('ACTIVE','SUPERSEDED','CONFLICTED','RETRACTED')),
    valid_from    TEXT NOT NULL,
    valid_to      TEXT,
    recorded_at   TEXT NOT NULL,
    authority     TEXT NOT NULL CHECK (
                    authority IN ('third_party','system_inferred',
                                  'user_document','user_direct')),
    session_id    TEXT NOT NULL,
    turn_id       INTEGER,
    speaker       TEXT NOT NULL DEFAULT 'user',
    fingerprint   TEXT NOT NULL,
    fingerprint_key TEXT NOT NULL,
    ordinal       INTEGER NOT NULL,
    version       INTEGER NOT NULL,
    superseded_by TEXT,
    linked_ids    TEXT NOT NULL DEFAULT '[]',
    confidence    REAL NOT NULL DEFAULT 1.0,
    source_text   TEXT,
    CHECK (valid_to IS NULL OR valid_to > valid_from),
    CHECK (confidence >= 0.0 AND confidence <= 1.0)
);

-- 核心不变量：同键至多一条 ACTIVE。
-- IFNULL 不可省：SQLite 中 NULL 互不相等，否则空条件会绕过约束。
CREATE UNIQUE INDEX IF NOT EXISTS ux_active
    ON items(owner, scope, subject, relation, IFNULL(condition,''))
    WHERE status = 'ACTIVE';

CREATE UNIQUE INDEX IF NOT EXISTS ux_version
    ON items(owner, scope, subject, relation, IFNULL(condition,''), version);

CREATE UNIQUE INDEX IF NOT EXISTS ux_ordinal ON items(ordinal);

CREATE INDEX IF NOT EXISTS ix_lookup
    ON items(owner, scope, subject, relation, IFNULL(condition,''));

-- 有效区间不得重叠（未撤回的条目之间）。
-- COALESCE 不可省：裸比较里 NULL 会让未结束区间永远不参与检测。
CREATE TRIGGER IF NOT EXISTS items_no_overlap_ins
BEFORE INSERT ON items
WHEN NEW.status NOT IN ('RETRACTED','CONFLICTED')
BEGIN
    SELECT RAISE(ABORT, 'overlapping valid interval')
    WHERE EXISTS (
        SELECT 1 FROM items
        WHERE owner = NEW.owner AND scope = NEW.scope
          AND subject = NEW.subject AND relation = NEW.relation
          AND IFNULL(condition,'') = IFNULL(NEW.condition,'')
          AND status NOT IN ('RETRACTED','CONFLICTED')
          AND NEW.valid_from < COALESCE(valid_to, '{_FAR_FUTURE}')
          AND COALESCE(NEW.valid_to, '{_FAR_FUTURE}') > valid_from
    );
END;

CREATE TRIGGER IF NOT EXISTS items_no_overlap_upd
BEFORE UPDATE OF valid_from, valid_to, status, condition ON items
WHEN NEW.status NOT IN ('RETRACTED','CONFLICTED')
BEGIN
    SELECT RAISE(ABORT, 'overlapping valid interval')
    WHERE EXISTS (
        SELECT 1 FROM items
        WHERE id != NEW.id
          AND owner = NEW.owner AND scope = NEW.scope
          AND subject = NEW.subject AND relation = NEW.relation
          AND IFNULL(condition,'') = IFNULL(NEW.condition,'')
          AND status NOT IN ('RETRACTED','CONFLICTED')
          AND NEW.valid_from < COALESCE(valid_to, '{_FAR_FUTURE}')
          AND COALESCE(NEW.valid_to, '{_FAR_FUTURE}') > valid_from
    );
END;

CREATE TABLE IF NOT EXISTS events (
    seq             INTEGER PRIMARY KEY AUTOINCREMENT,
    item_id         TEXT NOT NULL,
    related_item_id TEXT,
    decision        TEXT NOT NULL CHECK (
                      decision IN ('ADD','NOOP','SUPERSEDE','CONFLICT','BRANCH',
                                   'RETRACT','RESOLVE','CORRECTION','MERGE')),
    reason          TEXT NOT NULL CHECK (length(trim(reason)) > 0),
    actor           TEXT NOT NULL CHECK (length(trim(actor)) > 0),
    at              TEXT NOT NULL
);

-- 审计只追加：三个触发器缺一不可。
-- 只有 UPDATE/DELETE 时，INSERT OR REPLACE 会绕过（实测）。
CREATE TRIGGER IF NOT EXISTS events_no_update
BEFORE UPDATE ON events
BEGIN SELECT RAISE(ABORT, 'audit events are append-only'); END;

CREATE TRIGGER IF NOT EXISTS events_no_delete
BEFORE DELETE ON events
BEGIN SELECT RAISE(ABORT, 'audit events are append-only'); END;

CREATE TRIGGER IF NOT EXISTS events_no_replace
BEFORE INSERT ON events
WHEN EXISTS (SELECT 1 FROM events WHERE seq = NEW.seq)
BEGIN SELECT RAISE(ABORT, 'audit events are append-only'); END;

CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS vec_items (
    item_id TEXT PRIMARY KEY REFERENCES items(id) ON DELETE CASCADE,
    vector  BLOB NOT NULL,
    dims    INTEGER NOT NULL
);
"""

_FTS_SCHEMA = """
CREATE VIRTUAL TABLE IF NOT EXISTS items_fts
USING fts5(item_id UNINDEXED, tokens);
"""


def to_utc_text(value: datetime) -> str:
    """统一格式化为 UTC ISO-8601（带微秒与偏移）。

    秒级精度会让同一秒内的多次写入在 active_at 边界上判错。
    """
    if value.tzinfo is None:
        raise ValueError(f"时间必须带时区，收到无时区的 {value!r}")
    return value.astimezone(UTC).isoformat(timespec="microseconds")


def from_utc_text(value: str) -> datetime:
    return datetime.fromisoformat(value)


def tokenize(text: str) -> str:
    """把正文切成空格分隔的 token：中文按 2 字滑窗，英文/数字按词。

    FTS5 的 unicode61 把整段中文当一个 token，实测 `项目使用包管理器`
    对 `包管理` 查询返回 0 条。必须自己做 bigram。
    """
    tokens: list[str] = []
    buffer: list[str] = []

    def flush() -> None:
        if buffer:
            tokens.append("".join(buffer))
            buffer.clear()

    for char in text:
        if "\u4e00" <= char <= "\u9fff":
            flush()
            tokens.append(char)
        elif char.isalnum():
            buffer.append(char.lower())
        else:
            flush()

    flush()

    # 中文单字与英文词各自保留，同时补充相邻中文的 bigram
    bigrams: list[str] = []
    for index in range(len(tokens) - 1):
        left, right = tokens[index], tokens[index + 1]
        if len(left) == 1 and len(right) == 1:
            bigrams.extend([left, right, left + right])

    merged = list(dict.fromkeys([*tokens, *bigrams]))
    return " ".join(merged)


class SqliteStore:
    def __init__(
        self,
        path: Path | str,
        *,
        embedding_dims: int = 1024,
        timeout_seconds: float = 5.0,
    ) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._timeout = timeout_seconds
        self._conn = sqlite3.connect(
            str(self.path), isolation_level=None, timeout=timeout_seconds
        )
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys = ON")
        # 必须开：否则 INSERT OR REPLACE 会绕过 BEFORE DELETE（实测）
        self._conn.execute("PRAGMA recursive_triggers = ON")
        self._conn.executescript(_SCHEMA)
        self._conn.executescript(_FTS_SCHEMA)
        self._init_meta(embedding_dims)

    # ---------- 生命周期 ----------

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> SqliteStore:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    def _init_meta(self, embedding_dims: int) -> None:
        row = self._conn.execute(
            "SELECT value FROM meta WHERE key = 'embedding_dims'"
        ).fetchone()
        if row is None:
            self._conn.execute(
                "INSERT INTO meta (key, value) VALUES ('embedding_dims', ?)",
                (str(embedding_dims),),
            )
        elif int(row["value"]) != embedding_dims:
            raise ValueError(
                f"库中声明的向量维度为 {row['value']}，与本次配置 {embedding_dims} 不一致。"
                "维度不同会让向量距离不可比，请换库或改配置。"
            )

    def embedding_dims(self) -> int:
        row = self._conn.execute(
            "SELECT value FROM meta WHERE key = 'embedding_dims'"
        ).fetchone()
        return int(row["value"])

    def recursive_triggers_enabled(self) -> bool:
        return bool(self._conn.execute("PRAGMA recursive_triggers").fetchone()[0])

    def event_count(self) -> int:
        return int(self._conn.execute("SELECT COUNT(*) FROM events").fetchone()[0])

    def event_sequences(self) -> list[int]:
        rows = self._conn.execute("SELECT seq FROM events ORDER BY seq").fetchall()
        return [int(row["seq"]) for row in rows]

    def events_for(self, item_id: str) -> list[dict[str, Any]]:
        """返回某条目的审计事件，按追加顺序。"""
        rows = self._conn.execute(
            "SELECT * FROM events WHERE item_id = ? OR related_item_id = ? ORDER BY seq",
            (item_id, item_id),
        ).fetchall()
        return [dict(row) for row in rows]

    def embedding_of(self, item_id: str) -> Any:
        """返回条目的向量；没有则返回 None。"""
        import numpy as np

        row = self._conn.execute(
            "SELECT vector, dims FROM vec_items WHERE item_id = ?", (item_id,)
        ).fetchone()
        if row is None:
            return None
        return np.frombuffer(row["vector"], dtype=np.float32).copy()

    def search_text(self, query: str, *, limit: int = 20) -> list[MemoryItem]:
        """在当前有效（ACTIVE）的条目里做词面检索。

        中文按 bigram；单字不是 bigram，降级为 LIKE 前缀匹配
        （FTS5 的 unicode61 把整段中文当一个 token，实测单字查不到）。

        **按 BM25 排序**，而不是按 version：version 是键内序号，跨键无序，
        用它排序会让 RRF 拿到一个假排名。
        """
        tokens = tokenize(query).split()
        multi_char = [token for token in tokens if len(token) > 1]

        if multi_char:
            expression = " OR ".join(_escape_fts(token) for token in multi_char)
            rows = self._conn.execute(
                "SELECT i.* FROM items_fts f JOIN items i ON i.id = f.item_id"
                " WHERE items_fts MATCH ? AND i.status = 'ACTIVE'"
                " ORDER BY bm25(items_fts) ASC, i.ordinal DESC LIMIT ?",
                (expression, limit),
            ).fetchall()
            if rows:
                return [_row_to_item(row) for row in rows]

        # 单字或 bigram 未命中：降级为 LIKE（覆盖单字查询与小数据集）
        like = f"%{query}%"
        rows = self._conn.execute(
            "SELECT * FROM items WHERE status = 'ACTIVE'"
            " AND (value LIKE ? OR subject LIKE ? OR relation LIKE ? OR source_text LIKE ?)"
            " ORDER BY ordinal DESC LIMIT ?",
            (like, like, like, like, limit),
        ).fetchall()
        return [_row_to_item(row) for row in rows]

    # ---------- 事务 ----------

    @contextmanager
    def _write(self) -> Iterator[sqlite3.Connection]:
        """显式 BEGIN IMMEDIATE。

        不用默认的隐式事务：它不会为读加写锁，`MAX(ordinal)+1` 会与并发写撞。
        """
        try:
            self._conn.execute("BEGIN IMMEDIATE")
        except sqlite3.OperationalError as exc:
            if "locked" in str(exc) or "busy" in str(exc):
                raise StoreBusy(
                    "数据库正被另一个写入占用，请稍后重试。"
                ) from exc
            raise
        try:
            yield self._conn
        except Exception:
            self._conn.execute("ROLLBACK")
            raise
        else:
            self._conn.execute("COMMIT")

    # ---------- 读取 ----------

    def count(self) -> int:
        return int(self._conn.execute("SELECT COUNT(*) FROM items").fetchone()[0])

    def get(self, item_id: str) -> MemoryItem:
        row = self._conn.execute("SELECT * FROM items WHERE id = ?", (item_id,)).fetchone()
        if row is None:
            raise NotFound(f"找不到条目 {item_id}")
        return _row_to_item(row)

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
        at_text = to_utc_text(at)
        row = self._conn.execute(
            "SELECT * FROM items"
            " WHERE owner = ? AND scope = ? AND subject = ? AND relation = ?"
            "   AND IFNULL(condition,'') = IFNULL(?,'')"
            "   AND status IN ('ACTIVE','SUPERSEDED')"
            "   AND valid_from <= ?"
            "   AND (? < valid_to OR valid_to IS NULL)",
            (owner, scope.value, subject, relation, condition, at_text, at_text),
        ).fetchone()
        return _row_to_item(row) if row else None

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

        判定 BRANCH 需要看到全部现存分支，只看精确匹配会漏掉它们。
        """
        at_text = to_utc_text(at)
        rows = self._conn.execute(
            "SELECT * FROM items"
            " WHERE owner = ? AND scope = ? AND subject = ? AND relation = ?"
            "   AND status = 'ACTIVE'"
            "   AND valid_from <= ?"
            "   AND (? < valid_to OR valid_to IS NULL)"
            " ORDER BY version ASC",
            (owner, scope.value, subject, relation, at_text, at_text),
        ).fetchall()
        return [_row_to_item(row) for row in rows]

    def timeline(
        self,
        *,
        owner: str,
        scope: Scope,
        subject: str,
        relation: str,
    ) -> list[MemoryItem]:
        rows = self._conn.execute(
            "SELECT * FROM items"
            " WHERE owner = ? AND scope = ? AND subject = ? AND relation = ?"
            " ORDER BY version ASC",
            (owner, scope.value, subject, relation),
        ).fetchall()
        return [_row_to_item(row) for row in rows]

    # ---------- 写入 ----------

    def insert(
        self,
        item: MemoryItem,
        *,
        reason: str,
        actor: str,
        embedding: Sequence[float] | None = None,
        allow_duplicate_active: bool = False,
    ) -> MemoryItem:
        """插入一条新条目。

        `allow_duplicate_active=True` 时跳过"该键已有 ACTIVE"的前置检查，
        但仍受唯一索引与区间重叠约束保护。它只用于插入**非 ACTIVE** 的条目
        （例如冲突候选），调用方必须自己保证 item.status 不是 ACTIVE。
        """
        with self._write() as conn:
            if not allow_duplicate_active:
                existing = self._find_active(conn, item)
                if existing is not None:
                    if existing["fingerprint"] == fingerprint(item):
                        # 事件必须挂到已存在条目的 id 上：新构造的 item.id 还是空字符串
                        self._audit(conn, existing["id"], None, "NOOP", reason, actor)
                        return _row_to_item(existing)
                    raise ActiveExists(
                        f"键 {item.key()} 已有 ACTIVE 条目 {existing['id']}；"
                        "若要替换请使用 supersede()。"
                    )

            stored = self._materialize(conn, item)
            self._write_item(conn, stored, embedding)
            self._write_fts(conn, stored)
            self._audit(conn, stored.id, None, "ADD", reason, actor)
            return stored

    def supersede(
        self,
        old_id: str,
        new_item: MemoryItem,
        *,
        reason: str,
        actor: str,
        embedding: Sequence[float] | None = None,
    ) -> MemoryItem:
        with self._write() as conn:
            old_row = conn.execute(
                "SELECT * FROM items WHERE id = ?", (old_id,)
            ).fetchone()
            if old_row is None:
                raise NotFound(f"找不到要取代的条目 {old_id}")
            old = _row_to_item(old_row)
            self._check_transition(old, Status.SUPERSEDED)

            # 同一时刻改主意是正常场景（比如同一分钟内改了两次）。
            # 这时把新条目的起点推到旧起点之后 1 微秒，而不是报错让调用方自己处理。
            new_valid_from = new_item.valid_from
            if new_valid_from <= old.valid_from:
                new_valid_from = old.valid_from + _MIN_DURATION
                new_item = dataclasses.replace(new_item, valid_from=new_valid_from)

            # 旧条目原本已有 valid_to 时保留，避免伪造出更长的有效区间
            close_at = old.valid_to or new_valid_from
            stored = self._materialize(conn, new_item)
            self._close(conn, old, close_at, Status.SUPERSEDED, stored.id)
            self._write_item(conn, stored, embedding)
            self._write_fts(conn, stored)
            self._audit(conn, stored.id, old_id, "SUPERSEDE", reason, actor)
            return stored

    def insert_conflicted(
        self,
        item: MemoryItem,
        *,
        reason: str,
        actor: str,
        related_ids: Sequence[str] = (),
    ) -> MemoryItem:
        """以 CONFLICTED 状态插入一条条目。

        接受 ACTIVE 条目并自行转换——调用方的意图就是"这条是冲突候选"，
        要求它先手动改成 CONFLICTED 只是多余的仪式。
        """
        import dataclasses

        conflicted = dataclasses.replace(
            item, status=Status.CONFLICTED, linked_ids=tuple(related_ids)
        )
        return self.insert(
            conflicted, reason=reason, actor=actor, allow_duplicate_active=True
        )

    def mark_conflict(
        self,
        item_id: str,
        *,
        reason: str,
        actor: str,
        related_ids: Sequence[str] = (),
    ) -> MemoryItem:
        with self._write() as conn:
            row = conn.execute("SELECT * FROM items WHERE id = ?", (item_id,)).fetchone()
            if row is None:
                raise NotFound(f"找不到条目 {item_id}")
            item = _row_to_item(row)
            self._check_transition(item, Status.CONFLICTED)
            if item.status is Status.CONFLICTED:
                return item

            conn.execute(
                "UPDATE items SET status = 'CONFLICTED', linked_ids = ? WHERE id = ?",
                (json.dumps(list(related_ids)), item_id),
            )
            conn.execute("DELETE FROM items_fts WHERE item_id = ?", (item_id,))
            self._audit(conn, item_id, None, "CONFLICT", reason, actor)
            return self.get(item_id)

    def retract(self, item_id: str, *, reason: str, actor: str) -> MemoryItem:
        with self._write() as conn:
            row = conn.execute("SELECT * FROM items WHERE id = ?", (item_id,)).fetchone()
            if row is None:
                raise NotFound(f"找不到条目 {item_id}")
            item = _row_to_item(row)
            self._check_transition(item, Status.RETRACTED)
            if item.status is Status.RETRACTED:
                return item

            conn.execute(
                "UPDATE items SET status = 'RETRACTED' WHERE id = ?", (item_id,)
            )
            conn.execute("DELETE FROM items_fts WHERE item_id = ?", (item_id,))
            self._audit(conn, item_id, None, "RETRACT", reason, actor)
            return self.get(item_id)

    def resolve_conflict(
        self,
        winner_id: str,
        loser_id: str,
        *,
        reason: str,
        actor: str,
    ) -> tuple[MemoryItem, MemoryItem]:
        with self._write() as conn:
            winner_row = conn.execute(
                "SELECT * FROM items WHERE id = ?", (winner_id,)
            ).fetchone()
            loser_row = conn.execute(
                "SELECT * FROM items WHERE id = ?", (loser_id,)
            ).fetchone()
            if winner_row is None or loser_row is None:
                raise NotFound("裁决涉及的条目不存在")

            winner = _row_to_item(winner_row)
            loser = _row_to_item(loser_row)
            self._check_transition(winner, Status.ACTIVE)
            self._check_transition(loser, Status.SUPERSEDED)

            # 败者的 valid_to 必须写入，否则区间仍延伸到无穷远，
            # active_at 会同时返回胜者与败者（审查发现的 P0）。
            # 胜者若原本是 CONFLICTED，它的 valid_from 可能与败者相同，
            # 这时不能用它作为关闭时刻（会产生零长度区间）。
            close_at = loser.valid_to or max(winner.valid_from, loser.valid_from)
            if close_at <= loser.valid_from:
                close_at = loser.valid_from + _MIN_DURATION
            self._close(conn, loser, close_at, Status.SUPERSEDED, winner.id)

            # 胜者若是 CONFLICTED，其起点可能与败者相同；把它推进到败者关闭之后，
            # 避免与仍在历史里的旧区间重叠。
            winner_valid_from = max(winner.valid_from, close_at)
            conn.execute(
                "UPDATE items SET status = 'ACTIVE', superseded_by = NULL,"
                " valid_from = ?, valid_to = NULL WHERE id = ?",
                (to_utc_text(winner_valid_from), winner_id),
            )
            self._audit(conn, winner_id, loser_id, "RESOLVE", reason, actor)
            return self.get(winner_id), self.get(loser_id)

    # ---------- 内部 ----------

    def _find_active(
        self, conn: sqlite3.Connection, item: MemoryItem
    ) -> sqlite3.Row | None:
        row: sqlite3.Row | None = conn.execute(
            "SELECT * FROM items"
            " WHERE owner = ? AND scope = ? AND subject = ? AND relation = ?"
            "   AND IFNULL(condition,'') = IFNULL(?,'') AND status = 'ACTIVE'",
            (*item.key()[:4], item.condition),
        ).fetchone()
        return row

    def _next_ordinal(self, conn: sqlite3.Connection) -> int:
        row = conn.execute("SELECT COALESCE(MAX(ordinal), 0) + 1 AS n FROM items").fetchone()
        return int(row["n"])

    def _next_version(self, conn: sqlite3.Connection, item: MemoryItem) -> int:
        row = conn.execute(
            "SELECT COALESCE(MAX(version), 0) + 1 AS n FROM items"
            " WHERE owner = ? AND scope = ? AND subject = ? AND relation = ?"
            "   AND IFNULL(condition,'') = IFNULL(?,'')",
            (*item.key()[:4], item.condition),
        ).fetchone()
        return int(row["n"])

    def _materialize(self, conn: sqlite3.Connection, item: MemoryItem) -> MemoryItem:
        """分配 id / ordinal / version 与指纹。"""
        import dataclasses

        return dataclasses.replace(
            item,
            id=item.id or uuid.uuid4().hex,
            ordinal=self._next_ordinal(conn),
            version=self._next_version(conn, item),
        )

    def _write_item(
        self,
        conn: sqlite3.Connection,
        item: MemoryItem,
        embedding: Sequence[float] | None,
    ) -> None:
        try:
            conn.execute(
                "INSERT INTO items (id, owner, scope, subject, relation, condition, value,"
                " status, valid_from, valid_to, recorded_at, authority, session_id,"
                " turn_id, speaker, fingerprint, fingerprint_key, ordinal, version,"
                " superseded_by, linked_ids, confidence, source_text)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    item.id,
                    item.owner,
                    item.scope.value,
                    item.subject,
                    item.relation,
                    item.condition,
                    item.value,
                    item.status.value,
                    to_utc_text(item.valid_from),
                    to_utc_text(item.valid_to) if item.valid_to else None,
                    to_utc_text(item.recorded_at),
                    item.authority.value,
                    item.source.session_id,
                    item.source.turn_id,
                    item.source.speaker,
                    fingerprint(item),
                    _fingerprint_key(item),
                    item.ordinal,
                    item.version,
                    item.superseded_by,
                    "[]",
                    item.confidence,
                    item.text,
                ),
            )
        except sqlite3.IntegrityError as exc:
            raise _map_integrity_error(exc) from exc

        if embedding is not None:
            if len(embedding) != self.embedding_dims():
                raise DimensionMismatch(
                    f"向量维度 {len(embedding)} 与库声明 {self.embedding_dims()} 不一致。"
                )
            import numpy as np

            conn.execute(
                "INSERT INTO vec_items (item_id, vector, dims) VALUES (?,?,?)",
                (
                    item.id,
                    np.asarray(embedding, dtype=np.float32).tobytes(),
                    len(embedding),
                ),
            )

    def _write_fts(self, conn: sqlite3.Connection, item: MemoryItem) -> None:
        # 原文必须进索引：C3 的 9 条语义错误正是"原文与存储值零重叠"，
        # 不索引原文的话，词面路径对这个差距结构性失明。
        content = f"{item.subject} {item.relation} {item.value}"
        if item.text:
            content = f"{content} {item.text}"
        conn.execute(
            "INSERT INTO items_fts (item_id, tokens) VALUES (?,?)",
            (item.id, tokenize(content)),
        )

    def _close(
        self,
        conn: sqlite3.Connection,
        item: MemoryItem,
        close_at: datetime,
        status: Status,
        successor_id: str,
    ) -> None:
        conn.execute(
            "UPDATE items SET status = ?, valid_to = ?, superseded_by = ? WHERE id = ?",
            (status.value, to_utc_text(close_at), successor_id, item.id),
        )
        conn.execute("DELETE FROM items_fts WHERE item_id = ?", (item.id,))

    def _check_transition(self, item: MemoryItem, target: Status) -> None:
        if item.status is target:
            return
        if target not in _LEGAL_TRANSITIONS[item.status]:
            raise InvalidTransition(
                f"不允许的状态迁移：{item.status.value} → {target.value}"
                f"（条目 {item.id}）。"
            )

    def _audit(
        self,
        conn: sqlite3.Connection,
        item_id: str,
        related_item_id: str | None,
        decision: str,
        reason: str,
        actor: str,
    ) -> None:
        conn.execute(
            "INSERT INTO events (item_id, related_item_id, decision, reason, actor, at)"
            " VALUES (?,?,?,?,?,?)",
            (
                item_id,
                related_item_id,
                decision,
                reason,
                actor,
                to_utc_text(datetime.now(UTC)),
            ),
        )


def _fingerprint_key(item: MemoryItem) -> str:
    """用于幂等查询的键：逻辑键 + 内容指纹。"""
    return "|".join([*item.key()[:4], item.condition or "", fingerprint(item)])


def _escape_fts(token: str) -> str:
    """把 token 包成 FTS5 的字面量，避免特殊字符被当成语法。"""
    escaped = token.replace('"', '""')
    return f'"{escaped}"'


def _map_integrity_error(exc: sqlite3.IntegrityError) -> Exception:
    """按 sqlite_errorcode 精确映射，避免把 CHECK / NOT NULL 误报成唯一冲突。

    实测：unique=2067，notnull=1299，check=275。
    """
    code = getattr(exc, "sqlite_errorcode", None)
    message = str(exc)
    if code == sqlite3.SQLITE_CONSTRAINT_UNIQUE:
        if "ux_active" in message:
            return InvariantViolation(f"该键已有有效值（不变量被违反）：{message}")
        if "ux_version" in message or "ux_ordinal" in message:
            return InvariantViolation(f"版本号或写入序冲突：{message}")
        return InvariantViolation(message)
    if "overlapping valid interval" in message:
        return InvariantViolation(f"有效区间重叠：{message}")
    if code == sqlite3.SQLITE_CONSTRAINT_CHECK:
        return ValueError(f"约束校验失败：{message}")
    if code == sqlite3.SQLITE_CONSTRAINT_NOTNULL:
        return ValueError(f"必填字段为空：{message}")
    return exc


def _row_to_item(row: sqlite3.Row) -> MemoryItem:
    return MemoryItem(
        id=row["id"],
        owner=row["owner"],
        scope=Scope(row["scope"]),
        subject=row["subject"],
        relation=row["relation"],
        value=row["value"],
        condition=row["condition"],
        status=Status(row["status"]),
        valid_from=from_utc_text(row["valid_from"]),
        valid_to=from_utc_text(row["valid_to"]) if row["valid_to"] else None,
        recorded_at=from_utc_text(row["recorded_at"]),
        authority=Authority(row["authority"]),
        source=Source(
            session_id=row["session_id"],
            turn_id=row["turn_id"],
            speaker=row["speaker"],
        ),
        version=row["version"],
        ordinal=row["ordinal"],
        superseded_by=row["superseded_by"],
        confidence=row["confidence"],
        text=row["source_text"],
    )
