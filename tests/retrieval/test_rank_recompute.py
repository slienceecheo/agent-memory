"""离线复算名次的三个输入（tasks 3.2 / 3.3 的守卫）。

**为什么这条测试必须存在**：`rank_after_rerank` 是两步的结果——

```python
ranked = rerank(candidates, weights)                        # 按 score
ranked = sorted(ranked, key=(-score, fused_position[tag]))  # 并列用融合顺序
```

**只复现第一步，在无并列的数据上永远绿。** 而并列恰恰是这个装置最容易错的地方：
`rerank` 内部的并列判据是 `item_id`（tag 字典序），那会让 `d-<case>-0` 恒排在
`gold-<case>` 之前（"d" < "g"）——一个固定的偏向，看起来却像"排序结果"。

**所以本文件用构造数据造出并列，且让两种裁决给出相反名次。**
这样"复算忽略了融合顺序"会立刻红，而不是等到某份真实数据恰好并列时才发现。
"""

from __future__ import annotations

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data" / "retrieval-v2"


class _Cand:
    def __init__(
        self, tag: str, base: float, authority: float = 1.0, cosine: float = 1.0
    ):
        from memory.retrieval.rerank import FeatureScores

        self.item_id = tag
        self.features = FeatureScores(
            base=base, condition=0.0, authority=authority, cosine=cosine
        )


def test_tie_rank_depends_on_fusion_order() -> None:
    """**构造并列**：两种裁决给出相反名次，证明融合顺序确实参与决定。

    构造必须同时固定两件事，缺一则这条测试失去区分力：

    | 条件 | 作用 |
    |---|---|
    | 两条的**分数完全相同** | 并列成立 |
    | 融合位置**反向于 tag 字典序** | 两种裁决才会给出相反名次 |

    **第二条件是关键，而它容易被漏掉。** 实测 `billing-c2`（v2 唯一真正并列的 case）
    就不满足它：

    ```
    fused_position: gold=1, d-billing-c2-3=0  -> d 在前
    tag 字典序    : "d-billing-c2-3" < "gold-billing-c2" -> d 在前
    两种裁决同向 -> 不能区分
    ```

    **所以"数据里有并列"不等于"这个并列能验证裁决规则"**——
    事实存在 ≠ 该事实能验证机制。
    """
    from evals.run_retrieval import PREREGISTERED_WEIGHTS

    from memory.retrieval.rerank import rerank

    weights = PREREGISTERED_WEIGHTS["uniform"]
    cands = [_Cand("d-1", 0.5), _Cand("gold", 0.5)]

    raw = rerank(cands, weights=weights)
    score = {r.item_id: r.score for r in raw}
    assert score["gold"] == score["d-1"], (
        "条件一不成立：两者分数不同，这条测试无法证明并列裁决。"
    )

    # **显式断言"反向"**：若不反向，两种裁决同向，这条测试什么也证明不了。
    fused = ["gold", "d-1"]
    assert fused.index("gold") < fused.index("d-1"), (
        "条件二不成立：gold 的融合位置应更小"
    )
    assert "gold" > "d-1", (
        "条件二不成立：tag 字典序里 gold 必须更大（'d' < 'g'），"
        "否则两种裁决同向，无法区分"
    )

    # 按 tag 字典序（rerank 内部）：d-1 在前
    assert [r.item_id for r in raw] == ["d-1", "gold"]

    # 按融合顺序：gold 在前
    fpos = {t: i for i, t in enumerate(fused)}
    final = sorted(raw, key=lambda r: (-r.score, fpos.get(r.item_id, len(fused))))
    assert [r.item_id for r in final] == ["gold", "d-1"]

    # 两种裁决给出的名次确实不同
    assert final.index(raw[0]) != raw.index(raw[0]), (
        "两种裁决给出了相同名次——这条测试不能区分它们"
    )


def test_recompute_helper_matches_two_step_order() -> None:
    """`evaluate` 给出的复算输入（features_by_tag + fusion_tags）必须能还原名次。"""
    from evals.run_retrieval import PREREGISTERED_WEIGHTS, recompute_order

    from memory.retrieval.rerank import FeatureScores

    features_by_tag = {
        "gold-c1": {"base": 0.5, "authority": 1.0, "cosine": 0.0},
        "d-c1-1": {"base": 0.5, "authority": 1.0, "cosine": 0.0},
        "d-c1-2": {"base": 0.9, "authority": 1.0, "cosine": 0.0},
    }
    fusion_tags = ["gold-c1", "d-c1-1", "d-c1-2"]

    class _C:
        def __init__(self, tag: str) -> None:
            f = features_by_tag[tag]
            self.item_id = tag
            self.features = FeatureScores(
                base=f["base"], condition=0.0,
                authority=f["authority"], cosine=f["cosine"],
            )

    order = recompute_order(
        [_C(t) for t in features_by_tag],
        weights=PREREGISTERED_WEIGHTS["uniform"],
        fusion_tags=fusion_tags,
    )
    # d-c1-2 分最高；gold 与 d-c1-1 同分，按融合顺序 gold 在前
    assert order == ["d-c1-2", "gold-c1", "d-c1-1"]


