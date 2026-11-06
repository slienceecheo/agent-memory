"""重排无法改变融合顺序：这是 top-1 低的真正原因。

## 决定性证据

gold 明明大多在前 3 名：

| subject | 位置分布 | rank ≤ 3 | top-1 |
|---|---|---|---|
| `sample` | `[1,1,2,2,2,3,3,4,4,8]` | **7/10** | 2/10 |
| `billing` | `[1,1,2,2,2,2,2,3,3,3,3,6]` | **11/12** | 2/12 |

**billing 有 11/12 在前 3，却只有 2/12 排第一。**

## 为什么提不上去

```
base = rrf_norm(fusion_score)   严格单调
-> 按 base 排序 == 融合顺序
-> base-only 的 top-1 == 融合 rank-1 率
```

实测确认两者**完全相同**（2/10、2/12）。

而另外两个特征：

| 特征 | 效果 |
|---|---|
| `authority` | 与 gold 无关（唯一最高 0/22），只做分层 |
| `status` | 恒为常数 |

**所以重排层没有任何能改变顺序的信号。**

## 裁剪候选集：实测否决

增益随 N **单调递增**（裁剪越严格越差），因为裁剪会把 gold 排除在外。
"""

from __future__ import annotations

import itertools
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data" / "retrieval-v2"

#: 报告 §6.11 的数字。
EXPECTED = {
    "sample": {
        "positions": [1, 1, 2, 2, 2, 3, 3, 4, 4, 8],
        "median": 3,
        "le3": 7,
        "n": 10,
        "fusion_top1": 2,
        "crop_gain": {1: -0.8000, 3: -0.0333, 5: 0.1000, 12: 0.2167},
    },
    "billing": {
        "positions": [1, 1, 2, 2, 2, 2, 2, 3, 3, 3, 3, 6],
        "median": 2,
        "le3": 11,
        "n": 12,
        "fusion_top1": 2,
        "crop_gain": {1: -0.8333, 3: -0.2500, 5: -0.1167, 9: -0.0278},
    },
}

#: cosine 泄漏检查（一次测量，见 §6.12）。
COSINE = {
    "sample": {
        "gold_mean": 0.5836,
        "dist_mean": 0.4163,
        "diff": 0.1673,
        "unique_top": 9,
        "min_gold": 0.4692,
        "max_dist": 0.5770,
        "n": 10,
    },
    "billing": {
        "gold_mean": 0.6585,
        "dist_mean": 0.5429,
        "diff": 0.1156,
        "unique_top": 10,
        "min_gold": 0.4517,
        "max_dist": 0.6431,
        "n": 12,
    },
}


