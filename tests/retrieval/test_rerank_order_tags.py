"""两个新字段（`rerank_order_tags` / `pool_tag_meta`）必须自洽。

**为什么需要**：它们是"竞争集排名"唯一可复算的来源。
若它们与 `rank_after_rerank` 各说各话，竞争集排名就会变成第二个
"看起来对但测的不是它声称的东西"——这是本项目出现最多次的形态
（C4 缺陷 2/3/8，v2 的 F19b 第一版）。

这些测试用**已入库的结果文件**做断言，所以不跑网络也能验证。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
RESULT = ROOT / "results" / "v2-sample-threeway.json"


def _load() -> dict[str, object]:
    if not RESULT.exists():
        pytest.skip("结果文件缺失，先跑 evals.run_retrieval")
    return json.loads(RESULT.read_text(encoding="utf-8"))


def test_fields_exist() -> None:
    """两个字段必须都在，且非空。"""
    payload = _load()
    cases = payload["per_case"]  # type: ignore[index]

    assert cases
    for case in cases:
        if case.get("skipped"):
            continue
        assert "rerank_order_tags" in case, f"{case['case_id']} 缺 rerank_order_tags"
        assert "pool_tag_meta" in case, f"{case['case_id']} 缺 pool_tag_meta"
        assert case["rerank_order_tags"], f"{case['case_id']} 的 rerank_order_tags 为空"
        assert case["pool_tag_meta"], f"{case['case_id']} 的 pool_tag_meta 为空"


def test_rerank_order_matches_rank_after_rerank() -> None:
    """`rerank_order_tags` 里 gold 的下标必须等于 `rank_after_rerank`。

    这是"两处对同一件事的记录必须一致"的直接检查。
    """
    payload = _load()
    for case in payload["per_case"]:  # type: ignore[index]
        if case.get("skipped") or not case.get("has_gold"):
            continue
        tag = f"gold-{case['case_id']}"
        order = case["rerank_order_tags"]
        rank = case["rank_after_rerank"]

        if tag not in order:
            assert rank is None, f"{case['case_id']}: gold 不在顺序里但 rank={rank}"
            continue
        assert order.index(tag) + 1 == rank, (
            f"{case['case_id']}: 顺序里第 {order.index(tag) + 1}，"
            f"但 rank_after_rerank={rank}"
        )


def test_pool_tag_meta_covers_every_ranked_tag() -> None:
    """排序里出现的每个 tag 都必须在 `pool_tag_meta` 里有元数据。"""
    payload = _load()
    for case in payload["per_case"]:  # type: ignore[index]
        if case.get("skipped"):
            continue
        meta = case["pool_tag_meta"]
        for tag in case["rerank_order_tags"]:
            assert tag in meta, f"{case['case_id']}: tag {tag} 没有元数据"


def test_pool_tag_meta_has_only_subject_and_relation() -> None:
    """不得存 `condition`——竞争集判定用不上，且会让结果文件膨胀。

    20 个 subject × 每池 12 条 × 多一个字段 = 上万个小对象。
    """
    payload = _load()
    for case in payload["per_case"]:  # type: ignore[index]
        if case.get("skipped"):
            continue
        keys = {frozenset(v.keys()) for v in case["pool_tag_meta"].values()}
        assert keys == {frozenset({"subject", "relation"})}, (
            f"{case['case_id']}: 元数据字段不符：{keys}"
        )


def test_competing_set_rank_is_computable_and_bounded() -> None:
    """竞争集内名次必须 ≤ 竞争集容量。

    这是"两个口径"能被区分的核心断言：
    整池名次可以超过竞争集容量（q4 就是 6 > 4），
    而竞争集内名次不可能超过它。
    """
    payload = _load()
    for case in payload["per_case"]:  # type: ignore[index]
        if case.get("skipped") or not case.get("has_gold"):
            continue
        meta = case["pool_tag_meta"]
        order = case["rerank_order_tags"]
        tag = f"gold-{case['case_id']}"
        if tag not in meta or tag not in order:
            continue

        key = (meta[tag]["subject"], meta[tag]["relation"])
        same = [t for t in order if (meta[t]["subject"], meta[t]["relation"]) == key]
        comp_rank = same.index(tag) + 1

        assert comp_rank <= len(same), (
            f"{case['case_id']}: 竞争集内名次 {comp_rank} 超过容量 {len(same)}"
        )


def test_whole_pool_rank_can_exceed_competing_set() -> None:
    """**整池名次可以超过竞争集容量**——这正是两个口径不同的证据。

    若所有 case 都满足 `rank <= 竞争集容量`，说明整池里根本没有
    其他 relation 的干扰项，两个口径会退化成同一个。
    这条测试保护的是"这个区别仍然存在"。
    """
    payload = _load()
    exceeds = []
    for case in payload["per_case"]:  # type: ignore[index]
        if case.get("skipped") or not case.get("has_gold"):
            continue
        rank = case["rank_after_rerank"]
        if rank is None:
            continue
        meta = case["pool_tag_meta"]
        tag = f"gold-{case['case_id']}"
        if tag not in meta:
            continue
        key = (meta[tag]["subject"], meta[tag]["relation"])
        capacity = sum(
            1 for v in meta.values() if (v["subject"], v["relation"]) == key
        )
        if rank > capacity:
            exceeds.append((case["case_id"], rank, capacity))

    assert exceeds, (
        "没有任何 case 的整池名次超过竞争集容量——"
        "两个口径在这份数据上没有区别，分母争议失去对象"
    )
    assert ("ledger-q4", 6, 4) in exceeds
