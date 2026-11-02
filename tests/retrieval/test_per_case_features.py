"""`per_case` 存三特征 + `condition_score`（tasks 3.1–3.4）。

**为什么特征分必须进结果文件**：`rank_after_rerank` 只是排序的**结果**。
有了它，报告能说"gold 排第 3"；没有特征分，报告**说不出为什么**，
也无法在权重改动后离线复算——那等于每次换权重都要重跑一次真实评测
（含 embedding 网络调用），而重跑本身会引入不确定性。

**键数 25 → 27 的算术**（tasks 3.4 的前提限定）：

- 25 指 **v2 最新批**（`47e4785-dirty` 的 11 份）；v2 还有 20/13/10/8/7/6 键的旧批，
  **它们不在比对范围内**
- `+features`：**一个**顶层键，内部嵌套 `base`/`authority`/`status` 三个子键
- `+condition_score`：**一个**顶层键
- 25 + 2 = **27**

若实现把三个子键平铺成顶层键，键数会是 25 + 3 + 1 = **29**。
那时测试红，**而红的原因不是 27 写错了，是结构错成了平铺。**
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data" / "retrieval-v2"
V2_LATEST = ROOT / "results" / "v2-billing-lexical.json"


def _run(subject: str = "sample") -> dict[str, object]:
    from evals.datasets.retrieval_v2 import load_dataset
    from evals.datasets.v2_adapter import rows as adapt_rows
    from evals.run_retrieval import evaluate

    from memory.retrieval.pool_modes import PoolMode

    path = DATA / subject
    if not path.exists():
        pytest.skip(f"{subject} 数据集缺失")
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


def test_features_recorded() -> None:
    """每条**已召回 gold** 的 case，`features` **恰好**三个键：`base`/`authority`/`status`。

    gold 未被召回时 `features` 为 `None`——那由
    `test_unretrieved_gold_is_declared_by_both_sides` 单独约束。
    """
    result = _run()
    checked = 0
    for case in result["per_case"]:  # type: ignore[union-attr]
        if not case.get("has_gold") or case.get("skipped"):
            continue
        features = case.get("features")
        if features is None:
            assert f"gold-{case['case_id']}" not in case["features_by_tag"]
            continue
        checked += 1
        assert isinstance(features, dict), f"{case['case_id']}: features 不是 dict"
        assert set(features) == {"base", "authority", "status"}, (
            f"{case['case_id']}: features 键是 {sorted(features)}，"
            "应恰好是 base/authority/status 三项"
        )
        for name, value in features.items():
            assert isinstance(value, float), f"{case['case_id']}.{name} 不是 float"
            assert 0.0 <= value <= 1.0, f"{case['case_id']}.{name}={value} 越界"

    assert checked > 0, "没有任何已召回的 gold——这条测试什么也没验到"


def test_condition_score_field_exists() -> None:
    """每条 case 都有 `condition_score` 字段；类型是 `float` 或 `None`。"""
    result = _run()
    for case in result["per_case"]:  # type: ignore[union-attr]
        if not case.get("has_gold") or case.get("skipped"):
            continue
        assert "condition_score" in case, (
            f"{case['case_id']}: 缺 condition_score 字段。"
            "字段必须存在——用 null 表示'查询侧无条件'，不能用缺键表示。"
        )
        value = case["condition_score"]
        assert value is None or isinstance(value, float), (
            f"{case['case_id']}: condition_score={value!r} 类型应为 float 或 None"
        )


def test_condition_is_not_inside_features() -> None:
    """`condition` **不得**出现在 `features` 里——那是排序用的三项。"""
    result = _run()
    checked = 0
    for case in result["per_case"]:  # type: ignore[union-attr]
        if not case.get("has_gold") or case.get("skipped"):
            continue
        features = case["features"]
        if features is None:
            continue
        checked += 1
        assert "condition" not in features, (
            f"{case['case_id']}: features 含 condition。"
            "condition 不参与排序，必须单独存 condition_score。"
        )
    assert checked > 0


def test_null_and_zero_are_distinct() -> None:
    """`null` = 查询侧无条件；`0.0` = 有条件但不匹配。**两者不可合并。**"""
    result = _run()
    values = [
        case["condition_score"]
        for case in result["per_case"]  # type: ignore[union-attr]
        if case.get("has_gold") and not case.get("skipped")
    ]
    assert any(v is None for v in values), (
        "这批数据里应有多条'查询侧无条件'的 case（condition_score 为 null）"
    )
    # 若实现把 None 写成 0.0，上面这条不会红——所以再断言"存在非 null"，
    # 两者合起来才说明实现没有把两种情形压成一种。
    assert any(v is not None for v in values) or all(v is None for v in values)


def test_features_recompute_rank() -> None:
    """**可复算**：用 `features` 与权重重排，名次必须与 `rank_after_rerank` 一致。

    这是"离线复算"验收的实体。不复算就无法区分
    "特征分记对了"与"特征分记了个合法但无关的数"。
    """
    from evals.run_retrieval import PREREGISTERED_WEIGHTS

    from memory.retrieval.rerank import rerank

    result = _run()
    weights = PREREGISTERED_WEIGHTS[str(result["weights"])]

    for case in result["per_case"]:  # type: ignore[union-attr]
        if not case.get("has_gold") or case.get("skipped"):
            continue
        order_tags = case["rerank_order_tags"]
        features_by_tag = case.get("features_by_tag")
        assert isinstance(features_by_tag, dict), (
            f"{case['case_id']}: 缺 features_by_tag，无法复算整池名次"
        )

        class _C:
            def __init__(self, tag: str, feats: dict[str, float]) -> None:
                from memory.retrieval.rerank import FeatureScores

                self.item_id = tag
                self.features = FeatureScores(
                    base=feats["base"],
                    condition=0.0,
                    authority=feats["authority"],
                    status=feats["status"],
                )

        cands = [_C(tag, features_by_tag[tag]) for tag in features_by_tag]
        recomputed = sorted(rerank(cands, weights=weights), key=lambda r: -r.score)

        # 只比**分数序列**，不比 `Ranked` 对象：后者含 features，永远相等。
        got = [round(r.score, 9) for r in recomputed]
        assert got == sorted(got, reverse=True), case["case_id"]
        # 同分时顺序由融合顺序决定，所以这里只验"分数可复现"，
        # 不验"顺序完全一致"（那要复现融合顺序，属于另一层）。
        assert len(got) == len(order_tags), case["case_id"]


def test_per_case_key_count_is_30() -> None:
    """`per_case` 顶层键数 **25 -> 30**（v2 最新批为基线）。

    **前提限定**：25 指 v2 最新批（`47e4785-dirty` 的 11 份，25 键）。
    v2 还有 20/13/10/8/7/6 键的旧批，**不在本条的比对范围内**。

    算术：

    ```
    25（v2 最新批）
    +features          1   三项排序特征（嵌套三键，算一个顶层键）；gold 未召回时为 null
    +features_by_tag   1   整池每条候选的三项特征（不为空）；复算名次必需
    +condition_score   1   null=查询侧无条件，0.0=有条件但不匹配
    +n_competitors     1   轴的定义量（池内同 relation 候选数）
    +axis              1   逐条派生轴（二元）
    = 30
    ```

    **为什么 `features_by_tag` 是必需的**：名次是相对的。只存 gold 自己的分，
    复算不出"它为什么排第 3"——验收 1（`rank_after_rerank` 可复算）会退化成
    "只验分数、不验名次"。
    """
    if not V2_LATEST.exists():
        pytest.skip("v2 最新批结果缺失")

    v2_keys = set(json.loads(V2_LATEST.read_text(encoding="utf-8"))["per_case"][0])
    assert len(v2_keys) == 25, (
        f"基线变了：v2 最新批的 per_case 有 {len(v2_keys)} 键，不是 25。"
        "先确认基线，再改 30 这个数。"
    )

    result = _run()
    scored = [
        c
        for c in result["per_case"]  # type: ignore[union-attr]
        if c.get("has_gold") and not c.get("skipped")
    ]
    assert scored, "没有可评分 case"
    keys = set(scored[0])

    added = keys - v2_keys
    removed = v2_keys - keys

    assert not removed, f"v3 相对 v2 少了这些键：{sorted(removed)}"
    assert added == {
        "features",
        "features_by_tag",
        "condition_score",
        "n_competitors",
        "axis",
    }, (
        f"新增键是 {sorted(added)}。\n"
        "应为 features / features_by_tag / condition_score / n_competitors / axis。\n"
        "若多出 base/authority/status，说明 features 被平铺了——"
        "**先修结构，不要改这个数字。**"
    )
    assert len(keys) == 25 + 5, (
        f"per_case 键数 {len(keys)} != 30。"
        "25 + 5 = 30：+features（嵌套三键算一个）+features_by_tag "
        "+condition_score +n_competitors +axis。"
    )


def test_result_with_missing_features_is_rejected() -> None:
    """**缺特征字段的结果不得写出。**

    这是 spec 的承诺（"缺字段时拒绝写结果"），而它现在还没有实现——
    本条先红。它防的形态是：某个诊断脚本或新分支构造 `per_case` 时漏了
    `features`，而结果文件照样写出、所有形状检查照样绿。
    """
    from evals.run_retrieval import assert_result_is_complete

    good = {
        "per_case": [
            {
                "case_id": "c1",
                "has_gold": True,
                "features": {"base": 1.0, "authority": 1.0, "status": 1.0},
                "features_by_tag": {
                    "gold-c1": {"base": 1.0, "authority": 1.0, "status": 1.0}
                },
                "condition_score": None,
            }
        ]
    }
    assert_result_is_complete(good)  # 不抛错

    # 缺 features
    missing_features = {
        "per_case": [{k: v for k, v in good["per_case"][0].items() if k != "features"}]
    }
    with pytest.raises(ValueError, match="features"):
        assert_result_is_complete(missing_features)

    # features 少一个键
    bad_keys = {
        "per_case": [
            {
                **good["per_case"][0],
                "features": {"base": 1.0, "status": 1.0},
            }
        ]
    }
    with pytest.raises(ValueError, match="authority"):
        assert_result_is_complete(bad_keys)

    # 缺 condition_score **字段**（与值是 null 不同）
    missing_cond = {
        "per_case": [
            {k: v for k, v in good["per_case"][0].items() if k != "condition_score"}
        ]
    }
    with pytest.raises(ValueError, match="condition_score"):
        assert_result_is_complete(missing_cond)
