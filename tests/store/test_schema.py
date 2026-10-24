"""建表与约束的行为契约。

这里的断言直接对应 design.md 里四个实测坑：
1. NULL 绕过唯一索引 → 键列必须 NOT NULL + 非空 CHECK
2. `condition` 空值 → 唯一索引必须用 IFNULL
3. 区间重叠 → 触发器强制
4. 审计可被覆盖写入 → recursive_triggers + 第三个触发器
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from memory.store.sqlite import SqliteStore

_INSERT = (
    "INSERT INTO items (id, owner, scope, subject, relation, condition, value,"
    " status, valid_from, valid_to, recorded_at, authority, session_id,"
    " fingerprint, fingerprint_key, ordinal, version)"
    " VALUES (?, ?, 'project', ?, ?, ?, 'v', 'ACTIVE',"
    " '2026-01-01T00:00:00.000000+00:00', NULL,"
    " '2026-01-01T00:00:00.000000+00:00', 'user_direct', 'sess', ?, ?, ?, 1)"
)


def _raw(db: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db))
    conn.row_factory = sqlite3.Row
    return conn


def _try_insert(
    conn: sqlite3.Connection,
    *,
    item_id: str,
    owner: object,
    subject: object,
    relation: object,
    condition: str | None,
    ordinal: int,
) -> None:
    conn.execute(
        _INSERT,
        (item_id, owner, subject, relation, condition, f"fp-{item_id}", f"fk-{item_id}", ordinal),
    )


def test_all_tables_exist(tmp_path: Path) -> None:
    """缺表会在第一次写入时炸，且错误信息指向不到建表逻辑。"""
    store = SqliteStore(tmp_path / "m.db")
    db = store.path

    names = {
        row["name"]
        for row in _raw(db).execute("SELECT name FROM sqlite_master WHERE type='table'")
    }

    assert {"items", "items_fts", "events", "meta", "vec_items", "sqlite_sequence"} <= names


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("owner", None),
        ("subject", None),
        ("relation", None),
        ("owner", "   "),
        ("subject", ""),
        ("relation", "  "),
    ],
)
def test_key_columns_reject_null_or_blank(
    tmp_path: Path, field: str, value: str | None
) -> None:
    """NULL 在唯一索引里互不相等，会让两条"空 owner"的 ACTIVE 同时存在。"""
    store = SqliteStore(tmp_path / "m.db")
    conn = _raw(store.path)

    args: dict[str, object] = {
        "item_id": "i1",
        "owner": "o",
        "subject": "s",
        "relation": "r",
        "condition": None,
        "ordinal": 1,
    }
    args[field] = value

    with pytest.raises(sqlite3.IntegrityError):
        _try_insert(conn, **args)  # type: ignore[arg-type]


def test_two_active_with_null_condition_are_rejected(tmp_path: Path) -> None:
    """不包 IFNULL 时两条 NULL 条件的 ACTIVE 都能插入——这是最核心的一条。

    这里只断言"被拒绝"，不断言是哪个索引先触发：`ux_active` 与 `ux_version`
    都会命中，指定具体索引名等于在测试实现细节。
    """
    store = SqliteStore(tmp_path / "m.db")
    conn = _raw(store.path)

    _try_insert(
        conn,
        item_id="i1",
        owner="o",
        subject="s",
        relation="r",
        condition=None,
        ordinal=1,
    )
    conn.execute(
        "UPDATE items SET valid_from='2020-01-01T00:00:00.000000+00:00',"
        " valid_to='2020-06-01T00:00:00.000000+00:00' WHERE id='i1'"
    )

    with pytest.raises(sqlite3.IntegrityError):
        _try_insert(
            conn,
            item_id="i2",
            owner="o",
            subject="s",
            relation="r",
            condition=None,
            ordinal=2,
        )


def test_null_condition_would_bypass_index_without_ifnull(tmp_path: Path) -> None:
    """反证 IFNULL 的必要性：同一份数据，去掉 IFNULL 后两条都能插入。

    这条测试直接复现 design.md D1 的实测结论，防止有人"简化"掉 IFNULL。
    """
    db = tmp_path / "plain.db"
    conn = sqlite3.connect(str(db))
    conn.executescript(
        """
        CREATE TABLE plain (
            owner TEXT NOT NULL, condition TEXT, status TEXT NOT NULL
        );
        CREATE UNIQUE INDEX ux_plain ON plain(owner, condition) WHERE status='ACTIVE';
        """
    )

    conn.execute("INSERT INTO plain VALUES ('o', NULL, 'ACTIVE')")
    conn.execute("INSERT INTO plain VALUES ('o', NULL, 'ACTIVE')")

    assert conn.execute("SELECT COUNT(*) FROM plain").fetchone()[0] == 2


def test_unique_index_allows_different_conditions(tmp_path: Path) -> None:
    """条件分支必须能与无条件版本共存，否则条件冲突无法表达。"""
    store = SqliteStore(tmp_path / "m.db")
    conn = _raw(store.path)

    for index, condition in enumerate((None, "morning"), start=1):
        _try_insert(
            conn,
            item_id=f"i{index}",
            owner="o",
            subject="s",
            relation="r",
            condition=condition,
            ordinal=index,
        )

    assert conn.execute("SELECT COUNT(*) FROM items").fetchone()[0] == 2


def test_recursive_triggers_is_on(tmp_path: Path) -> None:
    """不开这个 pragma，INSERT OR REPLACE 会绕过 BEFORE DELETE 触发器。"""
    store = SqliteStore(tmp_path / "m.db")

    assert store.recursive_triggers_enabled() is True


def test_meta_records_embedding_dims(tmp_path: Path) -> None:
    store = SqliteStore(tmp_path / "m.db", embedding_dims=1024)

    assert store.embedding_dims() == 1024


def test_meta_rejects_mismatched_dims_on_reopen(tmp_path: Path) -> None:
    """已存在的库声明 1024 维，再以 768 维打开会导致向量不可比。"""
    db = tmp_path / "m.db"
    SqliteStore(db, embedding_dims=1024).close()

    with pytest.raises(ValueError, match="维度"):
        SqliteStore(db, embedding_dims=768)


def test_events_table_requires_reason_and_actor(tmp_path: Path) -> None:
    """没有原因的审计记录无法追责，所以数据库层面也要挡。"""
    store = SqliteStore(tmp_path / "m.db")
    conn = _raw(store.path)

    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO events (item_id, decision, reason, actor, at)"
            " VALUES ('i1','ADD','   ','someone','2026-01-01T00:00:00.000000+00:00')"
        )


def test_events_rejects_unknown_decision(tmp_path: Path) -> None:
    """自由字符串会让按决策聚合的报表悄悄漏数据。"""
    store = SqliteStore(tmp_path / "m.db")
    conn = _raw(store.path)

    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO events (item_id, decision, reason, actor, at)"
            " VALUES ('i1','SOMETHING','why','me','2026-01-01T00:00:00.000000+00:00')"
        )


def test_scope_check_constraint(tmp_path: Path) -> None:
    store = SqliteStore(tmp_path / "m.db")
    conn = _raw(store.path)

    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO items (id, owner, scope, subject, relation, condition, value,"
            " status, valid_from, recorded_at, authority, session_id, fingerprint,"
            " fingerprint_key, ordinal, version)"
            " VALUES ('i1','o','galaxy','s','r',NULL,'v','ACTIVE',"
            " '2026-01-01T00:00:00.000000+00:00','2026-01-01T00:00:00.000000+00:00',"
            " 'user_direct','sess','fp','fk',1,1)"
        )


def test_valid_to_must_be_after_valid_from_at_db_level(tmp_path: Path) -> None:
    """即使应用层漏了校验，数据库也要挡住零长度区间。"""
    store = SqliteStore(tmp_path / "m.db")
    conn = _raw(store.path)

    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO items (id, owner, scope, subject, relation, condition, value,"
            " status, valid_from, valid_to, recorded_at, authority, session_id,"
            " fingerprint, fingerprint_key, ordinal, version)"
            " VALUES ('i1','o','project','s','r',NULL,'v','ACTIVE',"
            " '2026-01-01T00:00:00.000000+00:00','2026-01-01T00:00:00.000000+00:00',"
            " '2026-01-01T00:00:00.000000+00:00','user_direct','sess','fp','fk',1,1)"
        )

