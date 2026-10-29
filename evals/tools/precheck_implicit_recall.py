"""铺新 subject 前的召回预检：只看 implicit 的 gold 能不能被召回。

**为什么需要独立脚本**：F19b 要跑完全部 26 项门禁才执行，而它红的时候
已经写了 7 条记忆 + 9 条查询。若 4 条 implicit 里有 2 条召不回，要改的是
查询文本，改完还要重跑整批。

本脚本只跑三路召回，几秒出结果，对每个新 subject 都能用。

**它和 F19b 的分工**：

| | 覆盖范围 | 何时跑 | 输出 |
|---|---|---|---|
| 本脚本 | 单个 subject 目录 | 铺完立刻 | 逐条 implicit 的召回状态 |
| F19b | 全量数据集 | 全量门禁 | 一条通过/失败 |

    uv run --no-sync python -m evals.tools.precheck_implicit_recall \
        --dataset data/retrieval-v2/billing
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from evals.datasets.retrieval_v2 import CueType, load_dataset
from evals.datasets.v2_adapter import rows as adapt_rows
from evals.run_retrieval import evaluate
from memory.retrieval.pool_modes import PoolMode

ROOT = Path(__file__).resolve().parents[2]


def precheck(dataset_dir: Path, *, embedder: object) -> int:
    ds = load_dataset(dataset_dir)
    rows = adapt_rows(ds)
    specs = [r["gold"] for r in rows if r["gold"]]

    implicit = [q for q in ds.queries if q.cue_type is CueType.IMPLICIT]
    if not implicit:
        print("没有 implicit 查询——打印这一条没有意义，但也不算失败。")
        return 0

    # 只跑三路召回，不需要重排与指标；但 evaluate 是唯一入口，只好用它。
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
    by_case = {c["case_id"]: c for c in result["per_case"]}  # type: ignore[index]

    print(f"数据集：{dataset_dir}")
    print(f"implicit 查询：{len(implicit)} 条\n")
    print(f"{'query_id':14} {'axis':4} {'lex':>5} {'vec':>5} {'adj':>5}  {'状态':>8}")
    print("-" * 58)

    bad: list[str] = []
    for q in implicit:
        case = by_case[q.query_id]
        ret = case["path_returns"]
        lex = ret.get("lexical")
        vec = ret.get("vector")
        adj = ret.get("adjacency")
        hit = any(v is not None and v > 0 for v in (lex, vec, adj))
        status = "召回" if hit else "**零召回**"
        if not hit:
            bad.append(q.query_id)
        print(
            f"{q.query_id:14} {q.axis.value:4} "
            f"{'-' if lex is None else lex:>5} "
            f"{'-' if vec is None else vec:>5} "
            f"{'-' if adj is None else adj:>5}  {status:>8}"
        )

    print()
    if bad:
        print(f"**预检未通过**：{len(bad)} 条 implicit 三路全零召回")
        print("  这些查询的 0 分会被记成'条件区分失败'，但实际是召回失败。")
        print("  要改的是查询文本（让它与 gold 的 memory_text 有语义交集）。")
        for qid in bad:
            q = next(x for x in implicit if x.query_id == qid)
            gold = ds.memory(q.gold_memory_id)
            print(f"\n  {qid}")
            print(f"    query: {q.query}")
            print(f"    gold : {gold.memory_text}")
        return 1

    print(f"预检通过：{len(implicit)} 条 implicit 的 gold 都至少被一路召回")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="evals.tools.precheck_implicit_recall")
    parser.add_argument("--dataset", type=Path, required=True)
    args = parser.parse_args(argv)

    if not args.dataset.is_dir():
        print(f"数据集目录不存在：{args.dataset}", file=sys.stderr)
        return 2

    from memory.config import Settings
    from memory.embedding.cache import EmbeddingCache
    from memory.embedding.dashscope import DashScopeEmbedder

    settings = Settings.load()
    settings.cache_dir.mkdir(parents=True, exist_ok=True)
    embedder = DashScopeEmbedder(
        settings=settings, cache=EmbeddingCache(settings.cache_dir / "cache.db")
    )
    return precheck(args.dataset, embedder=embedder)


if __name__ == "__main__":
    raise SystemExit(main())
