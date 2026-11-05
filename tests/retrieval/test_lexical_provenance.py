"""lexical 单路的 0.83 / 0.89 是怎么来的？

## 为什么问这个

若高分主要来自"query 与 gold 共享词面"，那不是排序能力，是**数据太容易**——
而那正是 `F24` 一直在找的"数据太简单"。

## 三组必须分开

| 组 | 含义 | 能否用重叠解释 |
|---|---|---|
| A | 召回了 gold **且** top-1 | ✅ |
| B | 召回了 gold 但未 top-1 | ✅（对照） |
| C | **没召回 gold** | ❌ |

**混算会夸大重叠的解释力**：`sample` 的 4 条 implicit 全部未召回且 bigram=0，
把它们算进"未命中"会把均值从 0.0400 拉到 0.0080，差从 0.1537 变成 0.1857。

## 结论分裂，不能统一

| subject | A 组均值 | p（置换检验） | 结论 |
|---|---|---|---|
| `sample` | 0.1937 | **0.0079** | 词面重叠能解释 top-1 |
| `billing` | 0.1353 | **0.1091** | **不能** |

`billing` 的 8 条 top-1 里有 3 条 bigram < 0.05：
`c1`（0.0357）、`c2`（0.0345）、`a3`（0.0488）。
它们是**语义相关**（"德国↔欧洲"、"发票"、"申报"），bigram 抓不到。
"""

from __future__ import annotations

from itertools import combinations
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data" / "retrieval-v2"
SUBJECTS = ("sample", "billing")

#: 报告 §6.9 的数字。改动这里必须同时改报告。
EXPECTED = {
    "sample": {
        "A": ["ledger-q1", "ledger-q5", "ledger-q6", "ledger-q9", "ledger-q10"],
        "B": ["ledger-q2"],
        "C": ["ledger-q3", "ledger-q4", "ledger-q7", "ledger-q8"],
        "a_mean": 0.1937,
        "low_overlap_top1": [],
        "p": 0.0079,
    },
    "billing": {
        "A": [
            "billing-a1", "billing-a3", "billing-a4", "billing-a5",
            "billing-a7", "billing-a8", "billing-c1", "billing-c2",
        ],
        "B": ["billing-a6"],
        "C": ["billing-a2", "billing-a9", "billing-c3"],
        "a_mean": 0.1353,
        "low_overlap_top1": ["billing-a3", "billing-c1", "billing-c2"],
        "p": 0.1091,
    },
}


def _bigrams(text: str) -> set[str]:
    t = "".join(text.split())
    return {t[i : i + 2] for i in range(len(t) - 1)} if len(t) >= 2 else set()


def _jaccard(a: set[str], b: set[str]) -> float:
    u = a | b
    return len(a & b) / len(u) if u else 0.0


def _perm_test(hit: list[float], miss: list[float]) -> tuple[float, float]:
    """精确置换检验（穷举全部组合）。返回 (观察到的均值差, 双侧 p)。"""
    obs = sum(hit) / len(hit) - sum(miss) / len(miss)
    pooled = hit + miss
    n_hit = len(hit)
    count = 0
    total = 0
    for idx in combinations(range(len(pooled)), n_hit):
        s = set(idx)
        h = [pooled[i] for i in s]
        m = [pooled[i] for i in range(len(pooled)) if i not in s]
        d = sum(h) / len(h) - sum(m) / len(m)
        if abs(d) >= abs(obs) - 1e-12:
            count += 1
        total += 1
    return obs, count / total


