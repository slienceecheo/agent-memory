"""同口径增益：剔除必然命中时，SEH@1 与基线必须同步重算。

## 为什么需要

结论 5 原来的对比 `0.83 vs 0.30` 混了两种偏差：

| 量 | 分子 | 分母 | 含必然命中 |
|---|---|---|---|
| lexical 0.8333 | 5 | 6 | **2 条**（空间 = 1） |
| threeway 0.3000 | 3 | 10 | 0 条 |

**分母不同（6 vs 10），且一方含必然命中。**

## 我上一轮算错的地方

我写"lexical 0.83 vs 随机 0.67，增益 +0.17"，用的是**全量**。
而必然命中的基线是 `1/1 = 1.0`，它同时抬高分子与基线，**抵消后把增益压小了**。

**剔除后增益反而更大**：

| subject | 全量 | **剔除后** |
|---|---|---|
| `sample` | +0.1667 | **+0.2500** |
| `billing` | +0.2778 | **+0.4167** |

## 同口径下的结论

| subject | lexical 增益 | threeway 增益 | 判定 |
|---|---|---|---|
| `sample` | +0.2500 | **+0.2167** | **相当**（差 0.0333） |
| `billing` | +0.4167 | **−0.0278** | **真差距** |

**`sample` 上 threeway 的绝对分只有 40%，但相对增益只差 13%。**
它绝对分低是因为**基线低 6 倍**（0.0833 vs 0.5000）。
"""

from __future__ import annotations

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data" / "retrieval-v2"
SUBJECTS = ("sample", "billing")

#: 报告 §6 的同口径数字。
#:
#: **这是「三项装置」的数字，不是当前装置。**
#: 旧装置是 `base=0.4, authority=0.3, status=0.3`，而 `status` 恒 1.0，
#: 所以它等价于 `0.4×base + 0.3×authority + 常数`。
#: 要**精确复现**它，必须让 `cosine` 权重为 0 并按比例放大另两项：
#: `0.4/0.7, 0.3/0.7`（乘 0.7 后恰好回到 `0.4×base + 0.3×authority`）。
#:
#: **为什么不能直接用 `0.4/0.3/0.3`**：第三项现在是 `cosine` 权重，
#: 而 `cosine` 在 commit ② 起有真实取值。那等于换成了另一个装置，
#: 下面 `test_sample_gains_are_comparable` 这类"结论型断言"就会失真。
THREE_FEATURES_WEIGHTS = (0.4 / 0.7, 0.3 / 0.7)

#: 报告 §6 的同口径数字（三项装置）。改动这里必须同时改报告。
EXPECTED = {
    "sample": {
        "lexical": {
            "n_all": 6, "seh1_all": 0.8333, "base_all": 0.6667,
            "n_kept": 4, "seh1_kept": 0.7500, "base_kept": 0.5000,
        },
        "threeway": {
            "n_all": 10, "seh1_all": 0.3000, "base_all": 0.0833,
            "n_kept": 10, "seh1_kept": 0.3000, "base_kept": 0.0833,
        },
    },
    "billing": {
        "lexical": {
            "n_all": 9, "seh1_all": 0.8889, "base_all": 0.6111,
            "n_kept": 6, "seh1_kept": 0.8333, "base_kept": 0.4167,
        },
        "threeway": {
            "n_all": 12, "seh1_all": 0.0833, "base_all": 0.1111,
            "n_kept": 12, "seh1_kept": 0.0833, "base_kept": 0.1111,
        },
    },
}


