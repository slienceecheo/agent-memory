"""C4 泄漏诊断：SEH@5 = 1.000 到底由什么造成。

**这是一个诊断脚本，不在评测路径上**，不参与任何报告分数。
它只回答一个问题：把 C4 的三个构造缺陷逐层拆掉，分数会变成什么。

三个缺陷（都能从代码读出来，不需要猜）：

1. `query` 与 gold 的**存库原文**逐字相同（`annotate_retrieval.py` 把
   `query = row["text"]`，而 `run_retrieval._item` 又把同一句 `row["text"]`
   当作 gold 的 `text`）。于是 gold 那篇文档**就是查询本身**。
2. 干扰项的 `text` 为 `None`，`items_fts` 里只剩 `subject/relation/value`，
   与查询几乎零重叠——它们物理上无法竞争。
3. 指标只在**被召回的子集**上算排名。子集只有 1 条时，排名恒为 1。

四个变体：

| 变体 | gold 原文 | 干扰项原文 |
|---|---|---|
| V0 | 用 query 那句（现状） | 无 |
| V1 | 抹掉 | 无 |
| V2 | 用 query 那句 | 用各自的原文（近似重建） |
| V3 | 抹掉 | 用各自的原文（近似重建） |

**V0 与 V1 的差就是缺陷 1 的贡献；V0 与 V2 的差说明缺陷 2 有没有额外贡献。**

必须说明的一点：V1/V3 抹掉 gold 原文之后，gold **没有正确的原文可用**——
数据集从来没记录过"这条记忆是被哪句话写进去的"。所以 V1/V3 只能当作
**下界**，不能当作公平基线。这也正是 v2 数据集必须单独存 `memory_text` 的理由。

    uv run python -m evals.tools.diagnose_c4_leak
"""

from __future__ import annotations

import collections
import json
import tempfile
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from evals.run_retrieval import _item, select_pool_distractors
from memory.retrieval.condition import condition_match, parse_condition
from memory.retrieval.fusion import rrf
from memory.retrieval.lexical import recall_by_lexical
from memory.retrieval.pool import build_pool
from memory.retrieval.pool_modes import PoolMode
from memory.retrieval.rerank import (
    PREREGISTERED_WEIGHTS,
    FeatureScores,
    authority_score,
    rerank,
    rrf_norm,
    status_score,
)
from memory.store.sqlite import SqliteStore

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data" / "conflict-set"
OUT = ROOT / "results" / "c4-query-leak-ablation.json"
SPLITS = ("dev", "test", "independent")
K = 5

VARIANTS: tuple[tuple[str, str, bool, bool], ...] = (
    ("V0", "现状：gold 原文=query，干扰项无原文", False, False),
    ("V1", "抹掉 gold 原文，干扰项无原文", True, False),
    ("V2", "gold 原文=query，干扰项带各自原文", False, True),
    ("V3", "抹掉 gold 原文，干扰项带各自原文", True, True),
)


def _rows(split: str) -> list[dict[str, Any]]:
    path = DATA / f"{split}.jsonl"
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _spec_key(spec: dict[str, Any]) -> tuple[str, str, str, str]:
    return (
        str(spec["subject"]),
        str(spec["relation"]),
        str(spec.get("condition")),
        str(spec["value"]),
    )


class _Candidate:
    def __init__(self, item_id: str, features: FeatureScores) -> None:
        self.item_id = item_id
        self.features = features


def _run_case(
    row: dict[str, Any],
    *,
    specs: list[dict[str, Any]],
    provenance: dict[tuple[str, str, str, str], str],
    blank_gold: bool,
    distractor_text: bool,
) -> dict[str, Any] | None:
    gold_spec = row.get("gold")
    if not gold_spec:
        return None
    query = str(row["query"])
    selected = select_pool_distractors(gold_spec, specs, mode=PoolMode.UNRELATED, limit=20)
    if len(selected) + 1 <= K:
        return None

    gold_text = None if blank_gold else str(row.get("text") or "")
    distractors = []
    for index, spec in enumerate(selected):
        text = provenance.get(_spec_key(spec)) if distractor_text else None
        distractors.append(_item({"text": ""}, spec, tag=f"d{index}", text=text))

    with tempfile.TemporaryDirectory() as directory:
        store = SqliteStore(Path(directory) / "diag.db")
        try:
            gold = _item(row, gold_spec, tag="gold", text=gold_text)
            pool = build_pool(gold, distractors, seed=0)
            id_map: dict[str, Any] = {}
            for entry in pool.items:
                id_map[entry.id] = store.insert(replace(entry, id=""), reason="diag", actor="diag")
            gold_id = id_map[pool.gold_id].id

            hits = recall_by_lexical(store, query, limit=len(pool.items))
            fused = rrf({"lexical": [item.id for item in hits]}, k=60)
            score_by_id = {entry.item_id: entry.score for entry in fused}
            max_score = max(score_by_id.values()) if score_by_id else 0.0

            query_condition = row.get("condition")
            features_seen: dict[str, set[float]] = {
                "base": set(),
                "condition": set(),
                "authority": set(),
                "status": set(),
            }
            candidates: list[_Candidate] = []
            for item_id, score in score_by_id.items():
                item = store.get(item_id)
                features = FeatureScores(
                    base=rrf_norm(score, max_score=max_score),
                    condition=condition_match(
                        str(query_condition) if query_condition else None,
                        item.condition,
                    ),
                    authority=authority_score(item.authority),
                    status=status_score(item.status),
                )
                for name in features_seen:
                    features_seen[name].add(round(getattr(features, name), 6))
                candidates.append(_Candidate(item_id, features))

            ranked = rerank(candidates, weights=PREREGISTERED_WEIGHTS["uniform"])
            order = [entry.item_id for entry in ranked]
            fusion_order = [entry.item_id for entry in fused]
            return {
                "candidates": len(score_by_id),
                "gold_rank": order.index(gold_id) + 1 if gold_id in order else None,
                "gold_rank_fusion": (
                    fusion_order.index(gold_id) + 1 if gold_id in fusion_order else None
                ),
                "feature_variance": {k: len(v) > 1 for k, v in features_seen.items()},
            }
        finally:
            store.close()


