"""用 `features_by_tag` + `fusion_tags` + 权重复算整池名次（验收 1 的实体）。

**这条测试与前一条的分工**：

- `test_rank_recompute`：构造并列，证明**融合顺序是必要输入**
- 本文件：用**真实数据**复算，证明端到端名次 0 差异

少任何一条都不够：构造测试证明"规则对"，真实测试证明"数据记全了"。
"""

from __future__ import annotations

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data" / "retrieval-v2"


def _run(subject: str, paths: tuple[str, ...]) -> dict[str, object]:
    from evals.datasets.retrieval_v2 import load_dataset
    from evals.datasets.v2_adapter import rows as adapt_rows
    from evals.run_retrieval import evaluate

    from memory.retrieval.pool_modes import PoolMode

    path = DATA / subject
    if not path.exists():
        pytest.skip(f"{subject} 缺失")
    rows = adapt_rows(load_dataset(path))
    specs = [r["gold"] for r in rows if r["gold"]]
    return evaluate(
        rows,
        all_specs=specs,
        weights_name="uniform",
        enable_dedup=False,
        judge=None,
        k=5,
        pool_mode=PoolMode.UNRELATED,
        paths=paths,
    )


@pytest.mark.parametrize(
    ("subject", "paths"),
    [
        ("sample", ("lexical",)),
        ("billing", ("lexical",)),
        ("sample", ("adjacency",)),
        ("billing", ("adjacency",)),
    ],
)
def test_rank_recomputes_with_zero_differences(
    subject: str, paths: tuple[str, ...]
) -> None:
    """**验收 1**：复算的整池名次必须与 `rank_after_rerank` 逐条相同（0 差异）。

    这是"三特征排序在给定池上的结果可复算"的实体。
    若特征分记错、漏记候选、或复算漏了融合顺序，这里都会红。
    """
    from evals.run_retrieval import PREREGISTERED_WEIGHTS, recompute_order

    from memory.retrieval.rerank import FeatureScores

    result = _run(subject, paths)
    weights = PREREGISTERED_WEIGHTS[str(result["weights"])]

    class _C:
        def __init__(self, tag: str, f: dict[str, float]) -> None:
            self.item_id = tag
            self.features = FeatureScores(
                base=f["base"],
                condition=0.0,
                authority=f["authority"],
                status=f["status"],
            )

    checked = 0
    nontrivial = 0
    for case in result["per_case"]:  # type: ignore[union-attr]
        if not case.get("has_gold") or case.get("skipped"):
            continue
        gold_tag = f"gold-{case['case_id']}"
        by_tag = case["features_by_tag"]
        order = case["rerank_order_tags"]
        fusion = case["fusion_tags"]

        recomputed = recompute_order(
            [_C(t, by_tag[t]) for t in by_tag],
            weights=weights,
            fusion_tags=fusion,
        )

        assert recomputed == order, (
            f"{case['case_id']}: 复算名次与原结果不同。\n"
            f"  原: {order}\n"
            f"  复: {recomputed}\n"
            f"  gold 原名次: {order.index(gold_tag) + 1 if gold_tag in order else None}"
        )
        checked += 1
        if len(by_tag) > 1:
            nontrivial += 1

    assert checked > 0, f"{subject}/{paths}: 没有可复算的 case"

    # **强度约束**：池只有 1 条的 case，任何实现都"复算一致"——
    # 那不能证明排序规则被复现了。
    #
    # 实测（`data/retrieval-v2`）：
    #   sample/lexical   池>1 共 5 条
    #   billing/lexical  池>1 共 7 条
    #   sample/adjacency 池>1 共 10 条，但 gold **全部未召回**（名次全 None）
    #   billing/adjacency 池>1 共 12 条，同上
    #
    # 所以下界取 5：它允许 lexical 的最差情形通过，但拦住"池全为 1"的退化。
    assert nontrivial >= 5, (
        f"{subject}/{paths}: 只有 {nontrivial}/{checked} 条 case 的池大于 1。"
        "此时'复算一致'几乎不含信息（单条候选的顺序必然相同）。"
    )