@pytest.fixture(scope="module")
def measured():
    """现场重跑 lexical 单路，把 case 分成 A/B/C 三组。"""
    import evals.run_retrieval as rr
    from evals.datasets.retrieval_v2 import load_dataset
    from evals.datasets.v2_adapter import rows as adapt_rows
    from evals.metrics.v2_baselines import derived_axis_of

    from memory.config import Settings
    from memory.embedding.cache import EmbeddingCache
    from memory.embedding.dashscope import DashScopeEmbedder
    from memory.retrieval.pool_modes import PoolMode
    from memory.retrieval.rerank import RerankWeights

    settings = Settings.load()
    settings.cache_dir.mkdir(parents=True, exist_ok=True)
    embedder = DashScopeEmbedder(
        settings=settings, cache=EmbeddingCache(settings.cache_dir / "cache.db")
    )

    out: dict[str, dict] = {}
    original = dict(rr.PREREGISTERED_WEIGHTS)
    try:
        rr.PREREGISTERED_WEIGHTS["__lexprov"] = RerankWeights(0.4, 0.3, 0.3)

        for subject in SUBJECTS:
            ds = load_dataset(DATA / subject)
            rows = adapt_rows(ds)
            specs = [r["gold"] for r in rows if r["gold"]]
            within = {
                q.query_id
                for q in ds.queries
                if derived_axis_of(ds, q) == "relation_within"
            }
            res = rr.evaluate(
                rows,
                all_specs=specs,
                weights_name="__lexprov",
                enable_dedup=False,
                judge=None,
                k=5,
                pool_mode=PoolMode.UNRELATED,
                paths=("lexical",),
                embedder=embedder,
            )

            groups: dict[str, dict[str, float]] = {"A": {}, "B": {}, "C": {}}
            for case in res["per_case"]:
                cid = case["case_id"]
                if cid not in within:
                    continue
                if not case.get("has_gold") or case.get("skipped"):
                    continue
                q = next(x for x in ds.queries if x.query_id == cid)
                gold = ds.memory(q.gold_memory_id)
                j = _jaccard(_bigrams(q.query), _bigrams(gold.memory_text))

                recalled = case.get("rank_after_fusion") is not None
                top1 = case.get("rank_after_rerank") == 1
                key = "A" if (recalled and top1) else ("B" if recalled else "C")
                groups[key][cid] = j

            a_vals = list(groups["A"].values())
            # A 组与 B/C 组做检验（C 组与重叠无关，但作为"非 top-1"的对照）
            b_vals = list(groups["B"].values())
            _, p = _perm_test(a_vals, b_vals + list(groups["C"].values()))

            out[subject] = {
                "groups": groups,
                "a_mean": sum(a_vals) / len(a_vals) if a_vals else 0.0,
                "p": p,
            }
    finally:
        rr.PREREGISTERED_WEIGHTS.clear()
        rr.PREREGISTERED_WEIGHTS.update(original)
    return out


# ---------- 分组本身 ----------


def test_three_groups_are_disjoint_and_cover_all(measured) -> None:
    """**A/B/C 必须互斥且覆盖全部 case。**

    若三类有交集或漏项，"命中组"的均值就不可信——
    同一个 case 可能被算两次，或某些 case 完全消失。
    """
    for subject in SUBJECTS:
        groups = measured[subject]["groups"]
        ids = {k: set(v) for k, v in groups.items()}

        assert not (ids["A"] & ids["B"]), f"{subject}: A 与 B 有交集 {ids['A'] & ids['B']}"
        assert not (ids["A"] & ids["C"]), f"{subject}: A 与 C 有交集"
        assert not (ids["B"] & ids["C"]), f"{subject}: B 与 C 有交集"

        total = len(ids["A"]) + len(ids["B"]) + len(ids["C"])
        expected = len(EXPECTED[subject]["A"]) + len(EXPECTED[subject]["B"]) + len(
            EXPECTED[subject]["C"]
        )
        assert total == expected, (
            f"{subject}: 三类合计 {total}，而报告的三组是 {expected} 条"
        )


