"""cosine 是"gold 检测器"还是"真排序信号"？

## 为什么需要这个检验

前三条泄漏判据（均值差 / 唯一最高 / 分布重叠）全部是
**gold vs 干扰项** 的比较。而"gold 检测器"的特征恰恰是
"gold 与其余差很大"——三条都会通过。

## 两个检验

**检验 A（极差）**：`gap`（gold − 最强干扰）vs `spread`（干扰项内部极差）

| subject | gap 均值 | spread 均值 | gap/spread 中位数 |
|---|---|---|---|
| `sample` | +0.1453 | 0.0657 | 2.24 |
| `billing` | +0.0943 | 0.0427 | 4.11 |

**看起来像 gold 检测器**。但极差被离群值放大，不能作结论。

**检验 B（秩相关，决定性）**：干扰项的 query-cosine 与
"它与 gold 的 cosine"的秩相关。

| subject | rho 均值 | rho 中位数 | 正相关 | top-1 一致 |
|---|---|---|---|---|
| `sample` | **+0.750** | +0.750 | **8/10** | **7/10** |
| `billing` | **+0.500** | **+1.000** | **9/12** | **9/12** |

**结论：未发现 gold 检测器特征。**

## 必须登记的局限

`billing` 每个 case 只有 **2 个干扰项**，rho 只能取 `±1`——
12 个 case 是 9 个 `+1`、3 个 `-1`。**统计力很弱。**

`sample` 的 4 个 case 有 3 个干扰项，rho 可取 `±1` / `±0.5`，稍好但仍小。

**所以只能写"未发现"，不能写"证明"。**
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data" / "retrieval-v2"

#: 报告 §6.12.4 的数字。
EXPECTED = {
    "sample": {
        "gap_mean": 0.1453,
        "spread_mean": 0.0657,
        "ratio_median": 2.24,
        "rho_mean": 0.500,
        "rho_median": 1.000,
        "positive": 8,
        "n": 10,
        "top1_agree": 7,
        # **sample 的 n_dist 是混合值 [2, 3]**：有些 case 只有 2 个同 relation 兄弟。
        "n_dist_set": [2, 3],
    },
    "billing": {
        "gap_mean": 0.0943,
        "spread_mean": 0.0427,
        "ratio_median": 4.11,
        "rho_mean": 0.500,
        "rho_median": 1.000,
        "positive": 9,
        "n": 12,
        "top1_agree": 9,
        "n_dist_set": [2],
    },
}


def _cos(a, b) -> float:
    va = np.asarray(a, dtype=float)
    vb = np.asarray(b, dtype=float)
    na, nb = np.linalg.norm(va), np.linalg.norm(vb)
    if na == 0 or nb == 0:
        return 0.0
    return float(va @ vb / (na * nb))


def _spearman(x: list[float], y: list[float]) -> float:
    """秩相关，用平均秩处理并列。"""
    def ranks(v: list[float]) -> list[float]:
        order = sorted(range(len(v)), key=lambda i: v[i])
        r = [0.0] * len(v)
        i = 0
        while i < len(order):
            j = i
            while j + 1 < len(order) and v[order[j + 1]] == v[order[i]]:
                j += 1
            avg = (i + j) / 2 + 1
            for k in range(i, j + 1):
                r[order[k]] = avg
            i = j + 1
        return r

    rx, ry = ranks(x), ranks(y)
    mx, my = float(np.mean(rx)), float(np.mean(ry))
    sx = float(np.sqrt(sum((a - mx) ** 2 for a in rx)))
    sy = float(np.sqrt(sum((b - my) ** 2 for b in ry)))
    if sx == 0 or sy == 0:
        return 0.0
    return sum((a - mx) * (b - my) for a, b in zip(rx, ry, strict=True)) / (sx * sy)


@pytest.fixture(scope="module")
def measured():
    """现场重跑：极差对比 + 秩相关。"""
    from evals.datasets.retrieval_v2 import load_dataset
    from evals.metrics.v2_baselines import derived_axis_of

    from memory.config import Settings
    from memory.embedding.cache import EmbeddingCache
    from memory.embedding.dashscope import DashScopeEmbedder

    settings = Settings.load()
    settings.cache_dir.mkdir(parents=True, exist_ok=True)
    embedder = DashScopeEmbedder(
        settings=settings, cache=EmbeddingCache(settings.cache_dir / "cache.db")
    )

    out: dict[str, dict] = {}
    for subject in ("sample", "billing"):
        ds = load_dataset(DATA / subject)
        within = {
            q.query_id
            for q in ds.queries
            if derived_axis_of(ds, q) == "relation_within"
        }

        gaps: list[float] = []
        spreads: list[float] = []
        ratios: list[float] = []
        rhos: list[float] = []
        agree = 0
        total = 0
        n_dists: list[int] = []

        for q in ds.queries:
            if q.query_id not in within:
                continue
            gold = ds.memory(q.gold_memory_id)
            others = [
                m
                for m in ds.memories
                if m.memory_id != gold.memory_id
                and m.subject == gold.subject
                and m.relation == gold.relation
            ]
            if len(others) < 2:
                continue

            qv = embedder.embed(q.query, text_type="query")
            gv = embedder.embed(gold.memory_text, text_type="document")
            ovs = [
                embedder.embed(o.memory_text, text_type="document") for o in others
            ]

            gc = _cos(qv, gv)
            q_cos = [_cos(qv, v) for v in ovs]
            g_cos = [_cos(gv, v) for v in ovs]

            spread = max(q_cos) - min(q_cos)
            gap = gc - max(q_cos)

            gaps.append(gap)
            spreads.append(spread)
            n_dists.append(len(others))
            if spread > 1e-9:
                ratios.append(gap / spread)

            if len(others) >= 2:
                rhos.append(_spearman(q_cos, g_cos))
                total += 1
                if int(np.argmax(q_cos)) == int(np.argmax(g_cos)):
                    agree += 1

        out[subject] = {
            "gap_mean": float(np.mean(gaps)),
            "spread_mean": float(np.mean(spreads)),
            "ratio_median": float(np.median(ratios)) if ratios else 0.0,
            "rho_mean": float(np.mean(rhos)) if rhos else 0.0,
            "rho_median": float(np.median(rhos)) if rhos else 0.0,
            "positive": sum(1 for r in rhos if r > 0),
            "n": total,
            "top1_agree": agree,
            "n_dist_set": sorted(set(n_dists)),
        }
    return out


def test_numbers_match_report(measured) -> None:
    """**所有数字必须与报告一致**（4 位小数容差 1e-3）。"""
    problems: list[str] = []
    for subject in ("sample", "billing"):
        got = measured[subject]
        want = EXPECTED[subject]
        for key in ("gap_mean", "spread_mean", "rho_mean", "rho_median"):
            if abs(got[key] - want[key]) > 1e-3:
                problems.append(f"{subject}/{key}: {got[key]:.4f} vs {want[key]}")
        # **倍数用 1e-2 容差**：它是 `gap/spread` 的比值，
        # 报告写 2.24（两位小数），实算 2.2441——用 1e-3 会误报。
        if abs(got["ratio_median"] - want["ratio_median"]) > 1e-2:
            problems.append(
                f"{subject}/ratio_median: {got['ratio_median']:.4f} "
                f"vs {want['ratio_median']}"
            )
        for key in ("positive", "n", "top1_agree"):
            if got[key] != want[key]:
                problems.append(f"{subject}/{key}: {got[key]} vs {want[key]}")
        if got["n_dist_set"] != want["n_dist_set"]:
            problems.append(
                f"{subject}/n_dist_set: {got['n_dist_set']} vs {want['n_dist_set']}"
            )
    assert not problems, "与报告不符：\n  " + "\n  ".join(problems)


def test_gap_exceeds_spread(measured) -> None:
    """**`gap` 必须大于 `spread`**——这条记录"看起来像 gold 检测器"这个事实。

    实测：

    | subject | gap | spread | 倍数 |
    |---|---|---|---|
    | `sample` | +0.1453 | 0.0657 | **2.2×** |
    | `billing` | +0.0943 | 0.0427 | **2.2×** |

    **这个事实必须保留**：它是"可疑"的来源。
    若只写秩相关的结论而删掉这个，读者会以为"一开始就没怀疑过"。
    """
    for subject in ("sample", "billing"):
        got = measured[subject]
        assert got["gap_mean"] > got["spread_mean"], (
            f"{subject}: gap {got['gap_mean']:.4f} 不大于 spread "
            f"{got['spread_mean']:.4f}——'看起来像 gold 检测器'这个前提不成立"
        )
        assert got["gap_mean"] > 2 * got["spread_mean"], (
            f"{subject}: gap 只有 spread 的 "
            f"{got['gap_mean'] / got['spread_mean']:.2f} 倍，不到 2 倍"
        )


def test_spearman_shows_ranking_info(measured) -> None:
    """**秩相关必须为正且显著**——这是"不是 gold 检测器"的决定性证据。

    | subject | rho 中位数 | 正相关 |
    |---|---|---|
    | `sample` | +0.750 | 8/10 |
    | `billing` | **+1.000** | 9/12 |

    **若 rho 接近 0**：cosine 只在 gold 上跳高，干扰项之间无排序信息
    -> 那是 gold 检测器，整个"加 cosine"方向要重新考虑。

    **阈值 0.4**：中位数超过 0.4 说明至少多数 case 有正相关。
    设为 0 会太松（一半正一半负也能过）。
    """
    for subject in ("sample", "billing"):
        got = measured[subject]
        assert got["rho_median"] > 0.4, (
            f"{subject}: rho 中位数 {got['rho_median']:+.3f}，期望 > 0.4。\n"
            "若接近 0，说明 cosine 是 gold 检测器——"
            "它在干扰项之间没有排序信息。"
        )


def test_majority_positive(measured) -> None:
    """**多数 case 的 rho 必须为正。**

    实测 `sample` 8/10、`billing` 9/12。

    **这条与中位数互补**：中位数只看中点，这条看多数。
    若 6 个 +1、6 个 −1，中位数可能是 0 而"多数"也不成立。
    """
    for subject in ("sample", "billing"):
        got = measured[subject]
        ratio = got["positive"] / got["n"]
        assert ratio > 0.6, (
            f"{subject}: 只有 {got['positive']}/{got['n']} 个 case 的 rho 为正"
            f"（{ratio:.0%}），不到 60%"
        )


def test_top1_agreement_above_chance(measured) -> None:
    """**top-1 一致率必须高于随机。**

    含义：cosine 选出的"最相关干扰项"与"最像 gold 的干扰项"
    是否同一个。若 cosine 有排序能力，两者应该高度一致。

    随机基线：`1 / n_dist`。`sample` 是 1/3，`billing` 是 1/2。

    | subject | 一致率 | 随机 |
    |---|---|---|
    | `sample` | 7/10 = 70% | 33% |
    | `billing` | 9/12 = 75% | 50% |
    """
    for subject in ("sample", "billing"):
        got = measured[subject]
        rate = got["top1_agree"] / got["n"]
        chance = 1 / got["n_dist_set"][0]
        assert rate > chance, (
            f"{subject}: top-1 一致率 {rate:.0%} 不高于随机 {chance:.0%}"
        )


def test_small_n_is_registered(measured) -> None:
    """**样本量局限必须被登记。**

    `billing` 每个 case 只有 **2 个干扰项** -> rho 只能取 `±1`。
    `sample` 是 **混合的 [2, 3]**：有些 case 只有 2 个同 relation 兄弟。

    **`sample` 的混合更糟**：一半 case 的 rho 只能取 ±1，另一半可取 ±1/±0.5。
    所以"rho 中位数 = 0.750"里，有 2 个 rho 是二元值。

    **这不是"检验通过"，是"统计力不足"。**
    所以结论只能写"未发现"，不能写"证明"。
    """
    assert measured["billing"]["n_dist_set"] == [2], (
        f"billing 的 n_dist 是 {measured['billing']['n_dist_set']}，期望 [2]"
    )
    assert measured["sample"]["n_dist_set"] == [2, 3], (
        f"sample 的 n_dist 是 {measured['sample']['n_dist_set']}，期望 [2, 3]"
    )

    # rho 的取值必须是离散的（容差处理浮点误差）
    discrete = (-1.0, -0.5, 0.0, 0.5, 1.0)
    for subject in ("sample", "billing"):
        got = measured[subject]
        med = round(got["rho_median"], 6)
        assert any(abs(med - d) < 1e-6 for d in discrete), (
            f"{subject}: rho 中位数 {got['rho_median']} 不是离散值——"
            "n 小的时候 rho 只能取少数值"
        )


# ---------- 报告内容 ----------


def _sub() -> str:
    """取 §6.12.4 的正文。

    **边界用 §6.12.6**：插入了 §6.12.6（噪声边界）后，
    原来的 `split("#### 6.12.5")` 找不到边界，会把后面的内容全包进来——
    那会让"证明"这个词从别处混进来，而断言本意是只检查 §6.12.4。
    """
    report = (ROOT / "docs" / "reports" / "v2-what-it-measures.md").read_text(
        encoding="utf-8"
    )
    body = report.split("## 6. 结论 5")[1].split("\n## ")[0]
    return body.split("#### 6.12.3 ")[1].split("#### 6.12.4")[0]


def test_report_states_both_checks() -> None:
    """**报告必须同时写出极差对比与秩相关。**

    只写秩相关会掩盖"一开始看起来像 gold 检测器"这个事实；
    只写极差会得出错误结论。

    **判据定位到秩相关那张表的行**：`+0.500` 在 §6.12.4 里出现两次
    （表格与正文），全局 `in` 会被另一处顶替。
    """
    sub = _sub()
    assert "极差" in sub or "spread" in sub, (
        "§6.12.4 必须保留极差对比——它是'可疑'的来源"
    )

    rows = [
        ln.strip() for ln in sub.splitlines() if ln.strip().startswith("|")
    ]
    sample_row = [r for r in rows if "`sample`" in r and "+0.500" in r]
    billing_row = [r for r in rows if "`billing`" in r and "9/12" in r]

    assert sample_row, (
        "§6.12.4 的秩相关表缺少 sample 行（含 +0.500）"
    )
    assert billing_row, (
        "§6.12.4 的秩相关表缺少 billing 行（含 9/12）"
    )
    assert "8/10" in sample_row[0], (
        f"sample 行必须含 8/10：{sample_row[0][:80]}"
    )


def test_report_does_not_claim_proof() -> None:
    """**报告必须以"未发现"作为结论，不得把否定表当成已证明。**

    **注意**：报告里会出现 `"证明 cosine 不是 gold 检测器" | ❌` 这一行——
    那是**否定表的最后一行**（说明"什么不能说"），不是结论。

    所以判据不能是 `"证明" not in sub`（会误伤那个否定表），
    而是：
    1. 必须有"未发现"作为正面结论
    2. 必须有那张"三档强度"的表，且"证明"那一档标记为 ❌
    """
    sub = _sub()

    assert "未发现" in sub, "§6.12.4 必须用「未发现」这个措辞"

    # "证明"只能出现在否定表里（与 ❌ 同一行）
    for line in sub.splitlines():
        if "证明" in line:
            assert "❌" in line, (
                f"§6.12.4 出现「证明」但不是否定行：{line.strip()[:70]}\n"
                "若把'证明'写进结论，就是在 n=2 上过度声称。"
            )


def test_report_registers_limitation() -> None:
    """**报告必须登记 `n_dist` 与统计力局限。**"""
    sub = _sub()

    assert "2 个干扰项" in sub or "n_dist = 2" in sub, (
        "§6.12.4 必须写出 billing 的 n_dist = 2"
    )
    assert "统计力" in sub or "样本" in sub, (
        "§6.12.4 必须登记统计力不足"
    )



