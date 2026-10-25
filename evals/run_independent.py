"""独立场景集的评测入口。

    uv run python -m evals.run_independent
    uv run python -m evals.run_independent --no-llm
    uv run python -m evals.run_independent --with-condition   # 只用条件已给出的子集

与 `run_conflict` 分开的原因：这批数据**不用于调参**，只用于报告泛化能力。
单独入口能让"held-out"这件事在代码层面也清晰可见。
"""

from __future__ import annotations

import argparse
import json
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path

from evals.datasets.independent_set import (
    INDEPENDENT_FILE,
    IndependentCase,
    IndependentSet,
    load_independent_set,
)
from evals.metrics.classification import confusion_matrix, macro_f1
from memory.config import PROJECT_ROOT, Settings
from memory.llm.cache import ResponseCache
from memory.llm.client import LLMClient
from memory.resolver.resolver import ConflictResolver, ResolverConfig
from memory.store.models import MemoryItem, Scope, Source, Status
from memory.store.sqlite import SqliteStore

DEFAULT_DIR = PROJECT_ROOT / "data" / "conflict-set"
DEFAULT_OUT = PROJECT_ROOT / "results"
BASE_TIME = datetime(2026, 1, 1, tzinfo=UTC)


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="evals.run_independent",
        description="在第三方独立场景集上评估（held-out，不用于调参）。",
    )
    parser.add_argument("--no-llm", action="store_true", help="禁用模型，只用规则")
    parser.add_argument("--dataset", type=Path, default=None)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument(
        "--with-condition",
        action="store_true",
        help="只用显式给出了 condition 的场景",
    )
    return parser.parse_args(argv)


def _seed(store: SqliteStore, case: IndependentCase) -> None:
    if case.existing_value is None:
        return
    store.insert(
        MemoryItem(
            owner="default",
            scope=Scope.PROJECT,
            subject=case.subject,
            relation=case.relation,
            value=case.existing_value,
            condition=case.existing_condition,
            status=Status.ACTIVE,
            valid_from=BASE_TIME,
            valid_to=None,
            recorded_at=BASE_TIME,
            authority=case.existing_authority,
            source=Source(session_id="seed"),
        ),
        reason="seeded",
        actor="harness",
    )


def run_case(resolver: ConflictResolver, store: SqliteStore, case: IndependentCase) -> str:
    _seed(store, case)
    decision = resolver.decide(
        subject=case.subject,
        relation=case.relation,
        value=case.candidate_value,
        text=case.text,
        condition=case.condition,
        authority=case.authority,
        at=BASE_TIME + timedelta(days=1),
    )
    return decision.kind.value


def evaluate(
    dataset: IndependentSet,
    *,
    allow_llm: bool,
    llm: object | None = None,
) -> dict[str, object]:
    gold: list[str] = []
    pred: list[str] = []
    per_case: list[dict[str, object]] = []

    for case in dataset.cases:
        with tempfile.TemporaryDirectory() as directory:
            store = SqliteStore(Path(directory) / "eval.db")
            try:
                resolver = ConflictResolver(
                    store=store,
                    config=ResolverConfig(allow_llm=allow_llm, owner="default"),
                    llm=llm,
                )
                predicted = run_case(resolver, store, case)
            finally:
                store.close()

        gold.append(case.expected.value)
        pred.append(predicted)
        per_case.append(
            {
                "id": case.id,
                "expected": case.expected.value,
                "predicted": predicted,
                "correct": predicted == case.expected.value,
                "confidence": case.confidence,
                "rationale": case.rationale,
                "text": case.text,
                "candidate": case.candidate_value,
                "existing": case.existing_value,
                "authority": case.authority.value,
                "existing_authority": case.existing_authority.value,
                "condition": case.condition,
            }
        )

    report = macro_f1(gold, pred)
    accuracy = sum(1 for g, p in zip(gold, pred, strict=True) if g == p) / len(gold)

    return {
        "n": len(gold),
        "accuracy": accuracy,
        "macro_f1": report.value,
        "support": {kind.value: count for kind, count in report.support.items()},
        "low_support_classes": [kind.value for kind in report.low_support_classes],
        "confusion_matrix": confusion_matrix(gold, pred),
        "per_case": per_case,
        "llm_enabled": allow_llm,
    }


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    path = args.dataset or (DEFAULT_DIR / INDEPENDENT_FILE)
    dataset = load_independent_set(path)

    if args.with_condition:
        dataset = dataset.with_condition_extracted()

    llm: object | None = None
    if not args.no_llm:
        settings = Settings.load()
        settings.cache_dir.mkdir(parents=True, exist_ok=True)
        llm = LLMClient(
            settings=settings,
            response_cache=ResponseCache(settings.cache_dir / "responses.db"),
            max_retries=0,
        )

    result = evaluate(dataset, allow_llm=not args.no_llm, llm=llm)
    result["subset"] = "with-condition" if args.with_condition else "all"

    args.out.mkdir(parents=True, exist_ok=True)
    suffix = "no-llm" if args.no_llm else "full"
    sub = "-cond" if args.with_condition else ""
    out_path = args.out / f"independent-{suffix}{sub}.json"
    out_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")

    wrong = [c for c in result["per_case"] if not c["correct"]]
    print(
        f"n={result['n']} accuracy={result['accuracy']:.4f} "
        f"macro_f1={result['macro_f1']:.4f} wrong={len(wrong)} -> {out_path}"
    )
    for case in wrong:
        print(
            f"  {case['id']}: expected={case['expected']:<10} "
            f"predicted={case['predicted']:<10} ({case['confidence']})"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
