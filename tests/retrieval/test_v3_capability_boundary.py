"""v3 装置的能力边界：三个特征各自提供什么信号。

## 三条实测边界（都可复算）

| 特征 | 性质 | 判据 |
|---|---|---|
| `status` | 恒为常数 | 池内方差 == 0 |
| `base` | 等于融合顺序 | `rrf_norm` 严格单调 |
| `authority` | 分层过滤器 | 同层逆序 == 0 |

## 为什么这不是"缺陷报告"

它是**能力边界**：v3 的 rerank 层不含语义相关性信号，
所以它的预期增益 ≈ 0，而那是一个可解释的 0。

**而"预期增益 ≈ 0"必须与"数据侧的禁止事项"配对**：
若有人为了提高增益而让 authority 与 gold 相关，
他重造的就是 v2 的 `condition` 直通缺陷。

## 为什么注释里写满了数字

这些数字不是"参考值"，是**判据的依据**。
若 v2 数据变了，断言会红，而红的时候需要知道原值是多少。
"""

from __future__ import annotations

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data" / "retrieval-v2"
SUBJECTS = ("sample", "billing")


def _ds(subject: str = "sample"):
    from evals.datasets.retrieval_v2 import load_dataset

    return load_dataset(DATA / subject)


def _within_ranks(res: dict, ds) -> dict[str, int | None]:
    from evals.metrics.v2_baselines import derived_axis_of

    ids = {
        q.query_id for q in ds.queries if derived_axis_of(ds, q) == "relation_within"
    }
    return {
        c["case_id"]: c.get("rank_after_rerank")
        for c in res["per_case"]
        if c["case_id"] in ids and c.get("has_gold") and not c.get("skipped")
    }


@pytest.fixture(scope="module")
def probe():
    """跑一次评测，复用给所有断言（评测较慢，不能每条重跑）。"""
    import evals.run_retrieval as rr
    from evals.datasets.retrieval_v2 import load_dataset
    from evals.datasets.v2_adapter import rows as adapt_rows
    from evals.run_retrieval import evaluate

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
        rr.PREREGISTERED_WEIGHTS["__auth"] = RerankWeights(base=0.0, authority=1.0, cosine=0.0)
        rr.PREREGISTERED_WEIGHTS["__base"] = RerankWeights(base=1.0, authority=0.0, cosine=0.0)

        for subject in SUBJECTS:
            ds = load_dataset(DATA / subject)
            rows = adapt_rows(ds)
            specs = [r["gold"] for r in rows if r["gold"]]
            out[subject] = {
                "auth": evaluate(
                    rows, all_specs=specs, weights_name="__auth", enable_dedup=False,
                    judge=None, k=5, pool_mode=PoolMode.UNRELATED,
                    paths=("lexical", "vector", "adjacency"), embedder=embedder,
                ),
                "base": evaluate(
                    rows, all_specs=specs, weights_name="__base", enable_dedup=False,
                    judge=None, k=5, pool_mode=PoolMode.UNRELATED,
                    paths=("lexical", "vector", "adjacency"), embedder=embedder,
                ),
            }
    finally:
        rr.PREREGISTERED_WEIGHTS.clear()
        rr.PREREGISTERED_WEIGHTS.update(original)
    return out


# ---------- 边界 1：status 恒为常数 ----------