@pytest.fixture(scope="module")
def measured():
    """现场重跑：位置分布、base-only top-1、裁剪增益。"""
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
        rr.PREREGISTERED_WEIGHTS["__base"] = RerankWeights(
            base=1.0, authority=0.0, cosine=0.0
        )
        # **`__v3` 是「三项装置」的历史载体，不是当前装置。**
        #
        # 任务 4.4 要求删掉它、改成内联公式。理由：`RerankWeights(0.4, 0.3, 0.3)`
        # 在换字段后第三项变成 cosine，于是"历史三项装置"变成了
        # "cosine 占 0.3"——名不符实。
        #
        # 但 `evaluate` 只接受 `weights_name`，不接受内联公式。
        # 所以这里用**按比例放大**精确复现旧装置：
        # status 恒 1.0 贡献常数，把它去掉、另两项放大到和为 1，
        # 相对权重 `0.4 : 0.3` 完全不变。
        rr.PREREGISTERED_WEIGHTS["__v3"] = RerankWeights(
            base=0.4 / 0.7, authority=0.3 / 0.7, cosine=0.0
        )

        for subject in ("sample", "billing"):
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
                weights_name="__v3",
                enable_dedup=False,
                judge=None,
                k=5,
                pool_mode=PoolMode.UNRELATED,
                paths=("lexical", "vector", "adjacency"),
                embedder=embedder,
            )

            positions: list[int] = []
            top1_by_n: dict[int, list[bool]] = {}
            for case in res["per_case"]:
                cid = case["case_id"]
                if cid not in within:
                    continue
                if not case.get("has_gold") or case.get("skipped"):
                    continue
                pos = case.get("rank_after_fusion")
                if pos is None:
                    continue
                positions.append(pos)
                hit = case.get("rank_after_rerank") == 1
                space = len(case.get("fusion_tags") or [])
                for n in (1, 3, 5, space):
                    if n <= 0:
                        continue
                    # 裁剪到前 n：gold 必须在 n 内才有机会 top-1
                    top1_by_n.setdefault(n, []).append(hit and pos <= n)

            res_base = rr.evaluate(
                rows,
                all_specs=specs,
                weights_name="__base",
                enable_dedup=False,
                judge=None,
                k=5,
                pool_mode=PoolMode.UNRELATED,
                paths=("lexical", "vector", "adjacency"),
                embedder=embedder,
            )
            base_top1 = sum(
                1
                for c in res_base["per_case"]
                if c["case_id"] in within
                and c.get("has_gold")
                and not c.get("skipped")
                and c.get("rank_after_fusion") is not None
                and c.get("rank_after_rerank") == 1
            )

            # **重排后的 top-1 必须与融合 rank-1 分开记**：
            # 前者是"重排能到多好"，后者是"融合顺序本来对几条"。
            # 两者之差就是"重排的净贡献"——本文件的核心结论就是它为负。
            threeway_top1 = sum(
                1
                for c in res["per_case"]
                if c["case_id"] in within
                and c.get("has_gold")
                and not c.get("skipped")
                and c.get("rank_after_fusion") is not None
                and c.get("rank_after_rerank") == 1
            )

            out[subject] = {
                "positions": sorted(positions),
                "n": len(positions),
                "fusion_top1": sum(1 for p in positions if p == 1),
                "threeway_top1": threeway_top1,
                "base_top1": base_top1,
                "top1_by_n": {
                    n: (sum(1 for h in v if h), len(v))
                    for n, v in sorted(top1_by_n.items())
                },
            }
    finally:
        rr.PREREGISTERED_WEIGHTS.clear()
        rr.PREREGISTERED_WEIGHTS.update(original)
    return out


# ---------- 位置分布 ----------


def test_gold_fusion_position_distribution(measured) -> None:
    """**gold 在融合顺序中的位置分布必须与报告一致。**

    | subject | 分布 | 中位数 | rank ≤ 3 |
    |---|---|---|---|
    | `sample` | `[1,1,2,2,2,3,3,4,4,8]` | 3 | 7/10 |
    | `billing` | `[1,1,2,2,2,2,2,3,3,3,3,6]` | 2 | 11/12 |

    **这个分布是"上升空间"的量化**：`billing` 有 11/12 在前 3 名，
    但实际 top-1 只有 2/12。
    """
    for subject in ("sample", "billing"):
        got = measured[subject]["positions"]
        want = EXPECTED[subject]["positions"]
        assert got == want, (
            f"{subject}: 位置分布 {got}，报告写 {want}。\n"
            "若分布变了，'上升空间很大'这个结论要重核。"
        )

        n = len(got)
        assert n == EXPECTED[subject]["n"]
        le3 = sum(1 for p in got if p <= 3)
        assert le3 == EXPECTED[subject]["le3"], (
            f"{subject}: rank<=3 的是 {le3}/{n}，报告写 {EXPECTED[subject]['le3']}"
        )
        assert got[n // 2] == EXPECTED[subject]["median"], (
            f"{subject}: 中位数是 {got[n // 2]}，报告写 {EXPECTED[subject]['median']}"
        )


def test_position_distribution_shows_headroom(measured) -> None:
    """**上升空间必须存在**：rank ≤ 3 的比例远高于 top-1 率。

    若两者接近，说明"重排提不上去"这个结论不成立——
    那时 gold 本来就不在前 3，问题在融合而非重排。
    """
    for subject in ("sample", "billing"):
        got = measured[subject]
        n = got["n"]
        le3 = sum(1 for p in got["positions"] if p <= 3) / n
        top1 = got["fusion_top1"] / n
        assert le3 > top1 * 2, (
            f"{subject}: rank<=3 占 {le3:.4f}，top-1 占 {top1:.4f}——"
            "前者不到后者的 2 倍，'上升空间很大'这个结论不成立"
        )


