"""F20：A 轴必须证明 `condition` 有贡献（条件消融）。

**为什么需要这条**：有人可以写出一批"explicit 占多数、condition 全都匹配"的
查询，也得到很高的 `SEH@1`——而 A 轴的设计意图（多个条件分支里挑对）
完全落空。只报分数看不出来。

**做法**：把全部查询的 `query_condition` 置空，重跑三路。
若 A 轴 `SEH@1` 的掉幅 < 0.3，说明条件在这份数据上不起作用。

实测样例（`data/retrieval-v2/sample`）：

| 指标 | 有 condition | 消融后 | 掉幅 |
|---|---|---|---|
| A 轴 `SEH@1` | 0.9000 | 0.3000 | **+0.6000** |
| implicit `SEH@1` | 0.7500 | 0.0000 | +0.7500 |
| explicit `SEH@1` | 1.0000 | 0.5000 | +0.5000 |

`never_recalled` 在两种配置下都是 0——**变的是名次，不是召回**。
这是 A 轴"测区分而非测召回"的直接证据。

    uv run --no-sync python -m evals.tools.ablate_condition --dataset data/retrieval-v2/sample
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from evals.datasets.retrieval_v2 import load_dataset
from evals.datasets.v2_adapter import rows as adapt_rows
from evals.run_retrieval import evaluate
from memory.retrieval.pool_modes import PoolMode

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_THRESHOLD = 0.30


def _axis_seh1(ranks: dict[str, int | None], axis_of: dict[str, str], axis: str) -> float:
    ids = [cid for cid in ranks if axis_of[cid] == axis]
    if not ids:
        return 0.0
    return sum(1 for cid in ids if ranks[cid] == 1) / len(ids)


def _cue_seh1(
    ranks: dict[str, int | None],
    cue_of: dict[str, str],
    axis_of: dict[str, str],
    cue: str,
) -> float:
    ids = [cid for cid in ranks if cue_of[cid] == cue and axis_of[cid] == "A"]
    if not ids:
        return 0.0
    return sum(1 for cid in ids if ranks[cid] == 1) / len(ids)


def _run(rows: list[dict[str, Any]], *, embedder: Any) -> dict[str, int | None]:
    specs = [r["gold"] for r in rows if r["gold"]]
    result = evaluate(
        rows,
        all_specs=specs,
        weights_name="uniform",
        enable_dedup=False,
        judge=None,
        k=5,
        pool_mode=PoolMode.UNRELATED,
        paths=("lexical", "vector", "adjacency"),
        embedder=embedder,
    )
    return {
        c["case_id"]: c["rank_after_rerank"]
        for c in result["per_case"]  # type: ignore[union-attr]
        if c.get("has_gold") and not c.get("skipped")
    }


def ablate(dataset_dir: Path, *, embedder: Any) -> dict[str, Any]:
    """跑有 condition 与无 condition 两组，返回掉幅与逐条变化。"""
    ds = load_dataset(dataset_dir)
    base_rows = adapt_rows(ds)
    axis_of = {q.query_id: q.axis.value for q in ds.queries}
    cue_of = {q.query_id: q.cue_type.value for q in ds.queries}

    with_cond = _run(base_rows, embedder=embedder)

    ablated_rows = []
    for row in base_rows:
        r = dict(row)
        r["condition"] = None
        ablated_rows.append(r)
    without_cond = _run(ablated_rows, embedder=embedder)

    changed = [
        cid for cid in with_cond if with_cond[cid] != without_cond.get(cid)
    ]
    return {
        "with_condition": with_cond,
        "without_condition": without_cond,
        "axis_a_seh1_with": _axis_seh1(with_cond, axis_of, "A"),
        "axis_a_seh1_without": _axis_seh1(without_cond, axis_of, "A"),
        "drop": _axis_seh1(with_cond, axis_of, "A")
        - _axis_seh1(without_cond, axis_of, "A"),
        "implicit_with": _cue_seh1(with_cond, cue_of, axis_of, "implicit"),
        "implicit_without": _cue_seh1(without_cond, cue_of, axis_of, "implicit"),
        "explicit_with": _cue_seh1(with_cond, cue_of, axis_of, "explicit"),
        "explicit_without": _cue_seh1(without_cond, cue_of, axis_of, "explicit"),
        "changed": changed,
        "never_recalled_with": sum(1 for v in with_cond.values() if v is None),
        "never_recalled_without": sum(1 for v in without_cond.values() if v is None),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="evals.tools.ablate_condition")
    parser.add_argument("--dataset", type=Path, default=None)
    parser.add_argument("--threshold", type=float, default=DEFAULT_THRESHOLD)
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args(argv)

    dataset_dir = args.dataset or (ROOT / "data" / "retrieval-v2" / "sample")
    if not dataset_dir.is_dir():
        print(f"数据集目录不存在：{dataset_dir}")
        return 2

    from memory.config import Settings
    from memory.embedding.cache import EmbeddingCache
    from memory.embedding.dashscope import DashScopeEmbedder

    settings = Settings.load()
    settings.cache_dir.mkdir(parents=True, exist_ok=True)
    embedder = DashScopeEmbedder(
        settings=settings, cache=EmbeddingCache(settings.cache_dir / "cache.db")
    )

    result = ablate(dataset_dir, embedder=embedder)
    result["dataset"] = str(dataset_dir)
    result["threshold"] = args.threshold
    result["passed"] = result["drop"] >= args.threshold

    print(f"数据集：{dataset_dir}")
    print(
        f"  A 轴 SEH@1  有 condition={result['axis_a_seh1_with']:.4f} "
        f"消融后={result['axis_a_seh1_without']:.4f} "
        f"掉幅={result['drop']:+.4f}（阈值 ≥{args.threshold}）"
    )
    print(
        f"  implicit    {result['implicit_with']:.4f} → {result['implicit_without']:.4f}"
    )
    print(
        f"  explicit    {result['explicit_with']:.4f} → {result['explicit_without']:.4f}"
    )
    print(
        f"  never_recalled  有 condition={result['never_recalled_with']} "
        f"消融后={result['never_recalled_without']}"
    )
    print(f"  变化的 case：{len(result['changed'])} 条 {result['changed']}")
    print()
    if result["passed"]:
        print("F20 PASS：condition 对 A 轴有可观测贡献")
    else:
        print(
            "F20 FAIL：condition 消融后没用明显下降——"
            "A 轴测的可能是召回，不是条件区分"
        )

    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(
            json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        print(f"-> {args.out}")

    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