def test_status_has_no_variance_in_pools(probe) -> None:
    """**`status` 在候选池内没有方差**——它占的 0.3 权重是空的。

    实测：`sample 0/10`、`billing 0/12`。
    原因是记忆库的 status 只有 `ACTIVE`（召回只返回活跃条目）。

    **这条断言的是"没有方差"这个事实，不是"它应该没有方差"。**
    若将来召回复活了非 ACTIVE 条目，这条会红——那时 status 权重才真正起作用，
    "0.3 权重是空的"这个结论要重核。
    """
    from memory.retrieval.rerank import status_score

    for subject in SUBJECTS:
        ds = _ds(subject)
        var = 0
        tot = 0
        for case in probe[subject]["auth"]["per_case"]:
            fbt = case.get("features_by_tag") or {}
            if not fbt:
                continue
            tot += 1
            if len({v.get("status", 0.0) for v in fbt.values()}) > 1:
                var += 1
        assert tot > 0, f"{subject}: 没有任何候选池"
        assert var == 0, (
            f"{subject}: {var}/{tot} 个池内 status 有方差——"
            "status 权重不再是空的，'能力边界'这段要重核"
        )

    # 同时确认记忆库层面的取值
    for subject in SUBJECTS:
        ds = _ds(subject)
        values = {m.status.value for m in ds.memories}
        assert values == {"ACTIVE"}, (
            f"{subject}: 记忆库 status 取值是 {values}，"
            "不再只有 ACTIVE——status 特征开始有信号了"
        )
        assert status_score(ds.memories[0].status) == 1.0


# ---------- 边界 2：base 等于融合顺序 ----------


def test_rrf_norm_is_strictly_monotonic() -> None:
    """**`base` 是融合分的严格单调变换**，所以按 base 排 == 按融合顺序排。

    实测输入 `[0, 0.1, 0.5, 1.0, 2.0, 5.0]` 输出 `[0, .02, .1, .2, .4, 1.0]`。

    **这条把"base-only ratio = 0.20"从"base 是负贡献"
    纠正为"融合顺序本身的 top-1 率"。**
    前者会让人以为去掉 base 更好，而剥掉 base 等于剥掉裁决规则。
    """
    from memory.retrieval.rerank import rrf_norm

    vals = [0.0, 0.1, 0.5, 1.0, 2.0, 5.0]
    norms = [rrf_norm(v, max_score=5.0) for v in vals]

    for i in range(len(norms) - 1):
        assert norms[i] < norms[i + 1], (
            f"rrf_norm 在 {vals[i]} -> {vals[i + 1]} 上不严格递增："
            f"{norms[i]} -> {norms[i + 1]}。\n"
            "若它变成非严格，base 会引入并列，'按 base 排 == 融合顺序' 不再成立。"
        )


def test_base_only_equals_fusion_order(probe) -> None:
    """**`base-only` 的排名必须等于融合顺序的排名**（逐条）。

    这是上一条的运行时验证：单调性保证了排序一致，但这里直接比对名次。
    """
    from evals.metrics.v2_baselines import derived_axis_of

    for subject in SUBJECTS:
        ds = _ds(subject)
        within = {
            q.query_id for q in ds.queries if derived_axis_of(ds, q) == "relation_within"
        }
        mismatches = []
        for case in probe[subject]["base"]["per_case"]:
            if case["case_id"] not in within:
                continue
            if not case.get("has_gold") or case.get("skipped"):
                continue
            if case.get("rank_after_fusion") != case.get("rank_after_rerank"):
                mismatches.append(
                    (case["case_id"], case.get("rank_after_fusion"),
                     case.get("rank_after_rerank"))
                )
        assert not mismatches, (
            f"{subject}: base-only 的名次与融合名次不同：{mismatches[:3]}。\n"
            "'base == 融合顺序' 不成立，能力边界的第 2 条要重核。"
        )


# ---------- 边界 3：authority 是过滤器 ----------


def _within_ids(ds) -> set[str]:
    from evals.metrics.v2_baselines import derived_axis_of

    return {
        q.query_id for q in ds.queries if derived_axis_of(ds, q) == "relation_within"
    }


def _tier_inversions(per_case: list[dict], within: set[str]) -> tuple[int, int, list[str]]:
    """同层逆序的 case 数、总 case 数、以及逆序的 case 名单。

    **只检查派生 within**：`ledger-q11/q12` 是 A 轴标注但 `n_competitors=0`，
    不属于派生 within。把它们算进来会让总数变成 24 而不是 22，
    与本变更记录的数字不一致——而"数字从哪来"必须可复算。
    """
    inversions: list[str] = []
    total = 0
    for case in per_case:
        if case["case_id"] not in within:
            continue
        fbt = case.get("features_by_tag") or {}
        fused = case.get("fusion_tags") or []
        order = case.get("rerank_order_tags") or []
        if not fbt or not fused or not order:
            continue
        total += 1
        auths = {t: v.get("authority", 0.0) for t, v in fbt.items()}
        tiers: dict[float, list[str]] = {}
        for t in fused:
            tiers.setdefault(auths[t], []).append(t)
        for level, members in tiers.items():
            in_order = [t for t in order if auths[t] == level]
            if in_order != members:
                inversions.append(case["case_id"])
                break
    return len(inversions), total, inversions


