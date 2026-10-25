"""检索评测入口。

    uv run python -m evals.run_retrieval --split independent
    uv run python -m evals.run_retrieval --split independent --no-dedup
    uv run python -m evals.run_retrieval --split independent --weights base_heavy

三个设计约束：

1. **每条场景独立建库**：池里只有该场景的候选，跨场景不污染
2. **保留未截断的融合排名**：否则"排序过低"与"重排丢弃"无法区分
3. **运行次数可验证**：结果 JSON 记录 `run_count`，使"test 只跑一次"可检查
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path

from evals.metrics.retrieval import (
    Attribution,
    attribute_failure,
    attribution_breakdown,
    seh_at_k,
    srs,
)
from memory.config import PROJECT_ROOT, Settings
from memory.llm.cache import ResponseCache
from memory.llm.client import LLMClient
from memory.retrieval.condition import condition_match
from memory.retrieval.dedup import dedup
from memory.retrieval.equivalence import EquivalenceJudge
from memory.retrieval.fusion import rrf
from memory.retrieval.lexical import recall_by_lexical
from memory.retrieval.pool import build_pool
from memory.retrieval.pool_modes import PoolMode
from memory.retrieval.rerank import (
    PREREGISTERED_WEIGHTS,
    FeatureScores,
    Ranked,
    authority_score,
    rerank,
    rrf_norm,
    status_score,
)
from memory.store.models import Authority, MemoryItem, Scope, Source, Status
from memory.store.sqlite import SqliteStore

ROOT = PROJECT_ROOT
DATA = ROOT / "data" / "conflict-set"
OUT_DIR = ROOT / "results"
BASE_TIME = datetime(2026, 1, 1, tzinfo=UTC)
DEFAULT_K = 5


def _rows(path: Path) -> list[dict[str, object]]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _item(
    row: dict[str, object], spec: dict[str, object], *, tag: str, text: str | None
) -> MemoryItem:
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
        text=text,
        id=f"{tag}",
    )


def select_pool_distractors(
    spec: dict[str, object],
    all_specs: list[dict[str, object]],
    *,
    mode: PoolMode,
    limit: int,
) -> list[dict[str, object]]:
    """按难度模式选干扰项的 spec（在构造成 MemoryItem 之前筛选）。

    **必须在 spec 层面筛**，因为 `PoolMode.SAME_RELATION` 需要看 relation，
    而 `MemoryItem` 的构造需要 text 等字段的额外处理。
    """
    gold_key = (spec.get("subject"), spec.get("relation"), spec.get("condition"))
    others = [
        candidate
        for candidate in all_specs
        if (candidate.get("subject"), candidate.get("relation"), candidate.get("condition"))
        != gold_key
    ]

    if mode is PoolMode.UNRELATED:
        return others[:limit]

    same_relation = [
        candidate for candidate in others if candidate.get("relation") == spec.get("relation")
    ]
    if mode is PoolMode.SAME_RELATION:
        return same_relation[:limit]

    gold_chars = set(str(spec.get("value") or ""))
    return [
        candidate
        for candidate in same_relation
        if gold_chars & set(str(candidate.get("value") or ""))
    ][:limit]


def evaluate_case(
    row: dict[str, object],    *,
    all_specs: list[dict[str, object]],
    weights_name: str,
    enable_dedup: bool,
    judge: EquivalenceJudge | None,
    k: int,
    pool_mode: PoolMode = PoolMode.UNRELATED,
) -> dict[str, object]:
    """评估单条场景。返回该条的排名、指标与归因。"""
    gold_spec = row.get("gold")
    query = str(row["query"])
    weights = PREREGISTERED_WEIGHTS[weights_name]

    if not gold_spec:
        return {
            "case_id": row["id"],
            "has_gold": False,
            "pool_size": 0,
            "rank_after_fusion": None,
            "rank_after_rerank": None,
            "seh": None,
            "srs": None,
            "attribution": None,
        }

    selected = select_pool_distractors(gold_spec, all_specs, mode=pool_mode, limit=20)

    # 池太小就无法评估：排名会退化成"只有 gold 一条"，SEH 恒为 1。
    # 这是数据的真实约束（independent 集 28/29 个 relation 只出现 1 次），
    # 必须显式跳过并计数，而不是给出一个虚高的分数。
    if len(selected) + 1 <= k:
        return {
            "case_id": row["id"],
            "has_gold": True,
            "skipped": True,
            "skip_reason": f"池只有 {len(selected) + 1} 条，不足 K={k}",
            "pool_size": len(selected) + 1,
            "rank_after_fusion": None,
            "rank_after_rerank": None,
            "seh": None,
            "srs": None,
            "attribution": None,
        }

    distractors = [
        _item({"text": ""}, spec, tag=f"d-{row['id']}-{i}", text=None)
        for i, spec in enumerate(selected)
    ]

    with tempfile.TemporaryDirectory() as directory:
        store = SqliteStore(Path(directory) / "eval.db")
        try:
            gold = _item(row, gold_spec, tag=f"gold-{row['id']}", text=str(row.get("text") or ""))
            pool = build_pool(gold, distractors, seed=0)

            id_map: dict[str, MemoryItem] = {}
            for entry in pool.items:
                import dataclasses

                stored = store.insert(
                    dataclasses.replace(entry, id=""), reason="pool", actor="harness"
                )
                id_map[entry.id] = stored

            gold_id = id_map[pool.gold_id].id
            lexical = [i.id for i in recall_by_lexical(store, query, limit=len(pool.items))]
            fused = rrf({"lexical": lexical}, k=60)
            fused_order = [entry.item_id for entry in fused]
            rank_fusion = (
                fused_order.index(gold_id) + 1 if gold_id in fused_order else None
            )

            score_by_id = {entry.item_id: entry.score for entry in fused}
            max_score = max(score_by_id.values()) if score_by_id else 0.0
            query_condition = row.get("condition")

            candidates = []
            for item_id, score in score_by_id.items():
                item = store.get(item_id)
                candidates.append(
                    _RerankCandidate(
                        item_id=item_id,
                        features=FeatureScores(
                            base=rrf_norm(score, max_score=max_score),
                            condition=condition_match(
                                str(query_condition) if query_condition else None,
                                item.condition,
                            ),
                            authority=authority_score(item.authority),
                            status=status_score(item.status),
                        ),
                    )
                )

            ranked: list[Ranked] = rerank(candidates, weights=weights)
        finally:
            store.close()

    order = [item.item_id for item in ranked]

    if enable_dedup and judge is not None:
        texts = [(item_id, item_id, 1.0) for item_id in order]
        kept, _ = dedup(texts, judge=judge, top_k=k)
        order = [entry[0] for entry in kept]

    rank_rerank = order.index(gold_id) + 1 if gold_id in order else None

    attribution = attribute_failure(
        gold_in_pool=True,
        rank_after_fusion=rank_fusion,
        rank_after_rerank=rank_rerank,
        k=k,
    )

    return {
        "case_id": row["id"],
        "has_gold": True,
        "pool_size": len(pool.items),
        "rank_after_fusion": rank_fusion,
        "rank_after_rerank": rank_rerank,
        "seh": seh_at_k(rank=rank_rerank, k=k),
        "srs": srs(rank=rank_rerank),
        "attribution": attribution.value if attribution else None,
    }


class _RerankCandidate:
    def __init__(self, *, item_id: str, features: FeatureScores) -> None:
        self.item_id = item_id
        self.features = features


def evaluate(
    rows: list[dict[str, object]],
    *,
    all_specs: list[dict[str, object]],
    weights_name: str,
    enable_dedup: bool,
    judge: EquivalenceJudge | None,
    k: int = DEFAULT_K,
    pool_mode: PoolMode = PoolMode.UNRELATED,
) -> dict[str, object]:
    per_case = [
        evaluate_case(
            row,
            all_specs=all_specs,
            weights_name=weights_name,
            enable_dedup=enable_dedup,
            judge=judge,
            k=k,
            pool_mode=pool_mode,
        )
        for row in rows
    ]

    scored = [item for item in per_case if item["has_gold"] and not item.get("skipped", False)]
    skipped = [item for item in per_case if item.get("skipped", False)]
    seh_values = [bool(item["seh"]) for item in scored]
    srs_values = [float(item["srs"]) for item in scored]

    return {
        "weights": weights_name,
        "pool_mode": pool_mode.value,
        "dedup": enable_dedup,
        "k": k,
        "cases": len(per_case),
        "with_gold": len(scored),
        "without_gold": len(per_case) - len([i for i in per_case if i["has_gold"]]),
        "skipped_small_pool": len(skipped),
        "seh_at_k": sum(seh_values) / len(seh_values) if seh_values else 0.0,
        "srs": sum(srs_values) / len(srs_values) if srs_values else 0.0,
        "attribution": attribution_breakdown(
            [
                None if item["attribution"] is None else Attribution(str(item["attribution"]))
                for item in scored
            ]
        ),
        "per_case": per_case,
    }


def _bump_run_count(out: Path) -> int:
    """记录同一配置被跑了几次，使"test 只跑一次"可验证。"""
    counter = OUT_DIR / "retrieval-run-count.json"
    counts: dict[str, int] = {}
    if counter.exists():
        counts = json.loads(counter.read_text(encoding="utf-8"))
    key = out.name
    counts[key] = counts.get(key, 0) + 1
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    counter.write_text(json.dumps(counts, ensure_ascii=False, indent=2), encoding="utf-8")
    return counts[key]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="evals.run_retrieval")
    parser.add_argument("--split", default="independent", choices=["dev", "test", "independent"])
    parser.add_argument("--weights", default="uniform", choices=sorted(PREREGISTERED_WEIGHTS))
    parser.add_argument("--no-dedup", action="store_true")
    parser.add_argument("--k", type=int, default=DEFAULT_K)
    parser.add_argument(
        "--pool",
        default="unrelated",
        choices=[mode.value for mode in PoolMode],
        help="候选池难度模式",
    )
    parser.add_argument("--dataset", type=Path, default=None)
    args = parser.parse_args(argv)

    path = args.dataset or (DATA / f"{args.split}.jsonl")
    if not path.exists():
        print(f"数据集不存在：{path}", file=sys.stderr)
        return 2
    rows = _rows(path)

    all_specs: list[dict[str, object]] = []
    for name in ("dev.jsonl", "test.jsonl", "independent.jsonl"):
        other = DATA / name
        if other.exists():
            all_specs.extend(
                [row["gold"] for row in _rows(other) if row.get("gold")]  # type: ignore[misc]
            )

    judge: EquivalenceJudge | None = None
    if not args.no_dedup:
        settings = Settings.load()
        settings.cache_dir.mkdir(parents=True, exist_ok=True)
        llm = LLMClient(
            settings=settings,
            response_cache=ResponseCache(settings.cache_dir / "responses.db"),
            max_retries=0,
        )
        judge = EquivalenceJudge(llm=llm)

    result = evaluate(
        rows,
        all_specs=all_specs,
        weights_name=args.weights,
        enable_dedup=not args.no_dedup,
        judge=judge,
        k=args.k,
        pool_mode=PoolMode(args.pool),
    )
    result["split"] = args.split

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    suffix = ("-nodedup" if args.no_dedup else "") + f"-pool{args.pool}"
    out = OUT_DIR / f"retrieval-{args.split}-{args.weights}{suffix}.json"
    run_count = _bump_run_count(out)
    result["run_count"] = run_count
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")

    print(
        f"split={args.split} weights={args.weights} pool={args.pool} dedup={not args.no_dedup} "
        f"n={result['with_gold']}/{result['cases']} skipped={result['skipped_small_pool']} "
        f"SEH@{args.k}={result['seh_at_k']:.3f} SRS={result['srs']:.3f} "
        f"run#{run_count}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
