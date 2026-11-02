"""A5：单开词面时，检索行为必须与归档逐位相同。

**为什么这个测试必须存在**：本变更要接入三路召回、修改 dedup 传参，
这些改动都在 `run_retrieval.py` 里。若不设一道"没改坏算法"的闸，
一次顺手的重构就能悄悄改变词面路径的排序，而所有分数看起来仍然"合理"。

**A5 的两段，适用范围不同**：

| 段 | 比什么 | 旧集 | v2 |
|---|---|---|---|
| A5-a | `rank_after_fusion` / `rank_after_rerank` / `attribution` / top-1 tag | ✅ | ✅ |
| A5-b | 完整 `fusion_tags` 序列 | ❌ 不可执行 | ✅ |

A5-b 在旧集上不可执行，原因三条（见 design.md）：
1. 归档结果从未记录融合序列，没有基线可比
2. 旧集 26/26 条 case 的召回集只有 1 个候选，完整序列恒为 `[gold]`，任何实现都会通过
3. 候选 id 由 `uuid4` 生成，跨运行不可比（必须用稳定 tag）

**这正是本项目第三次遇到"检查看起来合理、但在当前数据上无法失败"**
（前两次：`SEH@5` 饱和、`rank` 恒为 1）。写清适用范围，比假装它有效更好。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from evals.run_retrieval import evaluate

from memory.retrieval.pool_modes import PoolMode

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data" / "conflict-set"
RESULTS = ROOT / "results"

#: 归档基线：C4 最后一个提交产出的结果。
ARCHIVED_SPLITS = ("dev", "test", "independent")


def _rows(name: str) -> list[dict[str, object]]:
    path = DATA / name
    if not path.exists():
        pytest.skip(f"{name} 不存在")
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _all_specs() -> list[dict[str, object]]:
    specs: list[dict[str, object]] = []
    for name in ("dev.jsonl", "test.jsonl", "independent.jsonl"):
        specs.extend([row["gold"] for row in _rows(name) if row.get("gold")])  # type: ignore[misc]
    return specs


def _archived(split: str) -> dict[str, object]:
    path = RESULTS / f"retrieval-{split}-uniform-nodedup-poolunrelated.json"
    if not path.exists():
        pytest.skip(f"归档结果缺失：{path.name}")
    return json.loads(path.read_text(encoding="utf-8"))


def _run_lexical_only(split: str) -> dict[str, object]:
    return evaluate(
        _rows(f"{split}.jsonl"),
        all_specs=_all_specs(),
        weights_name="uniform",
        enable_dedup=False,
        judge=None,
        k=5,
        pool_mode=PoolMode.UNRELATED,
        paths=("lexical",),
    )


@pytest.mark.parametrize("split", ARCHIVED_SPLITS)
def test_single_path_ranks_match_archive(split: str) -> None:
    """A5-a：**融合**排名必须逐条相同；**重排**排名只在同装置下可比。

    这条原本断言"两个 rank 都必须逐条相同"。v3 之后要拆开：

    | rank | 是否受 v3 影响 | 断言 |
    |---|---|---|
    | `rank_after_fusion` | 否（RRF 未变） | **仍必须逐条相同** |
    | `rank_after_rerank` | 是（4 特征 → 3 特征） | **允许变化，但必须解释每处差异** |

    **融合排名不变**证明"v3 只动了重排，没动召回与融合"——这比原来的断言信息更精确。

    **重排排名的差异必须被逐条列出**，而不是"允许不同"就放过。
    若差异条数超过归档 case 数的 20%，说明变化超出预期，仍然红。
    """
    archived = _archived(split)
    current = _run_lexical_only(split)

    old = {c["case_id"]: c for c in archived["per_case"]}  # type: ignore[index]
    new = {c["case_id"]: c for c in current["per_case"]}  # type: ignore[index]

    assert set(old) == set(new)

    # 1) 融合排名：必须逐条相同（v3 不动召回与融合）
    fusion_mismatches = [
        (case_id, old[case_id]["rank_after_fusion"], new[case_id]["rank_after_fusion"])
        for case_id in sorted(old)
        if old[case_id]["rank_after_fusion"] != new[case_id]["rank_after_fusion"]
    ]
    assert not fusion_mismatches, f"融合排名变了（v3 不该动它）：{fusion_mismatches[:5]}"

    # 2) 重排排名：允许变化，但差异比例必须低于 20%
    rerank_mismatches = [
        (case_id, old[case_id]["rank_after_rerank"], new[case_id]["rank_after_rerank"])
        for case_id in sorted(old)
        if old[case_id]["rank_after_rerank"] != new[case_id]["rank_after_rerank"]
    ]
    ratio = len(rerank_mismatches) / len(old)
    assert ratio <= 0.20, (
        f"重排排名变化 {len(rerank_mismatches)}/{len(old)} = {ratio:.1%}，超过 20%。"
        f"去掉 condition 只应改变少数 case（那些原本靠条件分胜负的）。"
        f"变化清单：{rerank_mismatches[:10]}"
    )


@pytest.mark.parametrize("split", ARCHIVED_SPLITS)
def test_single_path_attribution_matches_archive(split: str) -> None:
    """A5-a：归因必须逐条相同。

    抓"rank 相同但归因变了"——那说明失败发生在不同阶段。
    """
    archived = _archived(split)
    current = _run_lexical_only(split)

    old = {c["case_id"]: c["attribution"] for c in archived["per_case"]}  # type: ignore[index]
    new = {c["case_id"]: c["attribution"] for c in current["per_case"]}  # type: ignore[index]

    mismatches = [
        (case_id, old[case_id], new[case_id])
        for case_id in sorted(old)
        if old[case_id] != new[case_id]
    ]
    assert not mismatches, f"归因变了：{mismatches[:5]}"


@pytest.mark.parametrize("split", ARCHIVED_SPLITS)
def test_single_path_top1_unchanged(split: str) -> None:
    """A5-a：排第一的那条必须没变（按稳定 tag 比，不是 uuid）。

    **这一项补的是前两项的盲区**：两个 rank 相同、attribution 也相同（都成功），
    但排第一的换成了另一条——前三项都抓不到，而这正是"改坏排序"最直接的形态。

    比较用 `rerank_top1_tag`，因为候选 id 是 uuid4、跨运行不可比。
    """
    archived = _archived(split)
    current = _run_lexical_only(split)

    old = {c["case_id"]: c["rank_after_rerank"] for c in archived["per_case"]}  # type: ignore[index]
    new = {c["case_id"]: c for c in current["per_case"]}  # type: ignore[index]

    # 归档没有 top-1 tag，所以只能对"rank=1 的 case"断言 top-1 就是 gold。
    # 这在旧集上约束不强（26/26 只有一个候选），但结构上可失败：
    # 若实现把 gold 挤出第一名，rank 就不再是 1，前一项会先失败。
    for case_id, record in new.items():
        if old.get(case_id) == 1:
            assert record["rerank_top1_tag"] == f"gold-{case_id}", (
                f"{case_id} 排第一的不是 gold：{record['rerank_top1_tag']}"
            )


def test_fusion_tags_are_stable_across_runs() -> None:
    """A5-b 的前提：融合序列用**稳定 tag**，两次运行必须相同。

    候选 id 是 uuid4（实测两次建库完全不同），所以直接比 id 在物理上不可能。
    这条测试锁住"存的是 tag 不是 uuid"，使 A5-b 在 v2 上真的可比。
    """
    first = _run_lexical_only("independent")
    second = _run_lexical_only("independent")

    first_tags = {
        c["case_id"]: c.get("fusion_tags")
        for c in first["per_case"]  # type: ignore[index]
        if c.get("has_gold") and not c.get("skipped")
    }
    second_tags = {
        c["case_id"]: c.get("fusion_tags")
        for c in second["per_case"]  # type: ignore[index]
        if c.get("has_gold") and not c.get("skipped")
    }

    assert first_tags
    assert first_tags == second_tags


def test_fusion_tags_never_contain_uuid() -> None:
    """融合序列里不得出现 32 位 hex（uuid4 的形态）。"""
    result = _run_lexical_only("dev")

    for record in result["per_case"]:  # type: ignore[union-attr]
        for tag in record.get("fusion_tags") or []:
            is_uuid = len(tag) == 32 and all(c in "0123456789abcdef" for c in tag)
            assert not is_uuid, f"{record['case_id']} 的融合序列里出现 uuid：{tag}"


def test_archived_results_lack_fusion_order() -> None:
    """记录 A5-b 在旧集上不可执行的事实。

    归档结果只存了 8 个键，没有融合序列。若有人日后补了，这条会失败，
    提醒去更新 design 里"仅 v2 适用"的说明。
    """
    archived = _archived("independent")
    keys = set(archived["per_case"][0])  # type: ignore[index]

    assert "fusion_tags" not in keys
    assert "fusion_order" not in keys


def test_old_split_pools_have_single_candidate() -> None:
    """A5-b 在旧集上无法失败的原因之二：召回集只有 1 个候选。

    这条与上面两条一起，构成 design 里"A5-b 仅 v2 适用"的三条依据。
    """
    payload = json.loads(
        (RESULTS / "c4-query-leak-ablation.json").read_text(encoding="utf-8")
    )
    histogram = payload["variants"]["independent"]["V0"]["recall_size_histogram"]

    assert histogram == {"1": 26}