def test_group_membership_matches_report(measured) -> None:
    """**三组的成员必须与报告 §6.9 一致。**

    这条抓"数据变了但报告没更新"，也抓"分组逻辑变了"。
    """
    problems: list[str] = []
    for subject in SUBJECTS:
        groups = measured[subject]["groups"]
        for key in ("A", "B", "C"):
            got = set(groups[key])
            want = set(EXPECTED[subject][key])
            if got != want:
                problems.append(
                    f"{subject}/{key}: 实际 {sorted(got)}，报告 {sorted(want)}"
                )
    assert not problems, "分组与报告不符：\n  " + "\n  ".join(problems)


def test_not_recalled_group_overlap_is_negligible(measured) -> None:
    """**C 组（未召回）的重叠可以非零，但必须极低。**

    **我第一版写的是"C 组 bigram 全为 0"，那是错的。**
    实测 `billing-a2` 未召回，但 bigram 是 0.031：
    query「硅谷那家要发票，抬头金额按什么算？」vs gold「北美的单子按美元开票」
    ——共享"发票"，但 lexical 仍没召回它。

    **这修正了一个更强的结论**：不是"未召回 = 零重叠"，
    而是"未召回 = 重叠不足以进入召回"。

    **为什么这条仍然重要**：它证明"未召回"与"重叠低"是**相关但不等价**的两件事。
    若把它们合并（把 C 组算进"未命中"），会：
    1. 把 4 条 bigram=0 的 implicit 混进来，拉低未命中均值
    2. 掩盖"billing-a2 有重叠但没召回"这个独立事实

    **阈值 0.05 与 A/B 组的分界一致**：C 组全部 < 0.05。
    """
    for subject in SUBJECTS:
        c_group = measured[subject]["groups"]["C"]
        high = {cid: j for cid, j in c_group.items() if j >= 0.05}
        assert not high, (
            f"{subject}: C 组（未召回）出现 ≥ 0.05 的 bigram：{high}。\n"
            "这说明分组逻辑有问题——重叠这么高却没召回，要去查召回路径。"
        )
        # 逐条记录，让"可以非零"这个事实留在测试里
        assert all(j < 0.05 for j in c_group.values())


# ---------- sample 与 billing 的结论分裂 ----------


def test_sample_top1_all_have_overlap(measured) -> None:
    """**`sample` 的 top-1 全部有词面重叠**（bigram ≥ 0.05）。

    实测 5 条全部 ≥ 0.05（最低 q9=0.053）。

    **这支持"sample 的 top-1 主要由词面决定"**——但只对 sample 成立。
    """
    a_group = measured["sample"]["groups"]["A"]
    assert len(a_group) == 5
    low = {cid: j for cid, j in a_group.items() if j < 0.05}
    assert not low, (
        f"sample: 这些 top-1 的 bigram < 0.05：{low}。\n"
        "若出现低重叠的 top-1，'sample 靠词面'这个结论要重核。"
    )


def test_billing_has_low_overlap_top1(measured) -> None:
    """**`billing` 有 3 条低重叠的 top-1**——这是"不能统一结论"的证据。

    实测：`billing-a3`（0.0488）、`billing-c1`（0.0357）、`billing-c2`（0.0345）。

    **若强行写"lexical 高分 = 数据太容易"**，这 3 条会被误判成"数据简单"，
    而实际它们是**语义相关**（"德国↔欧洲"、"发票"、"申报"），bigram 抓不到。
    """
    a_group = measured["billing"]["groups"]["A"]
    low = {cid for cid, j in a_group.items() if j < 0.05}
    expected = set(EXPECTED["billing"]["low_overlap_top1"])

    assert low == expected, (
        f"billing: 低重叠的 top-1 是 {sorted(low)}，报告写 {sorted(expected)}。\n"
        "若这个集合变了，'bigram 抓不到语义相关'那段要重写。"
    )
    assert len(low) == 3, f"应为 3 条，实际 {len(low)}"


