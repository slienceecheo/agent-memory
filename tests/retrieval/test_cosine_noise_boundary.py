"""cosine 的噪声边界：embedding 非确定性会不会让名次翻转？

## 为什么需要

cosine 的四条泄漏判据全部通过，但它依赖 embedding 的稳定性。
`AGENTS.md` 登记了"embedding 非确定性"，必须先量化它对名次的影响。

## 三条实测

**1. 非确定性只在缓存未命中时出现**

| 情形 | 结果 |
|---|---|
| 缓存命中 | `max|diff| = 0.00e+00`，`cos = 1.0000000000` |
| 缓存未命中 | `cos = 0.9971`（约 4.36°） |

**2. 向量扰动对 `cos(query, candidate)` 的影响**

旋转候选向量 4.36°，30 个样本：

| 量 | 值 |
|---|---|
| 均值 | 0.0019 |
| P95 | 0.0051 |
| **最大** | **0.0061** |

**3. `cosine_gap`（gold − 最强干扰）**

| subject | 正 gap 最小 | `gap < 0.01` | 负 gap（已排错） |
|---|---|---|---|
| `sample` | 0.0136 | **0** | **1** |
| `billing` | 0.0447 | **0** | **2** |

## 阈值为什么是 0.01 不是 0.006

实测噪声最大值 **0.0061**，而 0.006 **小于**它——判据会卡在边界上。
0.01 是它的 1.6 倍。

## 敏感度归因

| subject | 池大小 | 正 gap 最小 | 与噪声之比 |
|---|---|---|---|
| `billing` | **9**（更小） | 0.0447 | 7.3× |
| `sample` | **12–14**（更大） | 0.0136 | 2.2× |

**池更小的 billing 反而更稳定** -> 决定敏感度的是 tie 紧密度，不是池大小。
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data" / "retrieval-v2"

#: 实测噪声上界（旋转 4.36° 后的 |Δcos| 最大值）。
MEASURED_NOISE_MAX = 0.0061

#: 未来装置变更用的不稳定阈值。**必须大于实测噪声最大值。**
UNSTABLE_THRESHOLD = 0.01

#: 报告 §6.12.4 的数字。
EXPECTED = {
    "sample": {
        "min_positive_gap": 0.0136,
        "min_gap_case": "ledger-q8",
        "unstable": 0,
        "wrong": 1,
        "wrong_cases": ["ledger-q2"],
        "n": 10,
        "pool_size": 14,
    },
    "billing": {
        "min_positive_gap": 0.0447,
        "min_gap_case": "billing-c2",
        "unstable": 0,
        "wrong": 2,
        "wrong_cases": ["billing-a2", "billing-c3"],
        "n": 12,
        "pool_size": 9,
    },
}


def _cos(a, b) -> float:
    va = np.asarray(a, dtype=float)
    vb = np.asarray(b, dtype=float)
    na, nb = np.linalg.norm(va), np.linalg.norm(vb)
    if na == 0 or nb == 0:
        return 0.0
    return float(va @ vb / (na * nb))


def _unit(v):
    v = np.asarray(v, dtype=float)
    return v / np.linalg.norm(v)


@pytest.fixture(scope="module")
def embedder():
    from memory.config import Settings
    from memory.embedding.cache import EmbeddingCache
    from memory.embedding.dashscope import DashScopeEmbedder

    settings = Settings.load()
    settings.cache_dir.mkdir(parents=True, exist_ok=True)
    return DashScopeEmbedder(
        settings=settings, cache=EmbeddingCache(settings.cache_dir / "cache.db")
    )


@pytest.fixture(scope="module")
def measured(embedder):
    """现场重跑：cosine_gap 分布 + 旋转敏感度。"""
    from evals.datasets.retrieval_v2 import load_dataset
    from evals.metrics.v2_baselines import derived_axis_of

    out: dict[str, dict] = {}

    for subject in ("sample", "billing"):
        ds = load_dataset(DATA / subject)
        within = {
            q.query_id
            for q in ds.queries
            if derived_axis_of(ds, q) == "relation_within"
        }

        gaps: list[tuple[str, float]] = []
        for q in ds.queries:
            if q.query_id not in within:
                continue
            qv = embedder.embed(q.query, text_type="query")
            gold = ds.memory(q.gold_memory_id)
            others = [
                m
                for m in ds.memories
                if m.memory_id != gold.memory_id
                and m.subject == gold.subject
                and m.relation == gold.relation
            ]
            if not others:
                continue
            gc = _cos(qv, embedder.embed(gold.memory_text, text_type="document"))
            dc = [
                _cos(qv, embedder.embed(o.memory_text, text_type="document"))
                for o in others
            ]
            gaps.append((q.query_id, gc - max(dc)))

        positive = [(c, g) for c, g in gaps if g > 0]
        negative = [(c, g) for c, g in gaps if g <= 0]
        positive.sort(key=lambda x: x[1])

        out[subject] = {
            "n": len(gaps),
            "min_positive_gap": positive[0][1] if positive else 0.0,
            "min_gap_case": positive[0][0] if positive else "",
            "unstable": sum(1 for _, g in positive if g < UNSTABLE_THRESHOLD),
            "wrong": len(negative),
            "wrong_cases": sorted(c for c, _ in negative),
            "pool_size": max(
                len(
                    [
                        m
                        for m in ds.memories
                        if m.subject == ds.memory(q.gold_memory_id).subject
                    ]
                )
                for q in ds.queries
                if q.query_id in within
            ),
        }

    return out


@pytest.fixture(scope="module")
def rotation_deltas(embedder):
    """旋转候选向量 4.36°，测 cos(query, candidate) 的实际变化。"""
    from evals.datasets.retrieval_v2 import load_dataset
    from evals.metrics.v2_baselines import derived_axis_of

    theta = float(np.arccos(0.9971))
    rng = np.random.default_rng(0)
    ds = load_dataset(DATA / "sample")
    within = {
        q.query_id for q in ds.queries if derived_axis_of(ds, q) == "relation_within"
    }

    deltas: list[float] = []
    for q in ds.queries:
        if q.query_id not in within:
            continue
        qv = np.asarray(embedder.embed(q.query, text_type="query"), dtype=float)
        gold = ds.memory(q.gold_memory_id)
        others = [
            m
            for m in ds.memories
            if m.memory_id != gold.memory_id
            and m.subject == gold.subject
            and m.relation == gold.relation
        ]
        for m in [gold, *others[:2]]:
            v = _unit(embedder.embed(m.memory_text, text_type="document"))
            base = _cos(qv, v)
            r = rng.normal(size=v.shape)
            r = r - np.dot(r, v) * v
            if np.linalg.norm(r) < 1e-9:
                continue
            r = r / np.linalg.norm(r)
            rotated = np.cos(theta) * v + np.sin(theta) * r
            deltas.append(abs(_cos(qv, rotated) - base))

    return deltas


# ---------- 噪声上界 ----------


def test_cache_hit_is_bitwise_identical(embedder) -> None:
    """**缓存命中时逐位相同。**

    这是"重跑可复现"的基础：`run_retrieval` 走缓存，
    所以同一份产物重跑不会变。
    """
    from evals.datasets.retrieval_v2 import load_dataset

    ds = load_dataset(DATA / "sample")
    text = ds.memories[0].memory_text
    v1 = np.asarray(embedder.embed(text, text_type="document"), dtype=float)
    v2 = np.asarray(embedder.embed(text, text_type="document"), dtype=float)

    assert np.max(np.abs(v1 - v2)) == 0.0, (
        "缓存命中时两次调用给出不同向量——"
        "那说明缓存没生效，'重跑可复现'这个前提不成立"
    )


def test_rotation_delta_within_bound(rotation_deltas) -> None:
    """**向量扰动 4.36° 后，`|Δcos|` 必须 <= 0.01。**

    实测：均值 0.0019、P95 0.0051、**最大 0.0061**。

    **若这个上界超过 0.01**，阈值要跟着改——
    所以这条断言的是"噪声上界"，不是"某个具体值"。
    """
    assert rotation_deltas, "没有可用的旋转样本"
    arr = np.asarray(rotation_deltas)
    assert arr.max() <= UNSTABLE_THRESHOLD, (
        f"旋转后的 |Δcos| 最大值 {arr.max():.4f} 超过阈值 "
        f"{UNSTABLE_THRESHOLD}——阈值要调大"
    )
    # 同时记录实测上界，防止有人把上界当成 0
    assert arr.max() > 0.001, (
        f"|Δcos| 最大值只有 {arr.max():.6f}，小到不像真实扰动——"
        "检查旋转是否真的应用了"
    )


def test_threshold_exceeds_measured_noise() -> None:
    """**阈值必须大于实测噪声最大值。**

    实测最大值 0.0061，阈值 0.01 -> 1.6 倍。

    **若阈值 <= 0.0061**，判据会落在自己的噪声边界上：
    同样的数据，噪声稍微大一点就会产生不同的"稳定/不稳定"分类。
    """
    assert UNSTABLE_THRESHOLD > MEASURED_NOISE_MAX, (
        f"阈值 {UNSTABLE_THRESHOLD} 不大于实测噪声最大值 "
        f"{MEASURED_NOISE_MAX}——判据会卡在边界上抖动"
    )
    ratio = UNSTABLE_THRESHOLD / MEASURED_NOISE_MAX
    assert ratio >= 1.5, (
        f"阈值只有噪声的 {ratio:.2f} 倍，余量不足 1.5 倍"
    )


# ---------- cosine_gap 分布 ----------


def test_no_case_falls_in_noise_band(measured) -> None:
    """**没有 case 落在噪声带内**（正 gap < 0.01）。

    实测两个 subject 都是 **0**。

    **若出现 > 0**：那个 case 的名次可能因 embedding 非确定性翻转，
    不能单独支撑结论。
    """
    for subject in ("sample", "billing"):
        got = measured[subject]
        assert got["unstable"] == 0, (
            f"{subject}: {got['unstable']}/{got['n']} 个 case 的正 gap < "
            f"{UNSTABLE_THRESHOLD}——它们的名次可能不稳定"
        )


def test_min_positive_gap_matches_report(measured) -> None:
    """**正 gap 的最小值必须与报告一致。**

    | subject | 最小值 | case |
    |---|---|---|
    | `sample` | **0.0136** | `ledger-q8` |
    | `billing` | **0.0447** | `billing-c2` |

    **这是"离翻转有多远"的量化**。
    """
    for subject in ("sample", "billing"):
        got = measured[subject]
        want = EXPECTED[subject]
        assert got["min_gap_case"] == want["min_gap_case"], (
            f"{subject}: 最小正 gap 的 case 是 {got['min_gap_case']}，"
            f"报告写 {want['min_gap_case']}"
        )
        assert abs(got["min_positive_gap"] - want["min_positive_gap"]) < 1e-3, (
            f"{subject}: 最小正 gap {got['min_positive_gap']:.4f}，"
            f"报告写 {want['min_positive_gap']}"
        )


def test_wrong_cases_are_counted_separately(measured) -> None:
    """**负 gap（已排错）必须与"不稳定"分开计数。**

    | subject | 负 gap | 是哪些 |
    |---|---|---|
    | `sample` | **1** | `ledger-q2` |
    | `billing` | **2** | `a2`、`c3` |

    **若把负 gap 算作"不稳定"**，会得出"`billing` 有 17% 不稳定"——
    而那 17% 是 cosine 排错了，不是噪声。

    **处置相反**：不稳定可排除，排错不能排除。
    """
    for subject in ("sample", "billing"):
        got = measured[subject]
        want = EXPECTED[subject]
        assert got["wrong"] == want["wrong"], (
            f"{subject}: 负 gap 有 {got['wrong']} 条，报告写 {want['wrong']}"
        )
        assert got["wrong_cases"] == want["wrong_cases"], (
            f"{subject}: 负 gap 的 case 是 {got['wrong_cases']}，"
            f"报告写 {want['wrong_cases']}"
        )


def test_sensitivity_is_tie_not_pool_size(measured) -> None:
    """**敏感度由 tie 紧密度决定，不是池大小。**

    | subject | 池大小 | 正 gap 最小 | 与噪声之比 |
    |---|---|---|---|
    | `billing` | **9**（更小） | 0.0447 | **7.3×** |
    | `sample` | **14**（更大） | 0.0136 | **2.2×** |

    **池更小的 `billing` 反而更稳定**——所以"池小所以名次间隔小"不成立。
    """
    small_pool = measured["billing"]
    large_pool = measured["sample"]

    assert small_pool["pool_size"] < large_pool["pool_size"], (
        f"前提不成立：billing 池 {small_pool['pool_size']} 不小于 "
        f"sample 池 {large_pool['pool_size']}"
    )
    assert small_pool["min_positive_gap"] > large_pool["min_positive_gap"], (
        f"池更小的 billing 的 gap（{small_pool['min_positive_gap']:.4f}）"
        f"不大于池更大的 sample（{large_pool['min_positive_gap']:.4f}）——"
        "'敏感度由 tie 决定'这个结论要重核"
    )


# ---------- 报告内容 ----------


def _sub() -> str:
    report = (ROOT / "docs" / "reports" / "v2-what-it-measures.md").read_text(
        encoding="utf-8"
    )
    body = report.split("## 6. 结论 5")[1].split("\n## ")[0]
    return body.split("#### 6.12.4 ")[1].split("#### 6.12.5")[0]


def test_report_states_both_cache_states() -> None:
    """**报告必须区分"缓存命中"与"未命中"。**

    只写"有非确定性"会让读者以为"重跑会变"——而实测缓存命中是逐位相同的。
    """
    sub = _sub()
    assert "缓存命中" in sub, "§6.12.4 必须写出缓存命中的情形"
    assert "0.00e+00" in sub or "逐位" in sub, (
        "§6.12.4 必须给出缓存命中的结果（逐位相同）"
    )
    assert "0.9971" in sub, "§6.12.4 必须给出缓存未命中的 cos"


def test_report_states_threshold_rationale() -> None:
    """**报告必须写明阈值 0.01 与"为什么不是 0.006"。**

    实测噪声最大值 0.0061，而 0.006 **小于**它。
    若不写这个理由，读者会以为 0.006 更"精确"。

    **判据定位到阈值对比表的那两行**：`0.0061` 在 §6.12.4 里出现多次
    （噪声表、阈值讨论），全局 `in` 会被另一处顶替。
    """
    sub = _sub()
    assert "0.01" in sub, "§6.12.4 必须给出阈值 0.01"

    rows = [ln.strip() for ln in sub.splitlines() if ln.strip().startswith("|")]
    rejected = [r for r in rows if r.startswith("| 0.006 |")]
    adopted = [r for r in rows if r.startswith("| **0.01** |")]

    assert rejected, "§6.12.4 的阈值对比表缺少 `| 0.006 |` 那一行"
    assert adopted, "§6.12.4 的阈值对比表缺少 `| **0.01** |` 那一行"
    assert "0.0061" in rejected[0], (
        f"被否决的那行必须写出与 0.0061 的关系：{rejected[0][:80]}"
    )
    assert "❌" in rejected[0], "0.006 那行必须标记为 ❌"
    assert "✅" in adopted[0], "0.01 那行必须标记为 ✅"


def test_report_separates_wrong_from_unstable() -> None:
    """**报告必须把"排错"与"不稳定"分开。**"""
    sub = _sub()
    assert "排错" in sub or "负 gap" in sub, (
        "§6.12.4 必须提到负 gap（排错）"
    )
    for cid in ("ledger-q2", "billing-a2", "billing-c3"):
        assert cid in sub, f"§6.12.4 必须点名排错的 case {cid}"


def test_report_registers_future_fields() -> None:
    """**报告必须登记未来要加的字段与验收。**

    若不写，下次装置变更会漏掉 `cosine_gap`，
    而它是"名次有多稳"的唯一依据。

    **`cosine_unstable` 已改成 `cosine_band` 三态**（本变更修正）：
    布尔值会把"可能翻转"与"已排错"压成一个，而两者处置相反。
    """
    sub = _sub()
    rows = [ln.strip() for ln in sub.splitlines() if ln.strip().startswith("|")]

    gap_row = [r for r in rows if "`cosine_gap`" in r and "❌" in r]
    band_row = [r for r in rows if "`cosine_band`" in r and "❌" in r]
    tie_row = [r for r in rows if "`tie_at_top1`" in r and "✅" in r]

    assert gap_row, "§6.12.4 的字段表缺少 `cosine_gap` 那一行（标记 ❌）"
    assert band_row, (
        "§6.12.4 的字段表缺少 `cosine_band` 那一行（标记 ❌）。\n"
        "注意：旧的 `cosine_unstable` 布尔已被三态取代。"
    )
    assert tie_row, "§6.12.4 的字段表必须把 `tie_at_top1` 标为已有（✅）"

    # 三态的三个取值必须都出现
    body = _sub()
    for v in ("stable", "noise", "negative"):
        assert v in body, f"§6.12.4 必须给出 band 取值 {v}"
