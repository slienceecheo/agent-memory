"""`cosine_band` 三态 + 扰动验收。

## 为什么不是"稳定 case 的 SEH@1 == 全部 case 的 SEH@1"

**两种读法都不成立**：

| 读法 | sample | billing | 失效 |
|---|---|---|---|
| 含负 gap（`gap < 0.01`） | 9/9 = 1.0000 vs 0.9000 | 10/10 = 1.0000 vs 0.8333 | **永远红** |
| 只算噪声带（`0 < gap < 0.01`） | 集合 == 全集 | 集合 == 全集 | **恒真** |

**读法 1 的逻辑错误**：排除负 gap（已排错）后剩下全是命中项，
`SEH@1` 必然是 `1.0`——等于"先把错的删掉再报准确率"。

## 正确的验收：扰动

**稳定 case（`gap >= 0.01`）在 ±0.0061 的扰动下 top-1 不翻转。**

实测：`sample` 9 条 × 300 次 = 2700，`billing` 10 条 × 300 次 = 3000，
**合计 5700 次扰动，0 次翻转**。

## 三态 vs 布尔

`cosine_unstable = gap < 0.01` 会把负 gap（已排错）也算作"不稳定"。
而两者的处置相反：`noise` 排除出结论，`negative` 不能排除。
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data" / "retrieval-v2"

#: 不稳定阈值（实测噪声最大值 0.0061 的 1.6 倍）。
BAND_THRESHOLD = 0.01

#: 扰动幅度 = 实测噪声最大值。
NOISE = 0.0061

#: 扰动次数（固定种子 -> 可复现）。
TRIALS = 300

EXPECTED = {
    "sample": {
        "n": 10,
        "stable": 9,
        "noise": 0,
        "negative": 1,
        "negative_cases": ["ledger-q2"],
        "min_stable_gap": 0.0136,
        "full_top1": 9,
        "stable_top1": 9,
    },
    "billing": {
        "n": 12,
        "stable": 10,
        "noise": 0,
        "negative": 2,
        "negative_cases": ["billing-a2", "billing-c3"],
        "min_stable_gap": 0.0447,
        "full_top1": 10,
        "stable_top1": 10,
    },
}


def _cos(a, b) -> float:
    va = np.asarray(a, dtype=float)
    vb = np.asarray(b, dtype=float)
    na, nb = np.linalg.norm(va), np.linalg.norm(vb)
    if na == 0 or nb == 0:
        return 0.0
    return float(va @ vb / (na * nb))


def _band(gap: float) -> str:
    if gap < 0:
        return "negative"
    if gap < BAND_THRESHOLD:
        return "noise"
    return "stable"


@pytest.fixture(scope="module")
def cases():
    """现场算每条 case 的 gold/distractor cosine 与 band。"""
    from evals.datasets.retrieval_v2 import load_dataset
    from evals.metrics.v2_baselines import derived_axis_of

    from memory.config import Settings
    from memory.embedding.cache import EmbeddingCache
    from memory.embedding.dashscope import DashScopeEmbedder

    settings = Settings.load()
    settings.cache_dir.mkdir(parents=True, exist_ok=True)
    emb = DashScopeEmbedder(
        settings=settings, cache=EmbeddingCache(settings.cache_dir / "cache.db")
    )

    out: dict[str, list[dict]] = {}
    for subject in ("sample", "billing"):
        ds = load_dataset(DATA / subject)
        within = {
            q.query_id
            for q in ds.queries
            if derived_axis_of(ds, q) == "relation_within"
        }
        rows: list[dict] = []
        for q in ds.queries:
            if q.query_id not in within:
                continue
            qv = emb.embed(q.query, text_type="query")
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
            gc = _cos(qv, emb.embed(gold.memory_text, text_type="document"))
            dc = [
                _cos(qv, emb.embed(o.memory_text, text_type="document"))
                for o in others
            ]
            gap = gc - max(dc)
            rows.append(
                {
                    "cid": q.query_id,
                    "gold": gc,
                    "dists": dc,
                    "gap": gap,
                    "band": _band(gap),
                    "hit": gc > max(dc),
                }
            )
        out[subject] = rows
    return out


# ---------- 三态 ----------


def test_band_is_three_states(cases) -> None:
    """**`cosine_band` 必须是三态，且实际用到两种。**

    | 区间 | band |
    |---|---|
    | `gap >= 0.01` | `stable` |
    | `0 <= gap < 0.01` | `noise` |
    | `gap < 0` | `negative` |

    **这条断言的是"三态确实区分了两种坏"**：
    若所有 case 都是 `stable`，那三态没有存在意义。
    """
    for subject in ("sample", "billing"):
        bands = {c["band"] for c in cases[subject]}
        assert "stable" in bands, f"{subject}: 没有 stable case"
        assert "negative" in bands, (
            f"{subject}: 没有 negative case——三态退化成了两态"
        )
        assert bands <= {"stable", "noise", "negative"}, (
            f"{subject}: 出现了未知 band {bands}"
        )


def test_band_counts_match_report(cases) -> None:
    """**三态的条数必须与报告一致。**

    | subject | stable | noise | negative |
    |---|---|---|---|
    | `sample` | **9** | **0** | **1** |
    | `billing` | **10** | **0** | **2** |
    """
    for subject in ("sample", "billing"):
        want = EXPECTED[subject]
        got = {
            b: sum(1 for c in cases[subject] if c["band"] == b)
            for b in ("stable", "noise", "negative")
        }
        for b in ("stable", "noise", "negative"):
            assert got[b] == want[b], (
                f"{subject}/{b}: {got[b]}，报告写 {want[b]}"
            )


def test_negative_cases_are_named(cases) -> None:
    """**负 gap 的 case 必须点名。**

    | subject | 名单 |
    |---|---|
    | `sample` | `ledger-q2` |
    | `billing` | `billing-a2`、`billing-c3` |

    **它们是"cosine 已排错"，不是"不稳定"**——
    处置相反：`noise` 可排除，`negative` 不能排除。
    """
    for subject in ("sample", "billing"):
        got = sorted(c["cid"] for c in cases[subject] if c["band"] == "negative")
        want = EXPECTED[subject]["negative_cases"]
        assert got == want, f"{subject}: 负 gap 是 {got}，报告写 {want}"


def test_min_stable_gap_matches_report(cases) -> None:
    """**稳定 case 的最小 gap 必须与报告一致。**"""
    for subject in ("sample", "billing"):
        stable = [c["gap"] for c in cases[subject] if c["band"] == "stable"]
        assert stable, f"{subject}: 没有 stable case"
        got = min(stable)
        want = EXPECTED[subject]["min_stable_gap"]
        assert abs(got - want) < 1e-3, (
            f"{subject}: 最小 stable gap {got:.4f}，报告写 {want}"
        )


# ---------- 旧的"子集分数相等"判据必须不成立 ----------


def test_subset_equality_criterion_is_broken(cases) -> None:
    """**记录"子集分数相等"这个判据的两种失效方式。**

    | 读法 | 结果 |
    |---|---|
    | 含负 gap | 子集只剩命中项 -> `SEH@1 = 1.0` -> **永不相等** |
    | 只算噪声带 | 噪声带为空 -> 集合 == 全集 -> **恒真** |

    **这条断言的是"那个判据不成立"这个事实**，
    防有人重新提出它。
    """
    for subject in ("sample", "billing"):
        rows = cases[subject]
        full_n = len(rows)
        full_hit = sum(1 for c in rows if c["hit"])

        # 读法 1：含负 gap（gap < 0.01）
        s1 = [c for c in rows if c["gap"] >= BAND_THRESHOLD]
        s1_hit = sum(1 for c in s1 if c["hit"])
        assert full_hit / full_n != s1_hit / len(s1), (
            f"{subject}: 读法1 的 SEH@1 竟然相等——'永远红'这个结论不成立"
        )
        # 而且必须是 1.0（排除失败项后的必然结果）
        assert s1_hit / len(s1) == 1.0, (
            f"{subject}: 读法1 的 SEH@1 不是 1.0——"
            f"那说明 stable 集合里还有未命中的项（{s1_hit}/{len(s1)}）"
        )

        # 读法 2：只算噪声带
        s2 = [c for c in rows if not (0 <= c["gap"] < BAND_THRESHOLD)]
        assert len(s2) == full_n, (
            f"{subject}: 读法2 的集合不等于全集——那它就不是恒真"
        )


# ---------- 扰动验收 ----------


def test_stable_cases_do_not_flip_under_noise(cases) -> None:
    """**稳定 case 在 ±0.0061 的扰动下 top-1 不翻转。**

    **这才是"稳定性"该问的问题**，不是"子集分数是否相等"。

    实测：`sample` 9 条 × 300 次 = 2700，`billing` 10 条 × 300 次 = 3000，
    **合计 5700 次扰动，0 次翻转**。

    **扰动的是"分"不是"向量"**：这是保守近似。
    真实扰动幅度取决于夹角（最大 0.0061），而均匀扰动覆盖最坏情况。
    **保守方向安全**：若均匀扰动下 0 翻转，真实扰动也不会翻转。
    """
    rng = np.random.default_rng(0)

    for subject in ("sample", "billing"):
        stable = [c for c in cases[subject] if c["band"] == "stable"]
        assert stable, f"{subject}: 没有 stable case"

        flips = 0
        for _ in range(TRIALS):
            for c in stable:
                g = c["gold"] + rng.uniform(-NOISE, NOISE)
                d = [x + rng.uniform(-NOISE, NOISE) for x in c["dists"]]
                if (g > max(d)) != c["hit"]:
                    flips += 1

        total = TRIALS * len(stable)
        assert flips == 0, (
            f"{subject}: {total} 次扰动中有 {flips} 次翻转——"
            "稳定 case 在噪声下不稳定，'stable' 这个 band 的判据要重核"
        )


def test_noise_ratio_is_registered(cases) -> None:
    """**噪声 / 最小 gap 的比值必须登记。**

    | subject | 最小 gap | 噪声/最小 gap |
    |---|---|---|
    | `sample` | 0.0136 | **0.45** |
    | `billing` | 0.0447 | **0.14** |

    **`sample` 的噪声是最小 gap 的 45%**——离翻转只剩 55% 余量。
    这比 `billing` 紧得多，必须写进报告。
    """
    for subject in ("sample", "billing"):
        stable = [c["gap"] for c in cases[subject] if c["band"] == "stable"]
        ratio = NOISE / min(stable)
        if subject == "sample":
            assert 0.4 < ratio < 0.5, (
                f"sample: 噪声/gap = {ratio:.2f}，报告写 0.45"
            )
        else:
            assert 0.1 < ratio < 0.2, (
                f"billing: 噪声/gap = {ratio:.2f}，报告写 0.14"
            )


# ---------- 报告内容 ----------


def _sub(tag: str, next_tag: str) -> str:
    report = (ROOT / "docs" / "reports" / "v2-what-it-measures.md").read_text(
        encoding="utf-8"
    )
    body = report.split("## 6. 结论 5")[1].split("\n## ")[0]
    return body.split(f"##### {tag} ")[1].split(f"##### {next_tag}")[0]


def test_report_states_two_failed_readings() -> None:
    """**报告必须记录"子集分数相等"这个判据的两种失效方式。**

    若不写，下一个人会重新提出它。

    **判据定位到失效表的两行**：`1.0000` 在 §6.12.4.3 里出现 3 次，
    用 `"1.0000" in sub` 会在删掉"永远红"那格后仍然通过。
    """
    sub = _sub("6.12.4.3", "6.12.4.4")
    rows = [ln.strip() for ln in sub.splitlines() if ln.strip().startswith("|")]

    always_red = [r for r in rows if "含负 gap" in r]
    always_true = [r for r in rows if "只算噪声带" in r]

    assert always_red, "§6.12.4.3 的失效表缺少「含负 gap」那一行"
    assert always_true, "§6.12.4.3 的失效表缺少「只算噪声带」那一行"

    assert "永远红" in always_red[0], (
        f"「含负 gap」那行必须标「永远红」：{always_red[0][:80]}"
    )
    assert "恒真" in always_true[0], (
        f"「只算噪声带」那行必须标「恒真」：{always_true[0][:80]}"
    )


def test_report_states_perturbation_acceptance() -> None:
    """**报告必须写出扰动验收与实测结果。**

    **判据定位到实测表与合计句**：`扰动` 在 §6.12.4.3 出现 7 次，
    用 `"扰动" in sub` 几乎恒真。
    """
    sub = _sub("6.12.4.3", "6.12.4.4")
    rows = [ln.strip() for ln in sub.splitlines() if ln.strip().startswith("|")]

    sample_row = [r for r in rows if "`sample`" in r and "2700" in r]
    billing_row = [r for r in rows if "`billing`" in r and "3000" in r]

    assert sample_row, "§6.12.4.3 的实测表缺少 sample 行（含 2700）"
    assert billing_row, "§6.12.4.3 的实测表缺少 billing 行（含 3000）"
    assert "**0**" in sample_row[0], (
        f"sample 行必须写出 0 次翻转：{sample_row[0][:80]}"
    )
    assert "**0**" in billing_row[0], (
        f"billing 行必须写出 0 次翻转：{billing_row[0][:80]}"
    )
    assert "**合计 5700 次扰动，0 次翻转。**" in sub, (
        "§6.12.4.3 必须写出「合计 5700 次扰动，0 次翻转」"
    )


def test_report_states_three_state_band() -> None:
    """**报告必须写出 `cosine_band` 三态与判据。**

    **判据定位到字段表的 `cosine_band` 那一行**：
    `cosine_band` 在 §6.12.4.6 里出现 2 次（字段表、区间表）。
    """
    sub = _sub("6.12.4.6", "6.12.5")
    rows = [ln.strip() for ln in sub.splitlines() if ln.strip().startswith("|")]

    field_row = [r for r in rows if "`cosine_band`" in r and "❌" in r]
    assert field_row, "§6.12.4.6 的字段表缺少 `cosine_band` 那一行（标记 ❌）"

    # 三态的三个取值必须在字段行里
    for v in ("stable", "noise", "negative"):
        assert v in field_row[0], (
            f"`cosine_band` 那行必须列出 {v}：{field_row[0][:90]}"
        )

    assert "不得" in sub or "MUST NOT" in sub, (
        "§6.12.4.6 必须说明不得用布尔值的理由"
    )


def test_report_forbids_uniform_naming() -> None:
    """**报告必须写明 `(0,0,1)` 不得叫 `uniform`。**

    `uniform` 暗示"各项权重相等"，而 `(0,0,1)` 是"只有一项"。
    且与 `disabled_weights()` 的 `(1,0,0)` 语义冲突。

    **判据定位到命名表的 `(0,0,1)` 那一行**。
    """
    report = (ROOT / "docs" / "reports" / "v2-what-it-measures.md").read_text(
        encoding="utf-8"
    )
    body = report.split("## 6. 结论 5")[1].split("\n## ")[0]
    sub = body.split("#### 6.12.5 ")[1].split("### 6.13")[0]
    rows = [ln.strip() for ln in sub.splitlines() if ln.strip().startswith("|")]

    naming_row = [
        r
        for r in rows
        if "`(0,0,1)`" in r and "`cosine_only`" in r
    ]
    assert naming_row, (
        "§6.12.5 的命名表缺少 `(0,0,1)` -> `cosine_only` 那一行。\n"
        "注意：`single_signal` 是备选名，不能替代 `cosine_only` 那一行的判据。"
    )
    assert "uniform" in sub, "§6.12.5 必须点名 `uniform` 这个被否决的命名"
    assert "不得" in sub or "MUST NOT" in sub, (
        "§6.12.5 必须明确禁止把 `(0,0,1)` 命名为 `uniform`"
    )
