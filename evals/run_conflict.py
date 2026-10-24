"""场景集评测入口。

    uv run python -m evals.run_conflict --split test
    uv run python -m evals.run_conflict --split test --no-llm

关键约束：**proposed 的标签不能作为验收依据**。
入口会在标签未确认时打印醒目警告，并在结果 JSON 里记录 `label_status` 口径，
避免"用机器标签证明自己正确"的循环论证。
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

from evals.datasets.conflict_set import ConflictCase, ConflictSet, load_conflict_set
from evals.metrics.classification import confusion_matrix, macro_f1
from memory.config import PROJECT_ROOT, Settings
from memory.llm.cache import ResponseCache
from memory.llm.client import LLMClient
from memory.resolver.resolver import ConflictResolver, ResolverConfig
from memory.store.models import Authority, MemoryItem, Scope, Source, Status
from memory.store.sqlite import SqliteStore

DEFAULT_DIR = PROJECT_ROOT / "data" / "conflict-set"
DEFAULT_OUT = PROJECT_ROOT / "results"
BASE_TIME = datetime(2026, 1, 1, tzinfo=UTC)


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="evals.run_conflict",
        description="在冲突场景集上评估判定质量。",
    )
    parser.add_argument("--split", default="test", choices=["dev", "test"])
    parser.add_argument("--no-llm", action="store_true", help="禁用模型，只用规则")
    parser.add_argument("--dataset", type=Path, default=None)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument(
        "--allow-proposed",
        action="store_true",
        help="允许在未确认标签上跑（结果仅供参考，不能作为验收依据）",
    )
    return parser.parse_args(argv)


def _seed_existing(store: SqliteStore, case: ConflictCase) -> str | None:
    """把场景里的既有事实写进库，返回其 id。"""
    if case.existing_value is None:
        return None
    item = MemoryItem(
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
        authority=Authority.USER_DIRECT,
        source=Source(session_id="seed"),
    )
    stored = store.insert(item, reason="seeded from case", actor="harness")
    return stored.id


def run_case(resolver: ConflictResolver, store: SqliteStore, case: ConflictCase) -> str:
    """跑一条场景，返回判定类别名。"""
    _seed_existing(store, case)
    decision = resolver.decide(
        subject=case.subject,
        relation=case.relation,
        value=case.candidate_value,
        text=case.text,
        condition=case.condition,
        authority=Authority(case.authority) if case.authority else Authority.USER_DIRECT,
        at=BASE_TIME + timedelta(days=1),
    )
    resolver.apply(
        decision,
        value=case.candidate_value,
        text=case.text,
        reason=f"case {case.id}",
        actor="harness",
        condition=case.condition,
        authority=Authority(case.authority) if case.authority else Authority.USER_DIRECT,
        valid_from=BASE_TIME + timedelta(days=2),
    )
    return decision.kind.value


def evaluate(
    dataset: ConflictSet,
    *,
    allow_llm: bool,
    settings: Settings | None = None,
    llm: object | None = None,
) -> dict[str, object]:
    """逐条场景独立评估。

    每条场景使用**独立的临时库**：场景之间共享库会互相污染
    （例如三条 ADD 场景都用 `project:new`，第二条会撞上第一条的 ACTIVE）。
    隔离是评估的前提，不是可选的优化。
    """
    gold: list[str] = []
    pred: list[str] = []
    per_case: list[dict[str, object]] = []
    distribution: dict[str, int] = {}
    normalized_false = 0

    import tempfile

    for case in dataset.cases:
        with tempfile.TemporaryDirectory() as directory:
            store = SqliteStore(Path(directory) / "eval.db")
            try:
                config = ResolverConfig(allow_llm=allow_llm, owner="default")
                resolver = ConflictResolver(store=store, config=config, llm=llm)
                predicted = run_case(resolver, store, case)
                normalized = resolver.last_normalized  # type: ignore[attr-defined]
            finally:
                store.close()

        gold.append(case.expected.value)
        pred.append(predicted)
        distribution[predicted] = distribution.get(predicted, 0) + 1
        if not normalized:
            normalized_false += 1
        per_case.append(
            {
                "id": case.id,
                "expected": case.expected.value,
                "predicted": predicted,
                "correct": predicted == case.expected.value,
                "label_status": case.label_status,
                "normalized": normalized,
            }
        )

    report = macro_f1(gold, pred)
    matrix = confusion_matrix(gold, pred)
    accuracy = sum(1 for g, p in zip(gold, pred, strict=True) if g == p) / len(gold)

    return {
        "split": None,
        "n": len(gold),
        "accuracy": accuracy,
        "macro_f1": report.value,
        "classes_evaluated": report.classes_evaluated,
        "support": {kind.value: count for kind, count in report.support.items()},
        "absent_classes": [kind.value for kind in report.absent_classes],
        "low_support_classes": [kind.value for kind in report.low_support_classes],
        "confusion_matrix": matrix,
        "per_case": per_case,
        "predicted_distribution": distribution,
        "normalized_false": normalized_false,
    }


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    dataset_path = args.dataset or (DEFAULT_DIR / f"{args.split}.jsonl")
    dataset = load_conflict_set(dataset_path)

    confirmed = dataset.confirmed()
    if len(confirmed) == 0 and not args.allow_proposed:
        print(
            "标签尚未人工确认，不能作为验收依据。\n"
            f"  共 {len(dataset)} 条，全部为 proposed。\n"
            "  确认方式：uv run python -m evals.tools.label --split "
            f"{args.split} confirm --id <id> --label <LABEL> --labeler <name>\n"
            "  若只想看参考结果，加 --allow-proposed。",
            file=sys.stderr,
        )
        return 2

    target = dataset if args.allow_proposed else confirmed
    if len(confirmed) == 0:
        print(
            "警告：正在用未确认的机器标签评估，结果不能作为验收依据。",
            file=sys.stderr,
        )

    llm: object | None = None
    if not args.no_llm:
        settings = Settings.load()
        settings.cache_dir.mkdir(parents=True, exist_ok=True)
        llm = LLMClient(
            settings=settings,
            response_cache=ResponseCache(settings.cache_dir / "responses.db"),
            max_retries=0,
        )

    result = evaluate(target, allow_llm=not args.no_llm, llm=llm)
    result["split"] = args.split
    result["label_status"] = "proposed" if args.allow_proposed and not confirmed else "confirmed"
    result["llm_enabled"] = not args.no_llm
    result["dataset"] = dataset_path.name

    args.out.mkdir(parents=True, exist_ok=True)
    suffix = "no-llm" if args.no_llm else "full"
    out_path = args.out / f"conflict-{args.split}-{suffix}.json"
    out_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")

    print(
        f"split={args.split} n={len(target)} accuracy={result['accuracy']:.4f} "
        f"macro_f1={result['macro_f1']:.4f} -> {out_path}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