def test_recompute_helper_without_fusion_order_differs() -> None:
    """**反例**：不用融合顺序就得到不同名次——证明这个输入不是可选的。"""
    from evals.run_retrieval import PREREGISTERED_WEIGHTS, recompute_order

    from memory.retrieval.rerank import FeatureScores

    features = {
        "gold-c1": {"base": 0.5, "authority": 1.0, "cosine": 0.0},
        "d-c1-1": {"base": 0.5, "authority": 1.0, "cosine": 0.0},
    }

    class _C:
        def __init__(self, tag: str) -> None:
            f = features[tag]
            self.item_id = tag
            self.features = FeatureScores(
                base=f["base"], condition=0.0,
                authority=f["authority"], cosine=f["cosine"],
            )

    with_fusion = recompute_order(
        [_C("gold-c1"), _C("d-c1-1")],
        weights=PREREGISTERED_WEIGHTS["uniform"],
        fusion_tags=["gold-c1", "d-c1-1"],
    )
    # 反过来传输入顺序，模拟"候选列表来自另一处"
    without = recompute_order(
        [_C("d-c1-1"), _C("gold-c1")],
        weights=PREREGISTERED_WEIGHTS["uniform"],
        fusion_tags=None,
    )

    assert with_fusion == ["gold-c1", "d-c1-1"]
    assert without == ["d-c1-1", "gold-c1"], (
        "不传融合顺序时，同分候选的顺序由**输入顺序**决定——"
        "这正是'缺输入会静默给出另一个名次'的演示，不是正确行为"
    )
    assert with_fusion != without, (
        "两种裁决给出了相同名次，这条测试无法证明融合顺序是必要输入"
    )


def _run(subject: str = "billing") -> dict[str, object]:
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
        paths=("lexical",),
    )


def test_features_by_tag_keys_match_rerank_input() -> None:
    """**键集合 == 进入重排的候选集合**：`len(features_by_tag) == len(rerank_order_tags)`。

    这条现在恒真（去重从不合并），**而这正是要写下来的理由**：
    它让"将来去重开始合并"这件事在这里立刻可见。
    `features_by_tag` 若按 `fused_order` 存，会多出没参与重排的候选，
    离线复算的名次就会偏移——而分数全对，看不出问题。
    """
    result = _run()
    for case in result["per_case"]:  # type: ignore[union-attr]
        if not case.get("has_gold") or case.get("skipped"):
            continue
        by_tag = case.get("features_by_tag")
        order = case.get("rerank_order_tags")
        if not isinstance(by_tag, dict) or not isinstance(order, list):
            continue
        assert set(by_tag) == set(order), (
            f"{case['case_id']}: features_by_tag 的键与重排输入不同。"
            f"只在 features 侧：{sorted(set(by_tag) - set(order))}；"
            f"只在 order 侧：{sorted(set(order) - set(by_tag))}"
        )


def test_gold_features_are_consistent_with_pool() -> None:
    """`features`（gold 的三项）必须等于 `features_by_tag[gold_tag]`。

    **两个来源同一事实**是这一路反复出现的形态（8 键两个来源、两套判据、两份指纹）。
    它们可以不一致，而形状检查永远不红——所以必须显式比对。
    """
    result = _run()
    for case in result["per_case"]:  # type: ignore[union-attr]
        if not case.get("has_gold") or case.get("skipped"):
            continue
        gold_tag = f"gold-{case['case_id']}"
        by_tag = case["features_by_tag"]
        if gold_tag not in by_tag:
            continue
        assert case["features"] == by_tag[gold_tag], (
            f"{case['case_id']}: features 与 features_by_tag[gold] 不一致。"
            f"features={case['features']}，池内={by_tag[gold_tag]}"
        )

def test_unretrieved_gold_is_declared_by_both_sides() -> None:
    """**gold 未召回**必须两侧同时表达：`features is None` 且 gold tag 不在池里。

    不能一个为 `None` 一个有条目——那是一份数据两种说法。
    """
    result = _run()
    n_unretrieved = 0
    n_retrieved = 0
    for case in result["per_case"]:  # type: ignore[union-attr]
        if not case.get("has_gold") or case.get("skipped"):
            continue
        gold_tag = f"gold-{case['case_id']}"
        in_pool = gold_tag in case["features_by_tag"]
        has_features = case["features"] is not None
        assert in_pool == has_features, (
            f"{case['case_id']}: gold 在池里={in_pool}，但 features 非 None={has_features}。"
            "两处必须同时表达同一状态。"
        )
        if in_pool:
            n_retrieved += 1
        else:
            n_unretrieved += 1

    # **两种状态都必须出现**，否则这条测试只验证了一半。
    # 实测 billing（仅 lexical）确有未召回的 case，所以这不是空要求。
    assert n_unretrieved > 0, "这批数据里没有'gold 未召回'的 case，后半个约束没被验到"
    assert n_retrieved > 0, "这批数据里没有'gold 已召回'的 case，前半个约束没被验到"
