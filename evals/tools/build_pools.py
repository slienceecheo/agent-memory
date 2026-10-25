"""用真实场景集构建候选池。

每条场景的池 = 该场景的 gold + 从其他场景的 gold 中随机采样的干扰项。
干扰项来自其他场景，保证它们语义上不相关（不同 subject/relation）。

用法：
    uv run python -m evals.tools.build_pools --dry-run
    uv run python -m evals.tools.build_pools
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from memory.retrieval.pool import build_pool
from memory.store.models import Authority, MemoryItem, Scope, Source, Status

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data" / "conflict-set"
BASE_TIME = datetime(2026, 1, 1, tzinfo=UTC)


@dataclass(frozen=True, slots=True)
class PoolRecord:
    case_id: str
    query: str
    gold_id: str | None
    item_count: int
    gold_rank: int | None


def _to_item(row: dict[str, object], spec: dict[str, object], *, tag: str) -> MemoryItem:
    condition = spec.get("condition")
    return MemoryItem(
        owner="default",
        scope=Scope.PROJECT,
        subject=str(spec["subject"]),
        relation=str(spec["relation"]),
        value=str(spec["value"]),
        condition=str(condition) if condition else None,
        status=Status.ACTIVE,
        valid_from=BASE_TIME,
        valid_to=None,
        recorded_at=BASE_TIME,
        authority=Authority(str(spec.get("authority") or "user_direct")),
        source=Source(session_id=tag),
        text=str(row.get("text") or "") or None,
        id=f"{tag}:{spec['subject']}:{spec['relation']}",
    )


def load_rows(path: Path) -> list[dict[str, object]]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def collect_gold_specs(rows: Iterable[dict[str, object]]) -> list[dict[str, object]]:
    """收集所有场景的 gold 定义，用于跨场景采样干扰项。"""
    specs = []
    for row in rows:
        gold = row.get("gold")
        if gold:
            specs.append(gold)
    return specs


def build_all(
    rows: list[dict[str, object]],
    *,
    distractors: int = 20,
    seed: int = 0,
    global_specs: list[dict[str, object]] | None = None,
) -> list[PoolRecord]:
    """为一批场景构建候选池。

    `global_specs` 提供跨文件的干扰项池——单文件内的 gold 数量通常不足，
    会让池小于 K 而无法评估。
    """
    local_specs = collect_gold_specs(rows)
    specs = list(global_specs) if global_specs is not None else local_specs
    records: list[PoolRecord] = []

    for row in rows:
        gold_spec = row.get("gold")
        if not gold_spec:
            records.append(
                PoolRecord(
                    case_id=str(row["id"]),
                    query=str(row["query"]),
                    gold_id=None,
                    item_count=0,
                    gold_rank=None,
                )
            )
            continue

        gold = _to_item(row, gold_spec, tag=f"gold-{row['id']}")
        gold_key = (gold_spec.get("subject"), gold_spec.get("relation"), gold_spec.get("condition"))
        others = [
            _to_item({"text": ""}, spec, tag=f"dist-{row['id']}-{index}")
            for index, spec in enumerate(specs)
            if (spec.get("subject"), spec.get("relation"), spec.get("condition")) != gold_key
        ]
        pool = build_pool(gold, others[:distractors], seed=seed)
        records.append(
            PoolRecord(
                case_id=str(row["id"]),
                query=str(row["query"]),
                gold_id=gold.id,
                item_count=len(pool.items),
                gold_rank=pool.gold_rank,
            )
        )

    return records


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="evals.tools.build_pools")
    parser.add_argument("--dir", type=Path, default=DATA)
    parser.add_argument("--distractors", type=int, default=20)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    # 干扰项从**全部三个文件**的 gold 中采样：单文件内可用干扰项不足，
    # 会导致池小于 K 而无法评估。
    all_specs: list[dict[str, object]] = []
    loaded: dict[str, list[dict[str, object]]] = {}
    for name in ("dev.jsonl", "test.jsonl", "independent.jsonl"):
        path = args.dir / name
        if not path.exists():
            print(f"跳过（不存在）：{name}", file=sys.stderr)
            continue
        rows = load_rows(path)
        loaded[name] = rows
        all_specs.extend(collect_gold_specs(rows))

    print(f"全局干扰项候选：{len(all_specs)} 条")

    for name, rows in loaded.items():
        records = build_all(
            rows, distractors=args.distractors, global_specs=all_specs
        )
        with_gold = [r for r in records if r.gold_id]
        ranks = [r.gold_rank for r in with_gold if r.gold_rank]
        sizes = {r.item_count for r in with_gold}
        print(
            f"{name:<20} cases={len(records):<3} "
            f"with_gold={len(with_gold):<3} "
            f"pool_sizes={sorted(sizes)} "
            f"gold_rank={min(ranks) if ranks else '-'}..{max(ranks) if ranks else '-'}"
        )
    if args.dry_run:
        print("（dry-run）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