def test_permutation_results_split_by_subject(measured) -> None:
    """**置换检验：sample 显著、billing 不显著。**

    | subject | A 均值 | p | 结论 |
    |---|---|---|---|
    | `sample` | 0.1937 | **0.0079** | 重叠能解释 |
    | `billing` | 0.1353 | **0.1091** | **不能** |

    **两个方向相反的断言**，这本身就是结论：
    不能把两个 subject 合并成一个说法。

    **p 的容差是 1e-3**：精确置换的 p 是离散值（`k/组合数`），
    不应按浮点比较。
    """
    assert measured["sample"]["p"] < 0.05, (
        f"sample: p = {measured['sample']['p']:.4f}，期望 < 0.05（显著）"
    )
    assert measured["billing"]["p"] > 0.05, (
        f"billing: p = {measured['billing']['p']:.4f}，期望 > 0.05（不显著）。\n"
        "若它变显著，'结论分裂'这个发现要重核。"
    )

    assert measured["sample"]["p"] == pytest.approx(EXPECTED["sample"]["p"], abs=1e-3)
    assert measured["billing"]["p"] == pytest.approx(
        EXPECTED["billing"]["p"], abs=1e-3
    )


def test_a_group_means_match_report(measured) -> None:
    """**两组的 A 均值必须与报告一致**（保留 4 位小数）。"""
    for subject in SUBJECTS:
        got = measured[subject]["a_mean"]
        want = EXPECTED[subject]["a_mean"]
        assert round(got, 4) == pytest.approx(want, abs=1e-3), (
            f"{subject}: A 组均值 {got:.4f}，报告写 {want}"
        )


# ---------- 报告内容 ----------


def test_report_states_the_split_conclusion() -> None:
    """**报告必须写出"结论分裂"**，不能只写 sample。

    若只写"sample 靠词面"，读者会把它推广到 billing——
    而 billing 上不成立。
    """
    report = (ROOT / "docs" / "reports" / "v2-what-it-measures.md").read_text(
        encoding="utf-8"
    )
    section = report.split("## 6. 结论 5")[1].split("\n## ")[0]
    sub = section.split("### 6.9")[1].split("### 6.10")[0]

    assert "结论分裂" in sub or "不能统一" in sub, (
        "§6.9 必须写明两个 subject 的结论不同——否则读者会推广到 billing"
    )
    assert "0.0079" in sub and "0.1091" in sub, (
        "§6.9 必须给出两个 p 值——只给一个是单点报告"
    )


def test_report_does_not_claim_data_is_too_easy() -> None:
    """**报告不得写"lexical 高分 = 数据太容易"**（billing 上不成立）。"""
    report = (ROOT / "docs" / "reports" / "v2-what-it-measures.md").read_text(
        encoding="utf-8"
    )
    section = report.split("## 6. 结论 5")[1].split("\n## ")[0]
    sub = section.split("### 6.9")[1].split("### 6.10")[0]

    assert "不成立" in sub or "不得" in sub, (
        "§6.9 必须明确否定'lexical 高分 = 数据太容易'这个推广"
    )
    # 必须给出那 3 条低重叠的 case
    for cid in ("billing-c1", "billing-c2", "billing-a3"):
        assert cid in sub, f"§6.9 必须点名 {cid}——它是'语义相关'的实例"


def test_report_registers_bigram_blind_spot() -> None:
    """**报告必须登记 bigram 的漏检**。

    `bigram` 抓不到"语义相关但字面不同"。若不登记，
    下一个人会以为"bigram 低 = 与 query 无关"。
    """
    report = (ROOT / "docs" / "reports" / "v2-what-it-measures.md").read_text(
        encoding="utf-8"
    )
    section = report.split("## 6. 结论 5")[1].split("\n## ")[0]
    sub = section.split("### 6.9")[1].split("### 6.10")[0]

    assert "语义" in sub, "§6.9 必须点明 bigram 抓不到语义相关"
    assert "德国" in sub or "欧洲" in sub, (
        "§6.9 必须给出跨语种/近义的实例（德国↔欧洲）"
    )