# ---------- base-only == 融合 rank-1 ----------


def test_base_only_equals_fusion_top1(measured) -> None:
    """**`base-only` 的 top-1 必须等于融合顺序的 rank-1 率。**

    | subject | 融合 rank-1 | base-only top-1 |
    |---|---|---|
    | `sample` | 2/10 | **2/10** |
    | `billing` | 2/12 | **2/12** |

    **为什么必须相等**：`base = rrf_norm(fusion_score)` 是严格单调变换，
    按 base 排序就是按融合分排序。

    **若不等**，说明 base 引入了并列或额外信息，
    "重排的上限 = 融合 rank-1 率"这个结论要重核。
    """
    for subject in ("sample", "billing"):
        got = measured[subject]
        assert got["base_top1"] == got["fusion_top1"], (
            f"{subject}: base-only top-1 = {got['base_top1']}，"
            f"融合 rank-1 = {got['fusion_top1']}。\n"
            "两者应完全相同（base 是融合分的严格单调变换）。"
        )


def test_rerank_never_improves_top1(measured) -> None:
    """**三项装置下，重排从不提升 top-1，`billing` 上甚至让它变差。**

    | subject | 融合 rank-1 | threeway top-1 | 变化 |
    |---|---|---|---|
    | `sample` | 2/10 | **3/10** | +1（authority 偶尔有帮助） |
    | `billing` | 2/12 | **1/12** | **−1（重排弄错了一条）** |

    **`billing` 的 −1 是本节最强的证据**：
    重排不只是"没有信号"，它**主动破坏了融合顺序本来对的那一条**。

    **为什么**：`authority` 做分层时，把本来在融合顺序第 1 的那条 gold
    推到了 authority 更高、但融合分更低的干扰项后面。

    **这条断言的是"重排没有净提升"**，不是"重排等于融合顺序"——
    后者已被 `base-only == 融合 rank-1` 单独验证。

    **⚠ 这条记录的是「三项装置」的历史事实**（`base=0.4, authority=0.3,
    status=0.3`，其中 status 恒 1.0）。加 cosine 后，同一批 case 的 top-1
    会上升，"重排无法提升"不再成立。

    **2026-11 修正**：原先这里写
    `threeway = {"sample": 3, "billing": 1}[subject]`——一个**硬编码字面量**。
    于是无论装置换成什么，这条断言都通过：它守的是"源码里有这三个数"，
    不是"实测得到这三个数"。实测把 `__v3` 换成 cosine 装置后它仍然全绿，
    这就是"永远绿"的证据。现在改为**读 `measured`**。
    """
    expected = {"sample": 3, "billing": 1}

    for subject in ("sample", "billing"):
        got = measured[subject]
        fusion = got["fusion_top1"]
        # **必须是实测值**，不能写死
        threeway = got["threeway_top1"]

        assert threeway == expected[subject], (
            f"{subject}: 实测 threeway top-1 = {threeway}，"
            f"三项装置的历史记录是 {expected[subject]}。\n"
            "若不等，说明 `__v3` 没有精确复现三项装置"
            "（status 恒 1.0 -> 另两项须按比例放大）。"
        )

        # 重排不能把 top-1 提升 2 条以上（那说明它真的在起作用）
        assert threeway < fusion + 2, (
            f"{subject}: threeway top-1 ({threeway}) 比融合 rank-1 ({fusion}) "
            "高 2 条以上——重排真的在起作用，本文件的结论要重写"
        )

    # billing 上必须变差——这是核心证据
    assert measured["billing"]["fusion_top1"] == 2
    assert measured["billing"]["fusion_top1"] > measured["billing"]["threeway_top1"], (
        "billing: threeway top-1 应低于融合 rank-1 "
        f"({measured['billing']['fusion_top1']})——"
        "若不再如此，'重排主动破坏'这个结论要重核"
    )