@pytest.fixture(scope="module")
def measured():
    """现场重跑两种路径，返回全量与剔除后的统计。"""
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
        # **精确复现三项装置**：status 恒 1.0，所以它贡献的是常数；
        # 把另两项按比例放大到和为 1，cosine 权重为 0。
        # 这样 `0.4×base + 0.3×authority` 的相对权重完全不变。
        b, a = THREE_FEATURES_WEIGHTS
        rr.PREREGISTERED_WEIGHTS["__cal"] = RerankWeights(
            base=b, authority=a, cosine=0.0
        )

        for subject in SUBJECTS:
            ds = load_dataset(DATA / subject)
            rows = adapt_rows(ds)
            specs = [r["gold"] for r in rows if r["gold"]]
            within = {
                q.query_id
                for q in ds.queries
                if derived_axis_of(ds, q) == "relation_within"
            }
            out[subject] = {}

            for label, paths in (
                ("lexical", ("lexical",)),
                ("threeway", ("lexical", "vector", "adjacency")),
            ):
                res = rr.evaluate(
                    rows,
                    all_specs=specs,
                    weights_name="__cal",
                    enable_dedup=False,
                    judge=None,
                    k=5,
                    pool_mode=PoolMode.UNRELATED,
                    paths=paths,
                    embedder=embedder,
                )

                recs = []
                for case in res["per_case"]:
                    cid = case["case_id"]
                    if cid not in within:
                        continue
                    if not case.get("has_gold") or case.get("skipped"):
                        continue
                    if case.get("rank_after_fusion") is None:
                        continue  # 未召回：不参与 top-1 统计
                    recs.append(
                        {
                            "cid": cid,
                            "space": len(case.get("fusion_tags") or []),
                            "hit": case.get("rank_after_rerank") == 1,
                        }
                    )

                n_all = len(recs)
                hit_all = sum(1 for r in recs if r["hit"])
                base_all = sum(1 / r["space"] for r in recs) / n_all if n_all else 0.0

                kept = [r for r in recs if r["space"] >= 2]
                n_kept = len(kept)
                hit_kept = sum(1 for r in kept if r["hit"])
                base_kept = (
                    sum(1 / r["space"] for r in kept) / n_kept if n_kept else 0.0
                )

                out[subject][label] = {
                    "n_all": n_all,
                    "seh1_all": hit_all / n_all if n_all else 0.0,
                    "base_all": base_all,
                    "gain_all": (hit_all / n_all - base_all) if n_all else 0.0,
                    "n_kept": n_kept,
                    "seh1_kept": hit_kept / n_kept if n_kept else 0.0,
                    "base_kept": base_kept,
                    "gain_kept": (hit_kept / n_kept - base_kept) if n_kept else 0.0,
                }
    finally:
        rr.PREREGISTERED_WEIGHTS.clear()
        rr.PREREGISTERED_WEIGHTS.update(original)
    return out


def test_same_caliber_numbers_match_report(measured) -> None:
    """**同口径的数字必须与报告一致。**

    两种口径都要对：全量（含必然命中）与剔除后。
    只对一个会让"剔除"这个动作的效果无法验证。
    """
    problems: list[str] = []
    for subject in SUBJECTS:
        for label in ("lexical", "threeway"):
            got = measured[subject][label]
            want = EXPECTED[subject][label]
            for key in ("n_all", "n_kept"):
                if got[key] != want[key]:
                    problems.append(
                        f"{subject}/{label}/{key}: 实际 {got[key]}，报告 {want[key]}"
                    )
            for key in ("seh1_all", "base_all", "seh1_kept", "base_kept"):
                if abs(got[key] - want[key]) > 1e-3:
                    problems.append(
                        f"{subject}/{label}/{key}: 实际 {got[key]:.4f}，报告 {want[key]}"
                    )
    assert not problems, "同口径数字与报告不符：\n  " + "\n  ".join(problems)


def test_lexical_gain_grows_after_excluding_inevitable(measured) -> None:
    """**剔除必然命中后，lexical 的增益反而更大。**

    | subject | 全量增益 | 剔除后增益 |
    |---|---|---|
    | `sample` | +0.1667 | **+0.2500** |
    | `billing` | +0.2778 | **+0.4167** |

    **为什么**：必然命中的基线是 `1/1 = 1.0`，
    它同时抬高分子与基线，抵消后把增益**压小**了。

    **这条防的是我上一轮的错误**：只剔分子不剔分母，会得出"增益只有 +0.17"。
    正确做法是两者同步重算。
    """
    for subject in SUBJECTS:
        got = measured[subject]["lexical"]
        assert got["gain_kept"] > got["gain_all"], (
            f"{subject}: 剔除后增益 {got['gain_kept']:+.4f} 不大于全量 "
            f"{got['gain_all']:+.4f}。\n"
            "若剔除后增益变小，说明基线没有同步重算——"
            "必然命中的基线是 1.0，会同时抬高分子与分母。"
        )
        assert got["n_kept"] < got["n_all"], (
            f"{subject}: 剔除后 n 没有减少（{got['n_kept']} vs {got['n_all']}）——"
            "说明没有 '空间=1' 的 case，与报告不符"
        )


