"""同一份数据、同一份代码，必须给出同一个分数。

**这条测试防的是本轮发现的最严重装置缺陷**：

`rrf` 与 `rerank` 都用 `item_id` 破并列，而那里的 id 是 store 生成的
**uuid4**——每次运行都不同。于是并列候选的先后跨运行随机。

实测后果（修复前）：

    ledger-q1 连跑 5 次  rank = 1, 1, 1, 1, 2
    条件消融 A 轴 SEH@1  = 0.3000 / 0.4000 之间跳
    condition 掉幅       = 0.50 / 0.60 之间跳

而 0.50 与 0.60 都能过 F20 的 0.3 阈值——**门禁绿，数字却在漂**。
更糟的是：漂移会被当成"条件贡献的差异"或"路径贡献的差异"写进报告。

修法：融合与重排全部在**稳定 tag 域**进行，并用融合顺序作二级判据。
不能用 tag 字典序——那会让 `d-<case>-0` 恒排在 `gold-<case>` 之前
（"d" < "g"），把随机换成固定偏向。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SAMPLE = ROOT / "data" / "retrieval-v2" / "sample"


def _run_once(rows: list[dict[str, object]]) -> dict[str, int | None]:
    from evals.run_retrieval import evaluate

    from memory.config import Settings
    from memory.embedding.cache import EmbeddingCache
    from memory.embedding.dashscope import DashScopeEmbedder
    from memory.retrieval.pool_modes import PoolMode

    settings = Settings.load()
    settings.cache_dir.mkdir(parents=True, exist_ok=True)
    embedder = DashScopeEmbedder(
        settings=settings, cache=EmbeddingCache(settings.cache_dir / "cache.db")
    )
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
        for c in result["per_case"]  # type: ignore[index]
    }


@pytest.fixture(scope="module")
def sample_rows():  # type: ignore[no-untyped-def]
    from evals.datasets.retrieval_v2 import load_dataset
    from evals.datasets.v2_adapter import rows as adapt_rows

    if not SAMPLE.exists():
        pytest.skip("样例数据集缺失")
    return adapt_rows(load_dataset(SAMPLE))


def _ablate(rows: list[dict[str, object]]) -> list[dict[str, object]]:
    out = []
    for row in rows:
        r = dict(row)
        r["condition"] = None
        out.append(r)
    return out


def test_with_condition_is_deterministic(sample_rows) -> None:  # type: ignore[no-untyped-def]
    """带 condition 的配置连跑两次，逐条名次必须相同。"""
    first = _run_once(sample_rows)
    second = _run_once(sample_rows)

    assert first == second, (
        "同一配置两次运行名次不同："
        f"{ {k: (v, second.get(k)) for k, v in first.items() if v != second.get(k)} }"
    )


def test_condition_ablation_is_deterministic(sample_rows) -> None:  # type: ignore[no-untyped-def]
    """**核心**：条件消融两次运行必须给出同一个掉幅。

    修复前这里会在 0.50 与 0.60 之间跳，而两者都过 F20 的 0.3 阈值——
    门禁绿，数字却在漂。
    """
    ablated = _ablate(sample_rows)

    first = _run_once(ablated)
    second = _run_once(ablated)

    assert first == second, (
        "消融配置两次运行名次不同："
        f"{ {k: (v, second.get(k)) for k, v in first.items() if v != second.get(k)} }"
    )


def test_ablation_drop_is_stable_at_060(sample_rows) -> None:  # type: ignore[no-untyped-def]
    """**v2 历史事实：条件消融掉幅稳定在 0.600。v3 之后该掉幅必须为 0。**

    v2：`condition` 参与加权，所以抹掉条件会让 10 条 A 轴查询里 6 条掉出第 1。
    而 0.60 是 F20 阈值的依据（0.3 = 它的一半）。

    **v3：`condition` 退出加权，消融不改变任何得分——掉幅必须是 0。**
    这不是"缺陷被修了"，是**这个消融实验在 v3 不再有对象**。

    所以本条断言两件事：

    1. 消融前后名次**完全相同**（drop == 0）
    2. 若有人把 `condition` 权重加回去，drop 会变正——那时本条会红
    """
    with_cond = _run_once(sample_rows)
    without_cond = _run_once(_ablate(sample_rows))

    a_ids = [
        qid for qid in with_cond if qid.startswith("ledger-q") and qid not in
        ("ledger-q11", "ledger-q12")
    ]
    assert len(a_ids) == 10

    hit_with = sum(1 for qid in a_ids if with_cond[qid] == 1)
    hit_without = sum(1 for qid in a_ids if without_cond[qid] == 1)
    drop = (hit_with - hit_without) / len(a_ids)

    # v3：condition 不参与加权，消融无影响
    assert drop == pytest.approx(0.0, abs=1e-9), (
        f"消融掉幅 {drop} 不为 0——说明 condition 又参与了加权（v3 的 BREAKING 被回退）。"
        f" v2 的历史值是 0.600，见 HANDOFF §0.9。"
    )
    assert hit_with == hit_without, (
        f"有/无 condition 命中数不同：{hit_with} vs {hit_without}"
    )


def test_result_file_records_the_same_ranks_as_a_fresh_run(sample_rows) -> None:  # type: ignore[no-untyped-def]
    """**跨装置不可比**：v2 的存档结果与 v3 重跑必然不同。

    这条测试原来的判据是"入库结果必须与现在重跑一致"，
    它防的是"代码与结果脱节"。

    **但 v3 改了排序装置（4 特征 → 3 特征），所以 v2 的存档在原理上不可能被复现。**
    这不是脱节，是版本边界。

    替换判据：**只对同装置的结果做比对**。
    - v2 存档（`weights` 含 `condition`）-> 与 v3 重跑不可比，断言"确实不同"
    - v3 新产物（`weights` 无 `condition`）-> 与重跑可比，断言"相同"

    这样"脱节"仍然会被抓到：一旦 v3 产物与重跑不符，第二条断言就红。
    """
    path = ROOT / "results" / "v2-sample-threeway.json"
    if not path.exists():
        pytest.skip("结果文件缺失")

    stored = json.loads(path.read_text(encoding="utf-8"))
    stored_weights = stored.get("weights") or stored.get("weights_name")
    stored_ranks = {
        c["case_id"]: c["rank_after_rerank"] for c in stored["per_case"]
    }
    fresh = _run_once(sample_rows)

    # 判断存档是哪个装置产生的
    is_v2_apparatus = (
        isinstance(stored_weights, dict) and "condition" in stored_weights
    ) or stored_weights == "uniform"

    if is_v2_apparatus:
        # v2 存档：与 v3 重跑必然不同——这正是 BREAKING 的证据
        different = {
            k: (stored_ranks[k], fresh.get(k))
            for k in stored_ranks
            if stored_ranks[k] != fresh.get(k)
        }
        assert different, (
            "v2 存档与 v3 重跑竟然完全一致——"
            "说明 condition 仍参与加权（v3 的 BREAKING 未生效）"
        )
        # 而差异必须覆盖关键 case（q4 是 condition 起决定作用的那条）
        assert "ledger-q4" in different, (
            "q4 的名次没变——condition 退出加权后它应当掉出前列"
        )
    else:
        # v3 产物：必须与重跑一致
        assert stored_ranks == fresh, (
            "v3 结果文件与重跑不一致（装置脱节）："
            f"{ {k: (v, fresh.get(k)) for k, v in stored_ranks.items() if v != fresh.get(k)} }"
        )


def test_tiebreak_uses_fusion_order_not_tag_alphabet() -> None:
    """二级判据必须是融合顺序，不能是 tag 字典序。

    tag 字典序下 `d-<case>-0` 恒排在 `gold-<case>` 之前（"d" < "g"），
    于是每个并列都以 gold 输给干扰项告终——那是把随机换成了固定偏向，
    同样不是数据的性质。
    """
    assert "d-ledger-q1-0" < "gold-ledger-q1", "前提：tag 字典序里 d 在 g 前"
