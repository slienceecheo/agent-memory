"""评测入口。

    uv run python -m evals.run --help
    uv run python -m evals.run --baseline naive-rag --limit 5
    uv run python -m evals.run --all
    uv run python -m evals.run --check-cache
"""

from __future__ import annotations

import argparse
import sys
import uuid
from pathlib import Path

from evals.baselines import BASELINES, build_baseline
from evals.datasets.factconsolidation import FactConsolidationAdapter, iter_questions
from evals.types import BaselineResult, SampleResult
from memory.config import PROJECT_ROOT, Settings
from memory.embedding.cache import EmbeddingCache
from memory.llm.cache import ResponseCache
from memory.llm.client import LLMClient
from memory.tracing.jsonl import JsonlTracer

DEFAULT_DATASET = PROJECT_ROOT / "data" / "raw" / "Conflict_Resolution.parquet"
DEFAULT_RESULTS = PROJECT_ROOT / "results"


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="evals.run",
        description="跑 FactConsolidation 基线并产出可复现的结果 JSON。",
    )
    parser.add_argument("--baseline", choices=BASELINES, help="只跑一条基线")
    parser.add_argument("--all", action="store_true", help="跑全部三条基线")
    parser.add_argument("--bench", default="factconsolidation")
    parser.add_argument("--length", default="6k", help="6k / 32k / 64k / 262k")
    parser.add_argument("--hop", default="sh", help="sh / mh")
    parser.add_argument("--limit", type=int, default=None, help="只跑前 N 条问题")
    parser.add_argument("--top-k", type=int, default=5, help="naive-rag 的召回条数")
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--out", type=Path, default=DEFAULT_RESULTS)
    parser.add_argument(
        "--check-cache", action="store_true", help="校验缓存完整性后退出"
    )
    return parser.parse_args(argv)


def _check_cache(settings: Settings, dataset: Path, limit: int | None) -> int:
    """校验两种缓存：embedding 与 LLM 响应。

    退出码语义：全部完整=0，任一缺失/损坏=非零。
    LLM 缓存是 A2（两次运行逐位一致）的前提——模型本身有随机性。
    """
    exit_code = 0

    embed_path = settings.cache_dir / "cache.db"
    if not embed_path.exists():
        print(f"[embedding] 缓存不存在：{embed_path}")
        exit_code = 1
    else:
        embed = EmbeddingCache(embed_path)
        stats = embed.stats()
        checked, corrupt = embed.verify_all()
        print(f"[embedding] 条目={stats.entries} 已校验={checked} 损坏={len(corrupt)}")
        if corrupt:
            for key in corrupt:
                print(f"  损坏：{key}", file=sys.stderr)
            exit_code = 1
        if stats.entries == 0:
            print("[embedding] 缓存为空，视为不完整。")
            exit_code = 1

    response_path = settings.cache_dir / "responses.db"
    if not response_path.exists():
        print(f"[llm] 缓存不存在：{response_path}")
        exit_code = 1
    else:
        responses = ResponseCache(response_path)
        entries, corrupt = responses.verify_all()
        print(f"[llm] 条目={entries} 已校验={entries} 损坏={len(corrupt)}")
        if corrupt:
            for key in corrupt:
                print(f"  损坏：{key}", file=sys.stderr)
            exit_code = 1
        if entries == 0:
            print("[llm] 缓存为空，视为不完整。")
            exit_code = 1

    return exit_code


def _run_one(
    *,
    baseline_name: str,
    args: argparse.Namespace,
    settings: Settings,
    dataset: Path,
) -> BaselineResult:
    adapter = FactConsolidationAdapter(dataset)
    samples = adapter.load(length=args.length, hop=args.hop)

    run_id = uuid.uuid4().hex[:12]
    event_path = args.out / f"events-{baseline_name}-{run_id}.jsonl"
    tracer = JsonlTracer(event_path, run_id=run_id)
    settings.cache_dir.mkdir(parents=True, exist_ok=True)
    llm = LLMClient(
        settings=settings,
        response_cache=ResponseCache(settings.cache_dir / "responses.db"),
    )
    baseline = build_baseline(
        baseline_name, llm=llm, tracer=tracer, top_k=args.top_k
    )

    results: list[SampleResult] = []
    pairs = list(iter_questions(samples))
    if args.limit is not None:
        pairs = pairs[: args.limit]

    for sample, question in pairs:
        gold = question.answers[0] if question.answers else ""
        result = baseline.run(
            question=question.question,
            facts=[fact.text for fact in sample.facts],
            sample_id=question.id,
            gold=gold,
        )
        results.append(result)

    return BaselineResult(
        baseline=baseline_name,
        benchmark=args.bench,
        subset=samples[0].source,
        samples=results,
    )


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    settings = Settings.load()

    if args.check_cache:
        return _check_cache(settings, args.dataset, args.limit)

    if not args.all and not args.baseline:
        print("请指定 --baseline <名字> 或 --all", file=sys.stderr)
        return 2

    if not args.dataset.exists():
        print(f"数据集缺失：{args.dataset}", file=sys.stderr)
        return 2

    names = list(BASELINES) if args.all else [args.baseline]
    args.out.mkdir(parents=True, exist_ok=True)

    for name in names:
        assert name is not None
        result = _run_one(
            baseline_name=name, args=args, settings=settings, dataset=args.dataset
        )
        out_path = args.out / f"{name}-{args.length}-{args.hop}.json"
        out_path.write_text(result.model_dump_json(indent=2), encoding="utf-8")
        print(f"{name:14s} accuracy={result.accuracy:.4f} "
              f"n={len(result.answered)} errors={result.error_count} "
              f"reasoning_waste={result.reasoning_waste_ratio:.3f} -> {out_path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