def test_threeway_has_no_inevitable_hits(measured) -> None:
    """**threeway 没有"必然命中"**（它的排序空间总是 >= 2）。

    实测 two subjects 都是 `n_kept == n_all`。

    **这本身是个结论**：threeway 把整个池拉进排序，
    所以不存在"只有 gold 一个候选"的情况。
    **但也因此它的基线很低**（`1/9` 到 `1/12`）。
    """
    for subject in SUBJECTS:
        got = measured[subject]["threeway"]
        assert got["n_kept"] == got["n_all"], (
            f"{subject}: threeway 的 n_kept={got['n_kept']} != n_all={got['n_all']}——"
            "出现了空间=1 的 case，与'三路返回整个池'不符"
        )
        assert got["gain_kept"] == pytest.approx(got["gain_all"], abs=1e-9)


def test_threeway_baseline_is_much_lower(measured) -> None:
    """**threeway 的基线比 lexical 低 5–6 倍。**

    | subject | lexical 基线 | threeway 基线 | 倍数 |
    |---|---|---|---|
    | `sample` | 0.5000 | 0.0833 | **6.0** |
    | `billing` | 0.4167 | 0.1111 | **3.75** |

    **原因**：基线 = `mean(1/排序空间)`。
    lexical 只返回 1–4 条，threeway 返回整个池（9–12 条）。

    **这正是"融合稀释"的精确机制**：不是 RRF 算错了，
    而是候选集大了 3 倍，其中大部分是噪声。
    """
    for subject, ratio_min in (("sample", 4.0), ("billing", 3.0)):
        lex = measured[subject]["lexical"]["base_kept"]
        tri = measured[subject]["threeway"]["base_all"]
        assert tri < lex, f"{subject}: threeway 基线 {tri:.4f} 不低于 lexical {lex:.4f}"
        ratio = lex / tri
        assert ratio >= ratio_min, (
            f"{subject}: 基线倍数 {ratio:.2f} 小于 {ratio_min}。\n"
            "若倍数变小，'候选集大小'这个解释要重核。"
        )


def test_sample_gains_are_comparable(measured) -> None:
    """**`sample` 上两种配置的相对增益相当**（差 < 0.05）。

    | 配置 | 增益 |
    |---|---|
    | lexical（剔除后） | +0.2500 |
    | threeway | +0.2167 |
    | **差** | **0.0333** |

    **但绝对分数差 0.45**（0.7500 vs 0.3000）。
    所以"threeway 更差"这个说法只在绝对分数上成立，**相对增益上不成立**。
    """
    lex = measured["sample"]["lexical"]["gain_kept"]
    tri = measured["sample"]["threeway"]["gain_kept"]
    diff = abs(lex - tri)

    assert diff < 0.05, (
        f"sample: lexical 增益 {lex:+.4f} 与 threeway {tri:+.4f} 差 {diff:.4f}，"
        "超过 0.05——'相对增益相当'这个结论不成立"
    )

    # 同时记录：绝对分数差很大，但那不是增益差
    seh1_diff = abs(
        measured["sample"]["lexical"]["seh1_kept"]
        - measured["sample"]["threeway"]["seh1_kept"]
    )
    assert seh1_diff > 0.3, (
        f"sample: 绝对分差只有 {seh1_diff:.4f}，与报告'差 0.45'不符"
    )


def test_billing_threeway_gain_is_negative(measured) -> None:
    """**`billing` 上 threeway 的增益为负**——这是真正的差距。

    | 配置 | SEH@1 | 基线 | 增益 |
    |---|---|---|---|
    | lexical（剔除后） | 0.8333 | 0.4167 | **+0.4167** |
    | threeway | 0.0833 | 0.1111 | **−0.0278** |

    **负增益意味着排序不优于随机。** 这与"v3 三个特征不含语义信号"一致。
    """
    tri = measured["billing"]["threeway"]["gain_kept"]
    lex = measured["billing"]["lexical"]["gain_kept"]

    assert tri < 0, (
        f"billing: threeway 增益 {tri:+.4f} 不为负——"
        "'排序不优于随机'这个结论要重核"
    )
    assert lex > 0.3, (
        f"billing: lexical 增益 {lex:+.4f} 不大于 0.3，与报告 +0.4167 不符"
    )
    assert lex - tri > 0.4, (
        f"billing: 两者增益差 {lex - tri:.4f} 小于 0.4——"
        "'这是真正的差距'这个判断要重核"
    )