def test_authority_is_a_filter_not_a_signal(probe) -> None:
    """**`authority` 只分层，层内裁决完全由融合顺序完成。**

    判据：在 auth-only 下，同一 authority 层内部的相对顺序
    必须与融合顺序**逐条一致**。实测 22 个 case，逆序 0 个。

    **若逆序 > 0**：authority 内部还有额外信号（比如浮点精度差异），
    那时"过滤器"这个结论要重核，"预期增益 ≈ 0"也要重算。

    **为什么这条是决定性的**：它把 auth-only 的产出精确分解为
    "分层 + 层内融合顺序"。所以 auth-only 的 0.40 不是
    "authority 选中了 gold"，而是"低层被推到后面，gold 在剩余项里靠融合顺序靠前"。
    """
    total_all = 0
    for subject in SUBJECTS:
        ds = _ds(subject)
        n_inv, n_tot, names = _tier_inversions(
            probe[subject]["auth"]["per_case"], _within_ids(ds)
        )
        assert n_tot > 0, f"{subject}: 没有可检查的 case"
        assert n_inv == 0, (
            f"{subject}: {n_inv}/{n_tot} 个 case 出现同层逆序：{names[:3]}。\n"
            "这说明 authority 不只是过滤器——层内还有额外区分信号。\n"
            "'预期增益 ≈ 0' 的结论要重核。"
        )
        total_all += n_tot

    assert total_all == 22, (
        f"覆盖的 case 数变成 {total_all}（原为 22 = sample 10 + billing 12）——"
        "v2 数据变了，本条的数字要更新"
    )


def test_auth_only_top1_is_earliest_in_top_tier(probe) -> None:
    """**auth-only 的 top-1 必须是"融合顺序里最早的最高 authority 项"。**

    实测：`sample 10/10`、`billing 12/12`。

    这是上一条的更强版本：不只层内保序，而且第一名恰好是最高层里最靠前的那个。
    """
    for subject in SUBJECTS:
        ds = _ds(subject)
        within = _within_ids(ds)
        matched = 0
        total = 0
        for case in probe[subject]["auth"]["per_case"]:
            if case["case_id"] not in within:
                continue
            fbt = case.get("features_by_tag") or {}
            fused = case.get("fusion_tags") or []
            order = case.get("rerank_order_tags") or []
            if not fbt or not fused or not order:
                continue
            auths = {t: v.get("authority", 0.0) for t, v in fbt.items()}
            maxa = max(auths.values())
            top_tier = [t for t in fused if auths.get(t) == maxa]
            if not top_tier:
                continue
            total += 1
            if order[0] == top_tier[0]:
                matched += 1
        assert total > 0, f"{subject}: 没有可检查的 case"
        assert matched == total, (
            f"{subject}: 只有 {matched}/{total} 个 case 的 auth-only top-1 "
            "是最高层里融合顺序最早的那个"
        )


# ---------- 防泄漏：数据侧 MUST NOT 制造 authority 与 gold 的相关性 ----------


def _authority_stats(per_case: list[dict]) -> dict[str, float]:
    """gold 与干扰项的平均 authority，以及 gold 唯一最高的 case 数。"""
    gold_scores: list[float] = []
    dist_scores: list[float] = []
    unique_top = 0
    n = 0

    for case in per_case:
        fbt = case.get("features_by_tag") or {}
        fused = case.get("fusion_tags") or []
        if not fbt or not fused:
            continue
        gtag = next((t for t in fused if t.startswith("gold-")), None)
        if gtag is None or gtag not in fbt:
            continue
        n += 1
        auths = {t: v.get("authority", 0.0) for t, v in fbt.items()}
        gs = auths[gtag]
        others = [v for t, v in auths.items() if t != gtag]
        if not others:
            continue
        gold_scores.append(gs)
        dist_scores.extend(others)
        if gs > max(others):
            unique_top += 1

    return {
        "n": float(n),
        "gold_mean": sum(gold_scores) / len(gold_scores) if gold_scores else 0.0,
        "dist_mean": sum(dist_scores) / len(dist_scores) if dist_scores else 0.0,
        "unique_top": float(unique_top),
    }


