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
#:
#: **`p` 的正确值来自 `A vs B` 口径（对照组只含 B）**。
#: 上一版写的是 0.0079 / 0.1091，那两个数来自 `A vs (B+C)`——
#: C 组（未召回，bigram 全 0）混进了对照组，把 p 压低了。
EXPECTED = {
    "sample": {
        "A": ["ledger-q1", "ledger-q5", "ledger-q6", "ledger-q9", "ledger-q10"],
        "B": ["ledger-q2"],
        "C": ["ledger-q3", "ledger-q4", "ledger-q7", "ledger-q8"],
        "a_mean": 0.1937,
        # 空间 = 1 的两条：top-1 必然，不是排序能力
        "space1_top1": ["ledger-q9", "ledger-q10"],
        "low_overlap_top1": [],
        "p": 0.3333,
        "p_a1": 0.5000,
    },
    "billing": {
        "A": [
            "billing-a1", "billing-a3", "billing-a4", "billing-a5",
            "billing-a7", "billing-a8", "billing-c1", "billing-c2",
        ],
        "B": ["billing-a6"],
        "C": ["billing-a2", "billing-a9", "billing-c3"],
        "a_mean": 0.1353,
        "space1_top1": ["billing-a5", "billing-a8", "billing-c2"],
        # **只保留空间 >= 2 的两条**：c2 空间 = 1，它命中是因为没得选。
        # a3 共享的是「抬头」（字面命中），不是"德国↔欧洲"。
        "low_overlap_top1": ["billing-a3", "billing-c1"],
        "p": 0.7778,
        "p_a1": 1.0000,
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
        rr.PREREGISTERED_WEIGHTS["__lexprov"] = RerankWeights(base=0.4, authority=0.3, cosine=0.3)

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
            space: dict[str, int] = {}
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
                # **排序空间**：进入融合的候选数。
                # 它不是池大小——lexical 只返回 1–4 条。
                space[cid] = len(case.get("fusion_tags") or [])

            a_vals = list(groups["A"].values())
            b_vals = list(groups["B"].values())
            # **对照组只含 B**：C 组（未召回，bigram 全 0）与重叠无关，
            # 混进来会把对照均值压到 0.0080，p 从 0.3333 掉到 0.0079。
            #
            # 上一版写的是 `b_vals + list(groups["C"].values())`，而紧邻的注释
            # 却写着"C 组与重叠无关，单独报"——**注释与实现不符**。
            _, p = _perm_test(a_vals, b_vals)

            # A1：A 组里排序空间 >= 2 的部分（真有选择）。
            # 空间 = 1 意味着只有 gold 进了融合，top-1 必然。
            a1_vals = [groups["A"][cid] for cid in groups["A"] if space.get(cid, 0) >= 2]
            _, p_a1 = _perm_test(a1_vals, b_vals) if a1_vals and b_vals else (0.0, 1.0)

            recalled_vals = a_vals + b_vals
            random_by_space = (
                sum(1 / space[cid] for cid in groups["A"] | groups["B"] if space.get(cid))
                / len(recalled_vals)
                if recalled_vals
                else 0.0
            )

            out[subject] = {
                "groups": groups,
                "space": space,
                "a_mean": sum(a_vals) / len(a_vals) if a_vals else 0.0,
                "a1": a1_vals,
                "p": p,
                "p_a1": p_a1,
                "a1_hit": len(a1_vals),
                "b_n": len(b_vals),
                "random_by_space": random_by_space,
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


def test_billing_low_overlap_top1_is_explained_by_space(measured) -> None:
    """**`billing` 的 3 条低重叠 top-1，全部由排序空间解释，不是"语义能力"。**

    | case | bigram | 空间 | 机制 |
    |---|---|---|---|
    | `billing-c1` | 0.0357 | 2 | 二选一，靠「发票」 |
    | `billing-a3` | 0.0488 | 2 | 二选一，靠「**抬头**」 |
    | `billing-c2` | 0.0345 | **1** | **无竞争** |

    **上一版把 `c2` 算作"语义命中"是错的**：它空间 = 1，没有竞争对手。
    **上一版把 `a3` 说成"德国↔欧洲"也是错的**：共享 bigram 是「抬头」，
    而 query 里确有"抬头"二字。

    **所以这条断言的是"机制"，不是"能力"**：
    低重叠能 top-1，不是因为 lexical 懂语义，而是因为候选太少。
    """
    a_group = measured["billing"]["groups"]["A"]
    space = measured["billing"]["space"]

    low = {cid for cid, j in a_group.items() if j < 0.05}
    expected_low = {"billing-a3", "billing-c1", "billing-c2"}
    assert low == expected_low, (
        f"billing: 低重叠的 top-1 是 {sorted(low)}，报告写 {sorted(expected_low)}"
    )

    # 空间分布：1 条无竞争，2 条二选一
    space1 = {cid for cid in low if space.get(cid) == 1}
    space2 = {cid for cid in low if space.get(cid) == 2}
    assert space1 == {"billing-c2"}, (
        f"空间=1 的低重叠 top-1 应是 billing-c2，实际 {sorted(space1)}。\n"
        "若 c2 的空间不再是 1，'无竞争'这个解释要重核。"
    )
    assert space2 == {"billing-a3", "billing-c1"}, (
        f"空间=2 的低重叠 top-1 应是 a3/c1，实际 {sorted(space2)}"
    )

    # 没有任何一条空间 >= 3 —— 全是"候选极少"的情况
    high_space = {cid for cid in low if space.get(cid, 0) >= 3}
    assert not high_space, (
        f"这些低重叠 top-1 的排序空间 >= 3：{high_space}。\n"
        "若出现，说明 lexical 在多个候选里选中了低重叠的那条——"
        "那才可能是'语义能力'，需要重新解释。"
    )


def test_permutation_results_are_not_significant(measured) -> None:
    """**两个 subject 都不显著——没有"结论分裂"。**

    | subject | 对照 | 组合数 | 均值差 | p |
    |---|---|---|---|---|
    | `sample` | A vs B | 6 | +0.1537 | **0.3333** |
    | `billing` | A vs B | 9 | −0.0210 | **0.7778** |

    **上一版写的是 `sample p=0.0079 显著`，那个数是错的**：
    对照组把 C 组（未召回，bigram 全 0）混了进去。

    **断言具体值而不是方向**：只写 `p > 0.05` 时，`p = 0.99` 也会通过——
    而它与 `p = 0.06` 是两件不同的事。

    **为什么精确 p 可断言**：置换检验是精确检验（穷举全部组合），
    `p = k / 组合数` 是离散确定的，不依赖随机种子。

    **这也是发现那个 bug 的路径**：`sample` 只有 `C(6,5)=6` 种组合，
    可能的 p 值只有 `1/6`、`2/6`… 这些离散值——**0.0079 根本不在可能取值里**。
    它来自 `C(10,5)=252`，也就是 C 组混入后的组合数。
    """
    for subject in SUBJECTS:
        got = measured[subject]["p"]
        want = EXPECTED[subject]["p"]
        assert got == pytest.approx(want, abs=1e-3), (
            f"{subject}: p = {got:.4f}，期望 {want}。\n"
            "若这个是 0.0079 那种量级，检查组是否又把未召回的 case 混进了对照组。"
        )
        assert got > 0.05, f"{subject}: p = {got:.4f}，应为不显著"


def test_a1_vs_b_permutation_also_not_significant(measured) -> None:
    """**剔除必然命中后（A1 vs B），更不显著。**

    | subject | A1 n | B n | 组合数 | p |
    |---|---|---|---|---|
    | `sample` | 3 | 1 | 4 | **0.5000** |
    | `billing` | 5 | 1 | 6 | **1.0000** |

    **组合数极小（4 和 6）**，所以 p 值只能取几个离散值。
    这不是"检验不可靠"，而是**样本量本身不足以下结论**——
    而那正是要报告的结论。
    """
    for subject in SUBJECTS:
        got = measured[subject]["p_a1"]
        want = EXPECTED[subject]["p_a1"]
        assert got == pytest.approx(want, abs=1e-3), (
            f"{subject}: A1 vs B 的 p = {got:.4f}，期望 {want}"
        )


def test_space_one_top1_is_inevitable(measured) -> None:
    """**排序空间 = 1 的 top-1 是必然命中**，不是排序能力。

    实测：

    | subject | 空间=1 且 top-1 |
    |---|---|
    | `sample` | `ledger-q9`、`ledger-q10` |
    | `billing` | `billing-a5`、`billing-a8`、`billing-c2` |

    **空间 = 1 意味着只有 gold 进了融合**——池里其他候选根本没被 lexical 召回，
    所以"排第 1"不涉及任何选择。

    **这条同时验证两件事**：
    1. 这些 case 的空间确实是 1
    2. 它们确实 top-1（若空间=1 却没 top-1，说明分组逻辑有问题）
    """
    for subject in SUBJECTS:
        groups = measured[subject]["groups"]
        space = measured[subject]["space"]
        expected = set(EXPECTED[subject]["space1_top1"])

        actual = {cid for cid in groups["A"] if space.get(cid) == 1}
        assert actual == expected, (
            f"{subject}: 空间=1 且 top-1 的是 {sorted(actual)}，"
            f"报告写 {sorted(expected)}"
        )

        for cid in actual:
            assert space[cid] == 1, f"{cid}: 空间应为 1，实际 {space[cid]}"


def test_random_baseline_uses_sort_space_not_pool(measured) -> None:
    """**随机基线必须按 `1/排序空间` 算，不是 `1/池大小`。**

    | subject | 池大小 | 排序空间 | 1/池 | **1/空间** |
    |---|---|---|---|---|
    | `sample` | 12–14 | 0–2 | 0.0833 | **0.6667** |
    | `billing` | 9 | 0–4 | 0.1111 | **0.6111** |

    **用 1/池会把随机基线低估 8 倍**，于是"lexical 0.83 vs 随机 0.08"
    看起来增益 +0.75，而实际是 **+0.17**。
    """
    for subject, want in (("sample", 0.6667), ("billing", 0.6111)):
        got = measured[subject]["random_by_space"]
        assert got == pytest.approx(want, abs=1e-3), (
            f"{subject}: 按 1/空间 的随机基线 = {got:.4f}，期望 {want}。\n"
            "若这个数是 0.08 那种量级，说明用的是 1/池大小。"
        )
        assert got > 0.5, (
            f"{subject}: 随机基线 {got:.4f} 太小——"
            "排序空间只有 1–4 条，随机 top-1 概率不可能只有 8%"
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


def test_report_states_no_split() -> None:
    """**报告必须写"都不显著"**，不能说"结论分裂"。

    上一版写的是"结论分裂：`sample` 可解释、`billing` 不可"。
    **修正后两个都不显著，没有分裂。**

    若不改这句，读者会带着一个已被推翻的结论走。
    """
    report = (ROOT / "docs" / "reports" / "v2-what-it-measures.md").read_text(
        encoding="utf-8"
    )
    section = report.split("## 6. 结论 5")[1].split("\n## ")[0]
    sub = section.split("### 6.9 lexical 的 0.83 / 0.89 是怎么来的")[1].split("### 6.10")[0]

    assert "都不显著" in sub, (
        "§6.9 必须写明两个 subject 都不显著——否则读者会带着"
        "「结论分裂」那个已被推翻的结论走"
    )
    assert "0.3333" in sub and "0.7778" in sub, (
        "§6.9 必须给出两个正确的 p 值——只给一个是单点报告"
    )


def test_report_keeps_the_correction_notice() -> None:
    """**报告必须保留订正段**，不能静默改正文。

    订正段要含三件事：

    | 内容 | 为什么 |
    |---|---|
    | 旧值 0.0079 与旧结论"显著" | 让读者知道哪个数被撤销 |
    | 错因（C 组混入对照组） | 让读者能判断影响范围 |
    | **为什么证伪没发现** | 让下一个人知道检测边界 |

    **第三条最重要**：证伪时断言确实红了，但红是因为代码算出了显著 p，
    不是因为注释被验证。**证伪检查代码行为，不检查注释。**
    """
    report = (ROOT / "docs" / "reports" / "v2-what-it-measures.md").read_text(
        encoding="utf-8"
    )
    section = report.split("## 6. 结论 5")[1].split("\n## ")[0]
    sub = section.split("### 6.9 lexical 的 0.83 / 0.89 是怎么来的")[1].split("### 6.10")[0]

    assert "订正" in sub, "§6.9 必须保留订正段"
    assert "0.0079" in sub, "订正段必须写出旧值 0.0079——否则读者不知道哪个数被撤销"
    assert "C 组" in sub and "对照组" in sub, (
        "订正段必须写明错因是 C 组混入对照组"
    )
    assert "注释" in sub, (
        "订正段必须写明'注释与实现不符'——这是这类错误的根因，"
        "也是为什么证伪没发现它"
    )


def test_report_states_the_discounted_seh1() -> None:
    """**报告必须给出"剔除必然命中后"的 SEH@1 与正确的随机基线。**

    | subject | 报告值 | 剔除后 | 随机基线（1/空间） |
    |---|---|---|---|
    | `sample` | 0.8333 | **0.7500** | **0.6667** |
    | `billing` | 0.8889 | **0.8333** | **0.6111** |

    若不写这两个数，读者会以为"lexical 0.83 vs 随机 0.08，增益 +0.75"——
    而实际增益只有 **+0.17**。
    """
    report = (ROOT / "docs" / "reports" / "v2-what-it-measures.md").read_text(
        encoding="utf-8"
    )
    section = report.split("## 6. 结论 5")[1].split("\n## ")[0]
    sub = section.split("### 6.9 lexical 的 0.83 / 0.89 是怎么来的")[1].split("### 6.10")[0]

    assert "排序空间" in sub, "§6.9 必须引入「排序空间」这个概念"
    for v in ("0.7500", "0.8333", "0.6667", "0.6111"):
        assert v in sub, f"§6.9 必须给出 {v}"


def test_report_does_not_claim_data_is_too_easy() -> None:
    """**报告不得写"lexical 高分 = 数据太容易"**。

    修正后的证据更强：两个 subject 都不显著，所以**没有任何证据**
    支持"词面重叠解释了 top-1"。
    """
    report = (ROOT / "docs" / "reports" / "v2-what-it-measures.md").read_text(
        encoding="utf-8"
    )
    section = report.split("## 6. 结论 5")[1].split("\n## ")[0]
    sub = section.split("### 6.9 lexical 的 0.83 / 0.89 是怎么来的")[1].split("### 6.10")[0]

    assert "不成立" in sub or "不得" in sub, (
        "§6.9 必须明确否定'lexical 高分 = 数据太容易'这个推广"
    )


def test_report_registers_bigram_blind_spot() -> None:
    """**报告必须登记 bigram 的漏检**，但要写对机制。

    上一版把 `billing-a3` 解释成"德国↔欧洲 跨语种语义"——
    **那是错的**：实测共享的 bigram 是 **「抬头」**，而 query 里确实有"抬头"二字。

    所以 `a3` 是**字面命中**，不是跨语种语义。
    """
    report = (ROOT / "docs" / "reports" / "v2-what-it-measures.md").read_text(
        encoding="utf-8"
    )
    section = report.split("## 6. 结论 5")[1].split("\n## ")[0]
    sub = section.split("### 6.9 lexical 的 0.83 / 0.89 是怎么来的")[1].split("### 6.10")[0]

    assert "bigram" in sub and "抓不到" in sub, (
        "§6.9 必须登记 bigram 抓不到语义相关"
    )
    # **必须否认 a3 是"德国↔欧洲"的跨语种语义**
    assert "不是" in sub and "跨语种" in sub, (
        "§6.9 必须明确否认 `billing-a3` 是'德国↔欧洲'的跨语种语义映射"
    )
    # 若是**正面**断言它，就会出现"靠'德国↔欧洲'"这种句式
    assert "靠\"德国↔欧洲\"" not in sub and "靠「德国↔欧洲」" not in sub, (
        "§6.9 不得把 billing-a3 命中归因于'德国↔欧洲'——"
        "实测它靠的是「抬头」的字面命中"
    )