# ---------- 报告内容 ----------


def _section() -> str:
    report = (ROOT / "docs" / "reports" / "v2-what-it-measures.md").read_text(
        encoding="utf-8"
    )
    return report.split("## 6. 结论 5")[1].split("\n## ")[0]


def test_report_states_same_caliber() -> None:
    """**报告必须写出同口径表**（全量与剔除后两种）。"""
    sub = _section()
    assert "同口径" in sub, "§6 必须引入「同口径」这个概念"
    for v in ("0.7500", "0.5000", "0.2167", "0.4167", "0.1111"):
        assert v in sub, f"§6 必须给出 {v}"


def test_report_keeps_old_comparison_with_warning() -> None:
    """**旧对比必须保留，并标注"不能直接读"。**

    若不标注，下一个人从 git 历史里看到 `0.83 vs 0.30` 会以为那能用。

    **必须说明两种偏差**：
    1. 分母不同（6 vs 10）
    2. 一方含必然命中（lexical 的 6 里有 2 条空间 = 1）

    **判据必须定位到具体的句子**，不能用 `"不能直接读" in sub`——
    §6 里这句话出现两次（§6.5 的表格注、§6.5.1 的正文），
    删掉一处另一处仍会让断言通过。
    """
    sub = _section()
    assert "0.83 vs 0.30" in sub or "0.8333 vs 0.3000" in sub, (
        "§6 必须保留旧对比的数字"
    )
    # 必须**紧邻** §6.5 那张表
    tail = sub.split("#### 6.5.1")[0]
    assert "混口径" in tail, (
        "§6.5 的表格下方必须紧邻'混口径'标注——"
        "否则读者会继续用 0.8333 vs 0.3000 那个对比"
    )
    # §6.5.1 的正文要写出两种偏差
    body = sub.split("#### 6.5.1")[1].split("#### 6.5.2")[0]
    assert "不能直接读" in body, "§6.5.1 正文必须写明旧表不能直接读"
    assert "分母不同" in body, "§6.5.1 必须写出「分母不同」这个偏差"
    assert "必然命中" in body, "§6.5.1 必须点明「必然命中」这个偏差"


def test_report_states_the_corrected_conclusion() -> None:
    """**结论 5 必须改成"相对增益"的说法，不是"精度变低"。**

    旧：三路融合让 top-1 变低
    新：`sample` 上相对增益相当，`billing` 上为负

    **判据定位到 §6.5.2**：`"相当"` 在 §6 里出现多次（表格、正文、结论引文），
    全局 `in` 会被别处的用法顶替——实测过：删掉表格那一格，
    结论引文里的"相当"仍让断言通过。

    **所以断言的是那一行的完整内容**，不是关键词。
    """
    sub = _section()
    assert "相对增益" in sub, "§6 必须用「相对增益」而不是只有绝对分数"

    body = sub.split("#### 6.5.2")[1].split("#### 6.5.3")[0]
    rows = [
        ln.strip() for ln in body.splitlines() if ln.strip().startswith("|")
    ]
    sample_row = [r for r in rows if "`sample`" in r]
    billing_row = [r for r in rows if "`billing`" in r]

    assert sample_row, "§6.5.2 的表格缺少 sample 那一行"
    assert billing_row, "§6.5.2 的表格缺少 billing 那一行"

    # sample 行必须说"相当"，且给出两个增益
    assert "相当" in sample_row[0], (
        f"§6.5.2 的 sample 行必须写出「相当」：{sample_row[0][:80]}"
    )
    assert "+0.2167" in sample_row[0] and "+0.2500" in sample_row[0], (
        "§6.5.2 的 sample 行必须给出两个增益"
    )

    # billing 行必须说"负"，且给出 -0.0278
    assert "负" in billing_row[0] or "−" in billing_row[0], (
        f"§6.5.2 的 billing 行必须写出「为负」：{billing_row[0][:80]}"
    )
    assert "0.0278" in billing_row[0], (
        "§6.5.2 的 billing 行必须给出 threeway 的负增益"
    )