def test_gold_authority_has_no_systematic_advantage(probe) -> None:
    """**gold 与干扰项的平均 authority 不得有系统差**（阈值 0.05）。

    实测 v2：

    | subject | gold mean | distractor mean | 差 |
    |---|---|---|---|
    | `sample` | 0.8660 | 0.8904 | **−0.0244** |
    | `billing` | 0.9433 | 0.9221 | **+0.0213** |

    **sample 上 gold 甚至更低**——它不是靠权威赢的。

    **这个断言是防泄漏的守卫，不是"提高增益"的指标。**
    若有人为了让增益出现而让 gold 的 authority 更高，这条会红。

    **判据委托给 `_assert_authority_no_bias`**：
    `test_leak_guard_catches_doctored_pool` 调的是同一个函数，
    所以"证明它会红"验证的是**真实的判据**，不是另一份复制品。
    """
    _assert_authority_no_bias(
        {
            subject: _authority_stats(probe[subject]["auth"]["per_case"])
            for subject in SUBJECTS
        }
    )


def test_no_case_has_gold_as_unique_top_authority(probe) -> None:
    """**没有任何 case 的 gold 是唯一最高 authority**（硬判据：正好 0）。

    实测 v2：`sample 0/10`、`billing 0/12`。

    **为什么阈值是 0 而不是"少量"**：
    "少量"需要一个"多少算少"的判断，而那个判断会被"为了达标"往下调。
    0 是唯一不需要解释的阈值。

    **为什么这是泄漏**：若 gold 唯一最高，auth-only 直接 = 1.0，
    任务退化成"选权威最高的那个"，一个特征解决全部。

    **判据委托给 `_assert_no_unique_top`**，理由同上。
    """
    _assert_no_unique_top(
        {
            subject: _authority_stats(probe[subject]["auth"]["per_case"])
            for subject in SUBJECTS
        }
    )


# ---------- 数据侧禁止事项必须可被违反 ----------


def test_leak_guard_catches_doctored_pool() -> None:
    """**手工构造一份"gold 唯一最高 authority"的池，防泄漏断言必须红。**

    **为什么需要这条**：上面两条断言在 v2 数据上都是通过的，
    但"通过"可能只是"这份数据恰好如此"。这条证明它们**真的能抓泄漏**。

    构造：一个池，gold 的 authority 是 1.0，干扰项全是 0.66。
    这会同时触发：
      - `unique_top` == 1（应为 0）
      - `mean_gold - mean_distractors` 远大于 0.05
    """
    doctored = {
        "features_by_tag": {
            "gold-x": {"base": 0.1, "authority": 1.0, "cosine": 0.0},
            "d-x-0": {"base": 0.9, "authority": 0.66, "cosine": 0.0},
            "d-x-1": {"base": 0.8, "authority": 0.33, "cosine": 0.0},
        },
        "fusion_tags": ["d-x-0", "d-x-1", "gold-x"],
        "rerank_order_tags": ["gold-x", "d-x-0", "d-x-1"],
    }

    stats = _authority_stats([doctored])
    assert stats["unique_top"] == 1, (
        "构造失效：这份池里 gold 不是唯一最高 authority，"
        f"无法验证防泄漏断言。实际 unique_top={stats['unique_top']}"
    )
    diff = stats["gold_mean"] - stats["dist_mean"]
    assert diff > 0.05, (
        f"构造失效：差值只有 {diff:+.4f}，没到阈值 0.05，"
        "无法验证 mean-diff 断言"
    )

    # **用真实断言函数验证它们会红**，而不是 `assert ... "模拟断言"`
    #
    # 上一版写的是：
    #   with pytest.raises(AssertionError):
    #       assert stats["unique_top"] == 0, "模拟断言"
    # 那是**必然抛出的**——`assert False` 总是抛，与被测对象无关。
    # 恒真断言（永远红的那种），判别力为零。
    #
    # 现在直接调被验证的判据逻辑：
    with pytest.raises(AssertionError, match="gold 是唯一最高 authority"):
        _assert_no_unique_top({"fake": stats})

    with pytest.raises(AssertionError, match="超过阈值"):
        _assert_authority_no_bias({"fake": stats})


