"""为场景集补检索因变量：`query` 与 `gold`。

**为什么必须有这一步**：三份场景文件只有 `expected`（判定类别），
没有 query、没有 gold。没有 gold 时 SEH@K 与 SRS 根本无法定义——
这正是设计审查发现的首要缺陷。

两个字段的定义：

- `query`：取 `text`（原话语），**不拼接查找键**。
  拼接 `subject + relation` 会把答案放进查询里，词面召回接近 100%。
- `gold`：该场景的既有条目（`existing_value` / `existing_condition`）。
  非 ADD 场景必须看到它才能回答；ADD 场景没有 gold。

`gold` 为 `null` 的条目不参与召回指标，但数量必须报出来。

    uv run python -m evals.tools.annotate_retrieval --dry-run
    uv run python -m evals.tools.annotate_retrieval
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from evals.datasets.independent_set import INDEPENDENT_FILE

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data" / "conflict-set"
FILES = ("dev.jsonl", "test.jsonl", INDEPENDENT_FILE)


def gold_for(row: dict[str, object]) -> dict[str, object] | None:
    """既有条目即 gold；ADD 场景没有 gold。"""
    existing = row.get("existing_value")
    if existing in (None, ""):
        return None
    return {
        "subject": row["subject"],
        "relation": row["relation"],
        "value": existing,
        "condition": row.get("existing_condition"),
        "authority": row.get("existing_authority") or "user_direct",
    }


def annotate(path: Path, *, dry_run: bool = False) -> dict[str, object]:
    rows = [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]

    with_gold = 0
    missing_query = 0
    for row in rows:
        if not row.get("query"):
            row["query"] = row["text"]
        if row.get("gold") is None and "gold" not in row:
            row["gold"] = gold_for(row)
        if row["gold"] is not None:
            with_gold += 1
        if not row["query"].strip():
            missing_query += 1

    if not dry_run:
        lines = [json.dumps(row, ensure_ascii=False) for row in sorted(rows, key=lambda r: r["id"])]
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    return {
        "file": path.name,
        "total": len(rows),
        "with_gold": with_gold,
        "without_gold": len(rows) - with_gold,
        "missing_query": missing_query,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="evals.tools.annotate_retrieval")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--dir", type=Path, default=DATA)
    args = parser.parse_args(argv)

    total_cases = 0
    total_gold = 0
    for name in FILES:
        path = args.dir / name
        if not path.exists():
            print(f"跳过（不存在）：{name}", file=sys.stderr)
            continue
        stats = annotate(path, dry_run=args.dry_run)
        total_cases += stats["total"]  # type: ignore[operator]
        total_gold += stats["with_gold"]  # type: ignore[operator]
        print(
            f"{stats['file']:<20} total={stats['total']:<3} "
            f"gold={stats['with_gold']:<3} no_gold={stats['without_gold']:<3} "
            f"empty_query={stats['missing_query']}"
        )

    if total_cases:
        print(
            f"\n合计 {total_cases} 条，有 gold {total_gold} 条"
            f"（{total_gold / total_cases:.1%}）"
        )
    if args.dry_run:
        print("（dry-run，未写入）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
