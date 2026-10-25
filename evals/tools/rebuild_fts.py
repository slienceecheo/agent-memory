"""重建全文索引。

`items_fts` 是 FTS5 虚拟表，SQLite 不支持对它加列。要让它包含原文，
必须 DROP 后重建并从 `items` 重新灌入。

安全性：
- 建表前先校验 `items` 行数，重建后再次校验，不一致即报错
- 用事务包裹，失败则整体回滚
- **只重建索引，不动 items**——原文是元数据，索引是可再生派生物

    uv run python -m evals.tools.rebuild_fts data/memory.db
    uv run python -m evals.tools.rebuild_fts data/memory.db --dry-run
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

from memory.store.sqlite import tokenize


def _item_count(conn: sqlite3.Connection) -> int:
    return int(conn.execute("SELECT COUNT(*) FROM items").fetchone()[0])


def _fts_count(conn: sqlite3.Connection) -> int:
    return int(conn.execute("SELECT COUNT(*) FROM items_fts").fetchone()[0])


def rebuild(path: Path, *, dry_run: bool = False) -> dict[str, int]:
    """重建 FTS 索引，返回统计信息。"""
    if not path.exists():
        raise FileNotFoundError(f"找不到数据库：{path}")

    conn = sqlite3.connect(str(path), isolation_level=None)
    try:
        rows_before = _item_count(conn)
        fts_before = _fts_count(conn)

        if dry_run:
            return {
                "items": rows_before,
                "fts_before": fts_before,
                "fts_after": -1,
                "with_text": int(
                    conn.execute(
                        "SELECT COUNT(*) FROM items WHERE source_text IS NOT NULL"
                    ).fetchone()[0]
                ),
            }

        conn.execute("BEGIN IMMEDIATE")
        try:
            conn.execute("DROP TABLE IF EXISTS items_fts")
            # 不用 executescript：它会隐式 COMMIT，破坏外层事务
            conn.execute(
                "CREATE VIRTUAL TABLE items_fts"
                " USING fts5(item_id UNINDEXED, tokens)"
            )
            rows = conn.execute(
                "SELECT id, subject, relation, value, source_text FROM items"
            ).fetchall()
            conn.executemany(
                "INSERT INTO items_fts (item_id, tokens) VALUES (?,?)",
                [
                    (item_id, tokenize(_content(subject, relation, value, text)))
                    for item_id, subject, relation, value, text in rows
                ],
            )
        except Exception:
            conn.execute("ROLLBACK")
            raise
        else:
            conn.execute("COMMIT")

        rows_after = _item_count(conn)
        fts_after = _fts_count(conn)
        if rows_after != rows_before:
            raise RuntimeError(
                f"items 行数在重建过程中变化：{rows_before} → {rows_after}"
            )
        if fts_after != rows_after:
            raise RuntimeError(
                f"索引条数与条目数不一致：{fts_after} vs {rows_after}"
            )

        return {
            "items": rows_after,
            "fts_before": fts_before,
            "fts_after": fts_after,
            "with_text": int(
                conn.execute(
                    "SELECT COUNT(*) FROM items WHERE source_text IS NOT NULL"
                ).fetchone()[0]
            ),
        }
    finally:
        conn.close()


def _content(subject: str, relation: str, value: str, text: str | None) -> str:
    base = f"{subject} {relation} {value}"
    return f"{base} {text}" if text else base


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="evals.tools.rebuild_fts")
    parser.add_argument("database", type=Path)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    try:
        stats = rebuild(args.database, dry_run=args.dry_run)
    except (FileNotFoundError, RuntimeError) as exc:
        print(str(exc), file=sys.stderr)
        return 1

    print(f"items={stats['items']} fts_before={stats['fts_before']} "
          f"fts_after={stats['fts_after']} with_text={stats['with_text']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