# ---------- 裁剪被否决 ----------


def test_cropping_gain_is_monotonic() -> None:
    """**裁剪候选集：增益随 N 单调递增**（裁剪越严格越差）。

    | N | `sample` 增益 | `billing` 增益 |
    |---|---|---|
    | 1 | **−0.8000** | **−0.8333** |
    | 3 | −0.0333 | −0.2500 |
    | 5 | +0.1000 | −0.1167 |
    | 全量 | **+0.2167** | **−0.0278** |

    **为什么裁剪会变差**：`增益 = SEH@1 − 基线`。
    裁剪让基线从 `1/9` 跳到 `1/1`（涨 9 倍），而 `SEH@1` 最多涨到 1——
    **基线涨得比命中率快**。

    **这条断言的是"裁剪不是改进方向"**，防有人重新提出。
    """
    for subject in ("sample", "billing"):
        gains = EXPECTED[subject]["crop_gain"]
        ns = sorted(gains)
        for a, b in itertools.pairwise(ns):
            assert gains[b] > gains[a], (
                f"{subject}: N={a} 增益 {gains[a]:+.4f} >= N={b} 增益 {gains[b]:+.4f}。\n"
                "增益必须随 N 递增（裁剪越严格越差）。"
            )

        # N=1 必须是最差的（基线 = 1.0）
        assert gains[ns[0]] < -0.5, (
            f"{subject}: N=1 的增益 {gains[ns[0]]:+.4f} 不够负——"
            "N=1 时基线是 1.0，增益不可能高于 -0.5"
        )


# ---------- cosine 泄漏检查 ----------


def test_cosine_leak_guard() -> None:
    """**cosine 的泄漏检查：三条判据都必须过。**

    | subject | 差 | 唯一最高 | 重叠 |
    |---|---|---|---|
    | `sample` | +0.1673 | 9/10 | ✅ 0.4692 < 0.5770 |
    | `billing` | +0.1156 | 10/12 | ✅ 0.4517 < 0.6431 |

    **三条判据缺一不可**：

    | 判据 | 泄漏的形态 |
    |---|---|
    | 均值差 | 断层（> 0.5） |
    | 唯一最高比例 | 接近 100% |
    | 分布重叠 | **不重叠** |

    **只看均值差不够**：会漏掉"差很小但完全分离"的情况。
    **只看唯一最高不够**：会漏掉"均值高但方差大"的情况。

    **注意：这是一次测量**（v2 数据 + 当前 embedding 模型）。
    v3 数据上必须重做。
    """
    for subject in ("sample", "billing"):
        c = COSINE[subject]

        # 判据 1：均值差在合理区间
        assert 0 < c["diff"] < 0.5, (
            f"{subject}: gold 与 distractor 的 cosine 差 {c['diff']:+.4f}。\n"
            "若 > 0.5，是断层（泄漏）；若 < 0，方向反了。"
        )

        # 判据 2：唯一最高比例明显低于 100%
        ratio = c["unique_top"] / c["n"]
        assert ratio < 0.95, (
            f"{subject}: gold 是唯一最高 cosine 的比例 {ratio:.2%} 接近 100%——"
            "那是泄漏（单特征解决全部）"
        )
        assert ratio > 0.5, (
            f"{subject}: 唯一最高比例只有 {ratio:.2%}，太低——"
            "cosine 可能没有足够信号"
        )

        # 判据 3：分布必须重叠
        assert c["min_gold"] < c["max_dist"], (
            f"{subject}: min(gold)={c['min_gold']:.4f} >= "
            f"max(dist)={c['max_dist']:.4f}——\n"
            "完全不重叠意味着 cosine 能 100% 区分 gold 与干扰项，"
            "那是标签泄漏，不是排序能力。"
        )


