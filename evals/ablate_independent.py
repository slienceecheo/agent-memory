"""在独立场景集上量化"如果改规则会怎样"。

**为什么要有这个脚本**：独立场景集是 held-out，不能直接在上面调规则，
否则它就退化成第二个 dev 集，失去测量泛化能力的意义。

但这个数据集暴露的三类错误都有明确的修法。正确的做法是：
1. 在 held-out 上测出当前基线（43.3%）
2. 做**对照实验**：逐个启用候选改动，量化各自能带来多少提升
3. 把结果写进报告，标明"这些是未采用的候选改动"
4. 若要采用，必须在**另一个**独立来源上验证增益是否保持

这样既诚实，又给出了明确的后续方向。
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from pathlib import Path

from evals.datasets.independent_set import IndependentCase, load_independent_set
from memory.resolver.rules import (
    Candidate,
    DecisionKind,
    ExistingSnapshot,
    decide_by_rules,
)
from memory.store.models import Authority


@dataclass(frozen=True, slots=True)
class Variant:
    name: str
    description: str


VARIANTS: tuple[Variant, ...] = (
    Variant("baseline", "当前规则（七条，含 lower_authority 一律 CONFLICT）"),
    Variant(
        "authority_updates",
        "权威更低但文本含明确变更标记时，判 SUPERSEDE 而非 CONFLICT",
    ),
    Variant(
        "drop_lower_authority",
        "完全去掉 lower_authority 规则（所有新状态都取代）",
    ),
    Variant(
        "semantic_merge",
        "用模型判断'旧值是否仍成立'来决定 MERGE（需要 LLM）",
    ),
)


def _predict(
    case: IndependentCase, *, variant: str, llm: object | None = None
) -> str:
    """按指定变体给出判定。仅用于对照实验，不进入生产路径。"""
    from memory.resolver.change_marker import (
        ChangeSource,
        detect_by_rules,
    )

    marker = detect_by_rules(case.text)
    is_new_state = marker.is_new_state if marker is not None else True
    change_source = marker.source if marker is not None else ChangeSource.DISABLED

    existing = (
        None
        if case.existing_value is None
        else ExistingSnapshot(
            id="x",
            subject=case.subject,
            relation=case.relation,
            value=case.existing_value,
            condition=case.existing_condition,
            authority=case.existing_authority,
        )
    )

    if variant == "baseline":
        candidate = Candidate(
            subject=case.subject,
            relation=case.relation,
            value=case.candidate_value,
            condition=case.condition,
            authority=case.authority,
            is_new_state=is_new_state,
            change_source=change_source,
        )
        return decide_by_rules(candidate, existing=existing).kind.value

    if variant == "authority_updates":
        # 只有明确变更标记时才允许低权威取代
        effective_authority = (
            case.existing_authority
            if (case.authority < case.existing_authority and marker is not None)
            else case.authority
        )
        candidate = Candidate(
            subject=case.subject,
            relation=case.relation,
            value=case.candidate_value,
            condition=case.condition,
            authority=effective_authority,
            is_new_state=is_new_state,
            change_source=change_source,
        )
        return decide_by_rules(candidate, existing=existing).kind.value

    if variant == "drop_lower_authority":
        candidate = Candidate(
            subject=case.subject,
            relation=case.relation,
            value=case.candidate_value,
            condition=case.condition,
            authority=Authority.USER_DIRECT,
            is_new_state=is_new_state,
            change_source=change_source,
        )
        # 把 existing 也抬到同级，从而绕过 lower_authority
        if existing is not None:
            existing = ExistingSnapshot(
                id=existing.id,
                subject=existing.subject,
                relation=existing.relation,
                value=existing.value,
                condition=existing.condition,
                authority=Authority.USER_DIRECT,
            )
        return decide_by_rules(candidate, existing=existing).kind.value

    if variant == "semantic_merge":
        candidate = Candidate(
            subject=case.subject,
            relation=case.relation,
            value=case.candidate_value,
            condition=case.condition,
            authority=case.authority,
            is_new_state=is_new_state,
            change_source=change_source,
        )
        decision = decide_by_rules(candidate, existing=existing)
        if (
            decision.kind is DecisionKind.SUPERSEDE
            and existing is not None
            and llm is not None
            and _old_still_true(llm, existing.value, case.candidate_value)
        ):
            return DecisionKind.MERGE.value
        return decision.kind.value

    raise ValueError(f"未知变体：{variant}")


def _old_still_true(llm: object, old_value: str, new_value: str) -> bool:
    """让模型判断"旧值是否仍然成立"。"""
    prompt = (
        "判断下面两条陈述是否都能同时为真。\n"
        f"旧记录：{old_value}\n"
        f"新陈述：{new_value}\n"
        '只回答 JSON：{"both_true": true} 或 {"both_true": false}'
    )
    try:
        result = llm.complete(  # type: ignore[attr-defined]
            [{"role": "user", "content": prompt}],
            response_format={"type": "json_object"},
        )
    except Exception:
        return False
    content = (getattr(result, "content", "") or "").lower()
    return '"both_true": true' in content.replace(" ", "")


def evaluate_variant(
    cases: tuple[IndependentCase, ...], *, variant: str, llm: object | None = None
) -> dict[str, object]:
    rows = []
    for case in cases:
        predicted = _predict(case, variant=variant, llm=llm)
        rows.append(
            {
                "id": case.id,
                "expected": case.expected.value,
                "predicted": predicted,
                "correct": predicted == case.expected.value,
            }
        )
    correct = sum(1 for row in rows if row["correct"])
    return {
        "variant": variant,
        "n": len(rows),
        "accuracy": correct / len(rows) if rows else 0.0,
        "wrong_ids": [row["id"] for row in rows if not row["correct"]],
        "rows": rows,
    }


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    data_path = Path(args[0]) if args else Path("data/conflict-set/independent.jsonl")
    dataset = load_independent_set(data_path)

    llm: object | None = None
    try:
        from memory.config import Settings
        from memory.llm.cache import ResponseCache
        from memory.llm.client import LLMClient

        settings = Settings.load()
        settings.cache_dir.mkdir(parents=True, exist_ok=True)
        llm = LLMClient(
            settings=settings,
            response_cache=ResponseCache(settings.cache_dir / "responses.db"),
        )
    except Exception as exc:
        print(f"模型不可用，semantic_merge 变体将跳过：{exc}", file=sys.stderr)

    results = []
    for variant in VARIANTS:
        if variant.name == "semantic_merge" and llm is None:
            continue
        result = evaluate_variant(dataset.cases, variant=variant.name, llm=llm)
        results.append(result)
        print(
            f"{variant.name:<22} accuracy={result['accuracy']:.4f} "
            f"wrong={len(result['wrong_ids'])}"
        )

    out = Path("results/independent-variants.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps(
            [
                {
                    "variant": result["variant"],
                    "description": next(
                        v.description for v in VARIANTS if v.name == result["variant"]
                    ),
                    "n": result["n"],
                    "accuracy": result["accuracy"],
                    "wrong_ids": result["wrong_ids"],
                }
                for result in results
            ],
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"\n-> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