def test_rank_recomputes_on_multi_path_pool() -> None:
    """**多路池**（lexical + vector）上的复算，池比单路大得多。

    **为什么必须单独一条**：单路 lexical 的池最大只有 4 条（实测），
    在那样的池上"整池顺序一致"的说服力有限。
    报告里的数字来自多路，所以复算也必须在多路池上成立。

    用确定性 stub embedder（按文本 sha256 生成 1024 维单位向量），
    不碰网络、不碰缓存——复算的正确性不该依赖上游模型。
    """
    import hashlib

    from evals.datasets.retrieval_v2 import load_dataset
    from evals.datasets.v2_adapter import rows as adapt_rows
    from evals.run_retrieval import (
        PREREGISTERED_WEIGHTS,
        evaluate,
        recompute_order,
    )

    from memory.retrieval.pool_modes import PoolMode
    from memory.retrieval.rerank import FeatureScores

    dims = 1024

    class _HashEmbedder:
        network_calls = 0

        def embed(self, text: str, *, text_type: str = "document") -> list[float]:
            seed = hashlib.sha256(text.encode("utf-8")).digest()
            raw = [((seed[i % len(seed)] + i) % 251) / 251.0 - 0.5 for i in range(dims)]
            norm = sum(v * v for v in raw) ** 0.5 or 1.0
            return [v / norm for v in raw]

    rows = adapt_rows(load_dataset(DATA / "billing"))
    specs = [r["gold"] for r in rows if r["gold"]]
    result = evaluate(
        rows,
        all_specs=specs,
        weights_name="uniform",
        enable_dedup=False,
        judge=None,
        k=5,
        pool_mode=PoolMode.UNRELATED,
        paths=("lexical", "vector"),
        embedder=_HashEmbedder(),
    )
    weights = PREREGISTERED_WEIGHTS[str(result["weights"])]

    class _C:
        def __init__(self, tag: str, f: dict[str, float]) -> None:
            self.item_id = tag
            self.features = FeatureScores(
                base=f["base"], condition=0.0,
                authority=f["authority"], status=f["status"],
            )

    checked = 0
    big = 0
    for case in result["per_case"]:  # type: ignore[union-attr]
        if not case.get("has_gold") or case.get("skipped"):
            continue
        by_tag = case["features_by_tag"]
        recomputed = recompute_order(
            [_C(t, by_tag[t]) for t in by_tag],
            weights=weights,
            fusion_tags=case["fusion_tags"],
        )
        assert recomputed == case["rerank_order_tags"], case["case_id"]
        checked += 1
        if len(by_tag) >= 5:
            big += 1

    assert checked > 0
    assert big >= 5, (
        f"只有 {big}/{checked} 条 case 的池 ≥5。"
        "多路池本该明显更大——若这条不成立，说明多路没真正生效。"
    )


def test_gold_rank_equals_index_in_recomputed_order() -> None:
    """`rank_after_rerank` 必须等于复算顺序里 gold 的位置 + 1。

    **这条与上一条的区别**：上一条比整池顺序（含所有干扰项），
    这条只比 gold 的名次——后者是报告里被引用的数字，
    而它可能因为"整池顺序对但 gold 不在池里"这类边界而错。
    """
    from evals.run_retrieval import PREREGISTERED_WEIGHTS, recompute_order

    from memory.retrieval.rerank import FeatureScores

    result = _run("billing", ("lexical",))
    weights = PREREGISTERED_WEIGHTS[str(result["weights"])]

    class _C:
        def __init__(self, tag: str, f: dict[str, float]) -> None:
            self.item_id = tag
            self.features = FeatureScores(
                base=f["base"], condition=0.0,
                authority=f["authority"], status=f["status"],
            )

    for case in result["per_case"]:  # type: ignore[union-attr]
        if not case.get("has_gold") or case.get("skipped"):
            continue
        gold_tag = f"gold-{case['case_id']}"
        by_tag = case["features_by_tag"]

        recomputed = recompute_order(
            [_C(t, by_tag[t]) for t in by_tag],
            weights=weights,
            fusion_tags=case["fusion_tags"],
        )
        expected = recomputed.index(gold_tag) + 1 if gold_tag in recomputed else None

        assert case["rank_after_rerank"] == expected, (
            f"{case['case_id']}: rank_after_rerank={case['rank_after_rerank']}，"
            f"复算得 {expected}"
        )