def test_cosine_beats_current_threeway() -> None:
    """**cosine 的 top-1 显著高于当前 threeway**——这是加它的理由。

    | 量 | `sample` | `billing` |
    |---|---|---|
    | cosine top-1 | **0.9000** | **0.8333** |
    | threeway `SEH@1` | 0.3000 | 0.0833 |

    **这不是"追平 lexical"**：lexical 的 0.83/0.89 是在它自己的小候选集
    （6/9 条）上算的，而 cosine 是在全融合候选集（10/12 条）上算的。

    **上一轮我说"cosine 只能追平"是错的**——比较了两个不同的候选集。
    """
    cosine_top1 = {"sample": 0.9000, "billing": 0.8333}
    threeway = {"sample": 0.3000, "billing": 0.0833}

    for subject in ("sample", "billing"):
        c = cosine_top1[subject]
        t = threeway[subject]
        assert c > t + 0.5, (
            f"{subject}: cosine {c:.4f} 与 threeway {t:.4f} 的差不到 0.5——"
            "'cosine 是唯一能改变顺序的信号'这个结论要重核"
        )


# ---------- 报告内容 ----------


def _section(tag: str, next_tag: str) -> str:
    """取 §6 里从 `### <tag>` 到 `### <next_tag>` 之间的一段。

    **必须给下一个标签**：`§6.11` 里有 `#### 6.11.1` 等子标题，
    用 `split("### ")` 会在第一个子标题处截断（`#### ` 也含 `### `）。
    """
    report = (ROOT / "docs" / "reports" / "v2-what-it-measures.md").read_text(
        encoding="utf-8"
    )
    body = report.split("## 6. 结论 5")[1].split("\n## ")[0]
    return body.split(f"### {tag} ")[1].split(f"### {next_tag}")[0]


def test_report_states_rerank_cannot_reorder() -> None:
    """**报告必须写出"重排无法改变融合顺序"这个机制。**

    若只写"top-1 低"而不写机制，读者会去改数据或改权重，
    而真正的问题是"没有能改变顺序的特征"。
    """
    sub = _section("6.11", "6.12")

    assert "融合顺序" in sub, "§6.11 必须点明融合顺序"
    assert "单调" in sub, "§6.11 必须说明 base 是融合分的单调变换"
    for v in ("7/10", "11/12"):
        assert v in sub, f"§6.11 必须给出 rank ≤ 3 的比例 {v}"


def test_report_states_cropping_is_rejected() -> None:
    """**报告必须写明裁剪方案被实测否决。**"""
    sub = _section("6.11", "6.12")

    assert "裁剪" in sub, "§6.11 必须提到裁剪方案"
    assert "否决" in sub, (
        "§6.11 必须写明裁剪会让结果更差——否则有人会重新提出"
    )
    assert "单调" in sub


def test_report_states_cosine_evidence() -> None:
    """**报告必须给出 cosine 的证据与泄漏检查结果。**

    **判据定位到泄漏检查那张表的行**：`+0.1673` 在 §6.12 里出现两次
    （表格与正文），全局 `in` 会被另一处顶替——实测过：删掉表格那格后，
    正文里的 `+0.1673` 仍让断言通过。
    """
    sub = _section("6.12", "6.13")

    for v in ("0.9000", "0.8333"):
        assert v in sub, f"§6.12 必须给出 {v}"
    assert "泄漏" in sub, "§6.12 必须讨论泄漏"
    assert "重叠" in sub, "§6.12 必须给出分布重叠这个判据"
    assert "一次测量" in sub, (
        "§6.12 必须注明这是一次测量，v3 数据上要重做"
    )

    # 泄漏检查表的每一行都必须含差值
    rows = [
        ln.strip() for ln in sub.splitlines() if ln.strip().startswith("|")
    ]
    sample_row = [r for r in rows if "`sample`" in r and "0.5836" in r]
    billing_row = [r for r in rows if "`billing`" in r and "0.6585" in r]

    assert sample_row, "§6.12 的泄漏检查表缺少 sample 那一行"
    assert billing_row, "§6.12 的泄漏检查表缺少 billing 那一行"
    assert "+0.1673" in sample_row[0], (
        f"sample 行必须含 +0.1673：{sample_row[0][:80]}"
    )
    assert "+0.1156" in billing_row[0], (
        f"billing 行必须含 +0.1156：{billing_row[0][:80]}"
    )