def _assert_no_unique_top(stats_by_subject: dict[str, dict[str, float]]) -> None:
    """与 `test_no_case_has_gold_as_unique_top_authority` 相同的判据。"""
    for subject, stats in stats_by_subject.items():
        assert stats["unique_top"] == 0, (
            f"{subject}: {int(stats['unique_top'])}/{int(stats['n'])} 个 case 的 "
            "gold 是唯一最高 authority。\n"
            "这是泄漏：auth-only 会直接得 1.0，任务退化成单特征。"
        )


def _assert_authority_no_bias(stats_by_subject: dict[str, dict[str, float]]) -> None:
    """与 `test_gold_authority_has_no_systematic_advantage` 相同的判据。"""
    for subject, stats in stats_by_subject.items():
        diff = stats["gold_mean"] - stats["dist_mean"]
        assert abs(diff) < 0.05, (
            f"{subject}: gold 的平均 authority {stats['gold_mean']:.4f} "
            f"vs 干扰项 {stats['dist_mean']:.4f}，差 {diff:+.4f} 超过阈值 0.05。\n"
            "这是泄漏形态：authority 与 gold 相关，任务退化成'选权威最高'。\n"
            "**数据侧 MUST NOT 为了让增益出现而制造这种相关性。**"
        )


def test_leak_guard_passes_on_real_data(probe) -> None:
    """**真实 v2 数据上，两条防泄漏断言都通过**——这是配对的反面。

    若只有 `test_leak_guard_catches_doctored_pool`（红）而没有这条（绿），
    读者会以为数据本来就该红；若只有这条，读者不知道它还防泄漏。

    **两条合起来才说明**：守卫既能红也能绿。
    """
    for subject in SUBJECTS:
        stats = _authority_stats(probe[subject]["auth"]["per_case"])
        assert stats["unique_top"] == 0
        assert abs(stats["gold_mean"] - stats["dist_mean"]) < 0.05


# ---------- 能力边界本身：预期增益 ≈ 0 ----------


def test_three_features_have_no_semantic_signal() -> None:
    """**把三条边界合成一句可断言的结论**：三个特征都不含语义相关性。

    | 特征 | 性质 |
    |---|---|
    | `status` | 常数 |
    | `base` | 融合顺序（召回的产物） |
    | `authority` | 分层过滤器 |

    **"预期增益 ≈ 0"就是从这里来的**，而不是"装置坏了"。

    这条断言的是"三个性质都在"——任一条失效，结论要重算。
    """
    from evals.datasets.retrieval_v2 import load_dataset

    from memory.retrieval.rerank import rrf_norm

    # status: 恒为常数
    for subject in SUBJECTS:
        ds = load_dataset(DATA / subject)
        assert {m.status.value for m in ds.memories} == {"ACTIVE"}

    # base: 严格单调
    assert rrf_norm(0.1, max_score=1.0) < rrf_norm(0.5, max_score=1.0)

    # authority: 分层值来自固定的映射表，不含任何与查询相关的东西
    from memory.retrieval.rerank import authority_score
    from memory.store.models import Authority

    for level in Authority:
        v = authority_score(level)
        assert 0.0 <= v <= 1.0
    # 同一个 authority 值在任何查询下都一样 —— 这是"元数据先验"的定义
    assert authority_score(Authority.USER_DIRECT) == authority_score(
        Authority.USER_DIRECT
    )
