"""结论 5 在新装置下重测。

**这是任务 4.1 的"预期红"来源**：换装置后 `EXPECTED` 的数字会变。

同时测 mixed 与 cosine_only，因为报告 §6.14 要两套数字。
"""

from __future__ import annotations

from pathlib import Path

import pytest

ROOT = Path(".").resolve()
DATA = ROOT / "data" / "retrieval-v2"
SUBJECTS = ("sample", "billing")


@pytest.fixture(scope="module")
def measured():
    from evals.datasets.retrieval_v2 import load_dataset
    from evals.datasets.v2_adapter import rows as adapt_rows
    from evals.metrics.v2_baselines import derived_axis_of
    from evals.run_retrieval import evaluate

    from memory.config import Settings
    from memory.embedding.cache import EmbeddingCache
    from memory.embedding.dashscope import DashScopeEmbedder
    from memory.retrieval.pool_modes import PoolMode

    settings = Settings.load()
    settings.cache_dir.mkdir(parents=True, exist_ok=True)
    emb = DashScopeEmbedder(
        settings=settings, cache=EmbeddingCache(settings.cache_dir / "cache.db")
    )

    out: dict[str, dict] = {}
    for subject in SUBJECTS:
        ds = load_dataset(DATA / subject)
        rows = adapt_rows(ds)
        specs = [r["gold"] for r in rows if r["gold"]]
        within = {
            q.query_id
            for q in ds.queries
            if derived_axis_of(ds, q) == "relation_within"
        }
        out[subject] = {}

        for label, paths in (
            ("lexical", ("lexical",)),
            ("threeway", ("lexical", "vector", "adjacency")),
        ):
            for wname in ("uniform", "cosine_only"):
                res = evaluate(
                    rows,
                    all_specs=specs,
                    weights_name=wname,
                    enable_dedup=False,
                    judge=None,
                    k=5,
                    pool_mode=PoolMode.UNRELATED,
                    paths=paths,
                    embedder=emb,
                )
                recs = []
                for case in res["per_case"]:
                    cid = case["case_id"]
                    if cid not in within:
                        continue
                    if not case.get("has_gold") or case.get("skipped"):
                        continue
                    if case.get("rank_after_fusion") is None:
                        continue
                    recs.append(
                        {
                            "cid": cid,
                            "space": len(case.get("fusion_tags") or []),
                            "hit": case.get("rank_after_rerank") == 1,
                        }
                    )
                n = len(recs)
                hit = sum(1 for r in recs if r["hit"])
                base = sum(1 / r["space"] for r in recs) / n if n else 0.0
                out[subject][f"{label}/{wname}"] = {
                    "n": n,
                    "hit": hit,
                    "seh1": hit / n if n else 0.0,
                    "base": base,
                    "gain": (hit / n - base) if n else 0.0,
                    "hits": {r["cid"] for r in recs if r["hit"]},
                    "all": {r["cid"] for r in recs},
                }
    return out


@pytest.mark.parametrize("subject", SUBJECTS)
def test_report_new_numbers(measured, subject: str) -> None:
    """打印实测数字（这个测试的"断言"是它跑通；数字用于回填报告）。"""
    m = measured[subject]
    print(f"\n=== {subject} ===")
    for key, v in m.items():
        print(
            f"  {key:24} n={v['n']:2}  hit={v['hit']:2}  "
            f"SEH@1={v['seh1']:.4f}  base={v['base']:.4f}  gain={v['gain']:+.4f}"
        )

    # 配对比较：lexical 与 threeway 都召回了 gold 的 case
    lex = m["lexical/uniform"]
    tri_new = m["threeway/uniform"]
    paired = lex["all"] & tri_new["all"]
    print(f"  配对 n={len(paired)}")
    if paired:
        lh = len(lex["hits"] & paired)
        th = len(tri_new["hits"] & paired)
        print(f"    配对 lexical {lh}/{len(paired)} = {lh/len(paired):.4f}")
        print(f"    配对 threeway {th}/{len(paired)} = {th/len(paired):.4f}")