def main() -> int:
    loaded = {split: _rows(split) for split in SPLITS}
    specs = [row["gold"] for split in SPLITS for row in loaded[split] if row.get("gold")]

    # 近似的"产生这条记忆的原话"：数据集没有这个字段，只能从 gold 反查。
    provenance: dict[tuple[str, str, str, str], str] = {}
    for split in SPLITS:
        for row in loaded[split]:
            if row.get("gold"):
                provenance[_spec_key(row["gold"])] = str(row.get("text") or "")

    payload: dict[str, Any] = {
        "generated": datetime.now(UTC).date().isoformat(),
        "purpose": "定位 C4 的 SEH@5=1.000 由哪些构造缺陷造成",
        "caveat": (
            "V1/V3 抹掉 gold 原文后，gold 没有正确的原文可用——数据集从未记录"
            "『这条记忆由哪句话写入』。因此 V1/V3 只能作为下界，不是公平基线。"
        ),
        "k": K,
        "variants": {},
        "feature_variance_v0": {},
        "distractor_sampling": {},
        "condition_supplied_vs_extracted": {},
    }

    for split in SPLITS:
        rows = loaded[split]
        payload["variants"][split] = {}
        for name, description, blank, dist in VARIANTS:
            results = [
                _run_case(
                    row,
                    specs=specs,
                    provenance=provenance,
                    blank_gold=blank,
                    distractor_text=dist,
                )
                for row in rows
            ]
            scored = [item for item in results if item]
            n = len(scored)
            seh = sum(1 for item in scored if item["gold_rank"] and item["gold_rank"] <= K) / n
            srs = (
                sum(1.0 / item["gold_rank"] if item["gold_rank"] else 0.0 for item in scored) / n
            )
            sizes = collections.Counter(item["candidates"] for item in scored)
            payload["variants"][split][name] = {
                "description": description,
                "n": n,
                "seh_at_k": round(seh, 6),
                "srs": round(srs, 6),
                "recall_size_histogram": {
                    str(size): count for size, count in sorted(sizes.items())
                },
                "single_candidate_cases": sizes.get(1, 0),
            }
            if name == "V0":
                counts = collections.Counter()
                for item in scored:
                    for feature, has_variance in item["feature_variance"].items():
                        counts[feature] += int(has_variance)
                payload["feature_variance_v0"][split] = {
                    "cases": n,
                    "with_variance": dict(counts),
                    "ratio": {k: round(v / n, 6) for k, v in counts.items()},
                }

    # 干扰项是"随机采样"还是"固定前缀"？
    compositions = collections.Counter()
    for split in SPLITS:
        for row in loaded[split]:
            if not row.get("gold"):
                continue
            picked = select_pool_distractors(
                row["gold"], specs, mode=PoolMode.UNRELATED, limit=20
            )
            compositions[
                tuple((s["subject"], s["relation"], str(s["value"])) for s in picked)
            ] += 1
    payload["distractor_sampling"] = {
        "distinct_compositions": len(compositions),
        "most_reused_composition_count": compositions.most_common(1)[0][1] if compositions else 0,
        "note": "select_pool_distractors 用 others[:limit] 取固定前缀，不是随机采样",
    }

    # query 里的条件能不能自己抽出来，还是靠 annotation 白给？
    supplied_only = 0
    extractable = 0
    total_conditioned = 0
    for split in SPLITS:
        for row in loaded[split]:
            raw = row.get("condition")
            if not raw:
                continue
            total_conditioned += 1
            from_query = parse_condition(str(row["query"]))
            from_field = parse_condition(str(raw))
            if from_query.is_empty:
                supplied_only += 1
            elif from_query.slots & from_field.slots:
                extractable += 1
    payload["condition_supplied_vs_extracted"] = {
        "total_conditioned": total_conditioned,
        "extractable_from_query": extractable,
        "only_in_annotation": supplied_only,
        "note": "condition_match 收到的是 annotation 的 condition 字段，不是从 query 抽的",
    }

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print(f"{'split':12} {'variant':32} {'n':>3} {'SEH@5':>6} {'SRS':>6} {'仅1条候选':>9}")
    for split in SPLITS:
        for name, _description, _blank, _dist in VARIANTS:
            bucket = payload["variants"][split][name]
            print(
                f"{split:12} {name:32} {bucket['n']:3} "
                f"{bucket['seh_at_k']:6.3f} {bucket['srs']:6.3f} "
                f"{bucket['single_candidate_cases']:9}"
            )

    print("\nV0 池内特征方差（真实候选池）")
    for split in SPLITS:
        bucket = payload["feature_variance_v0"][split]
        print(f"  {split:12} cases={bucket['cases']:3} {bucket['with_variance']}")

    print("\n干扰项采样：不同组合数 =", payload["distractor_sampling"]["distinct_compositions"])
    print("条件可抽取性：", payload["condition_supplied_vs_extracted"])
    print(f"\n-> {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
