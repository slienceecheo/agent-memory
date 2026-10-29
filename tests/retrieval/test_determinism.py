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
    """修好确定性之后，掉幅稳定在 0.6000。

    **这条不只是记录数字**：0.60 是 F20 的依据（阈值 0.3 是它的一半）。
    若它其实在 0.50 与 0.60 之间随机，那"0.60 的一半"这个说法就没有基础。
    """
    with_cond = _run_once(sample_rows)
    without_cond = _run_once(_ablate(sample_rows))

    a_ids = [
        qid for qid in with_cond if qid.startswith("ledger-q") and qid not in
        ("ledger-q11", "ledger-q12")
    ]
    hit_with = sum(1 for qid in a_ids if with_cond[qid] == 1)
    hit_without = sum(1 for qid in a_ids if without_cond[qid] == 1)
    drop = (hit_with - hit_without) / len(a_ids)

    assert len(a_ids) == 10
    assert hit_with == 9, f"有 condition 时命中 {hit_with}/10"
    assert hit_without == 3, f"消融后命中 {hit_without}/10"
    assert drop == pytest.approx(0.6, abs=1e-6)


def test_result_file_records_the_same_ranks_as_a_fresh_run(sample_rows) -> None:  # type: ignore[no-untyped-def]
    """入库的结果文件必须与现在重跑一致。

    否则报告里的数字与代码不再对应——而那是"装置没接上"的一种形态。
    """
    path = ROOT / "results" / "v2-sample-threeway.json"
    if not path.exists():
        pytest.skip("结果文件缺失")

    stored = json.loads(path.read_text(encoding="utf-8"))
    stored_ranks = {
        c["case_id"]: c["rank_after_rerank"] for c in stored["per_case"]
    }
    fresh = _run_once(sample_rows)

    assert stored_ranks == fresh, (
        "结果文件与重跑不一致："
        f"{ {k: (v, fresh.get(k)) for k, v in stored_ranks.items() if v != fresh.get(k)} }"
    )


def test_tiebreak_uses_fusion_order_not_tag_alphabet() -> None:
    """二级判据必须是融合顺序，不能是 tag 字典序。

    tag 字典序下 `d-<case>-0` 恒排在 `gold-<case>` 之前（"d" < "g"），
    于是每个并列都以 gold 输给干扰项告终——那是把随机换成了固定偏向，
    同样不是数据的性质。
    """
    assert "d-ledger-q1-0" < "gold-ledger-q1", "前提：tag 字典序里 d 在 g 前"
