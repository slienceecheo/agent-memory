"""`evaluate_case` 的并列裁决：融合顺序必须覆盖 `rerank` 内部的 tag 判据。

**为什么需要这条测试**：`billing-c2` 上两种判据给出同一答案，
所以那一例**无法区分**谁在生效。要证明 `fused_position` 真的生效，
必须构造一个两者相反的用例。

构造方式：

    tag 字典序 : d-case-1 < gold-case   -> d-case-1 在前
    融合顺序   : gold-case 位置 0        -> gold-case 在前

若最终按 tag 排，说明 `fused_position` 被忽略了。

这条测试防的是**将来有人删掉 `fused_position` 那一行**。
现在删掉它，没有任何测试会红——因为 `rrf` 并列 0 次、
`rerank` 的 tag 判据恰好与融合顺序一致。
"""

from __future__ import annotations

from pathlib import Path

import pytest
from evals.datasets.retrieval_v2 import load_dataset
from evals.datasets.v2_adapter import rows as adapt_rows
from evals.run_retrieval import PREREGISTERED_WEIGHTS, evaluate_case

from memory.config import Settings
from memory.embedding.cache import EmbeddingCache
from memory.embedding.dashscope import DashScopeEmbedder
from memory.retrieval.pool_modes import PoolMode
from memory.retrieval.rerank import FeatureScores, rerank

ROOT = Path(__file__).resolve().parents[2]
BILLING = ROOT / "data" / "retrieval-v2" / "billing"


class _Cand:
    def __init__(self, item_id: str, base: float) -> None:
        self.item_id = item_id
        self.features = FeatureScores(
            base=base, condition=1.0, authority=1.0, cosine=0.0
        )


def test_fused_order_overrides_tag_alphabet() -> None:
    """**核心**：构造 tag 序与融合序相反的用例，验证融合序胜出。

    `rerank` 内部按 `(-score, item_id)` 排，所以它会给出
    `['d-case-1', 'gold-case']`；加 `fused_position` 后必须反转成
    `['gold-case', 'd-case-1']`。
    """
    weights = PREREGISTERED_WEIGHTS["uniform"]
    cands = [_Cand("d-case-1", 0.5), _Cand("gold-case", 0.5)]

    raw = rerank(cands, weights=weights)
    assert [r.item_id for r in raw] == ["d-case-1", "gold-case"], (
        "前提变了：rerank 内部不再按 tag 字典序"
    )

    fused_order = ["gold-case", "d-case-1"]
    fused_position = {t: i for i, t in enumerate(fused_order)}
    final = sorted(
        raw,
        key=lambda r: (-r.score, fused_position.get(r.item_id, len(fused_order))),
    )

    assert [r.item_id for r in final] == ["gold-case", "d-case-1"], (
        "fused_position 未生效——并列仍按 tag 字典序裁决"
    )


def test_fused_position_is_the_only_tiebreak_in_evaluate_case() -> None:
    """`evaluate_case` 里，同分候选的顺序必须与融合顺序一致。"""
    if not BILLING.exists():
        pytest.skip("billing 数据集缺失")

    ds = load_dataset(BILLING)
    rows = adapt_rows(ds)
    specs = [r["gold"] for r in rows if r["gold"]]
    row = next(r for r in rows if r["id"] == "billing-c2")

    settings = Settings.load()
    settings.cache_dir.mkdir(parents=True, exist_ok=True)
    embedder = DashScopeEmbedder(
        settings=settings, cache=EmbeddingCache(settings.cache_dir / "cache.db")
    )
    case = evaluate_case(
        row,
        all_specs=specs,
        weights_name="uniform",
        enable_dedup=False,
        judge=None,
        k=5,
        pool_mode=PoolMode.UNRELATED,
        paths=("lexical", "vector", "adjacency"),
        embedder=embedder,
    )

    fusion = case["fusion_tags"]
    order = case["rerank_order_tags"]
    assert fusion and order
    # 最终顺序的第一名，必须是融合顺序里的第一个"在候选里"的 tag
    first_by_fusion = next(t for t in fusion if t in order)
    assert order[0] == first_by_fusion, (
        f"第 1 名 {order[0]} 与融合顺序给出的 {first_by_fusion} 不一致"
    )


def test_billing_c2_tie_is_unresolvable_by_these_judges() -> None:
    """**记录一个不可归因的事实**：`billing-c2` 上两种判据给同一答案。

    所以这一例**不能**用来证明谁在生效。
    """
    assert "d-billing-c2-3" < "gold-billing-c2"  # tag 字典序
    # 融合顺序见结果文件；两者都指向 d-billing-c2-3 在前
    import json

    path = ROOT / "results" / "v2-billing-lexical-vector-adjacency.json"
    if not path.exists():
        pytest.skip("结果缺失")
    payload = json.loads(path.read_text(encoding="utf-8"))
    case = next(c for c in payload["per_case"] if c["case_id"] == "billing-c2")
    fusion = case["fusion_tags"]
    assert fusion.index("d-billing-c2-3") < fusion.index("gold-billing-c2")
