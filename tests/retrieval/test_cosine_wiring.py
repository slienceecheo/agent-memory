"""commit ② 的验收：cosine 分与产物字段。

对应 tasks 3.5 / 3.6 / 3.8 / 3.10 / 3.11。

**核心判据是"独立取一次分再比"**：不能用 `features_by_tag` 里的值与它自己比，
那是恒真。
"""

from __future__ import annotations

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data" / "retrieval-v2"
SUBJECTS = ("sample", "billing")


@pytest.fixture(scope="module")
def env():
    from evals.datasets.retrieval_v2 import load_dataset
    from evals.datasets.v2_adapter import rows as adapt_rows

    from memory.config import Settings
    from memory.embedding.cache import EmbeddingCache
    from memory.embedding.dashscope import DashScopeEmbedder

    settings = Settings.load()
    settings.cache_dir.mkdir(parents=True, exist_ok=True)
    emb = DashScopeEmbedder(
        settings=settings, cache=EmbeddingCache(settings.cache_dir / "cache.db")
    )
    out = {}
    for subject in SUBJECTS:
        ds = load_dataset(DATA / subject)
        rows = adapt_rows(ds)
        out[subject] = (ds, rows, [r["gold"] for r in rows if r["gold"]])
    return emb, out


def test_features_cosine_equals_recall_score(env) -> None:
    """**产物里的 cosine 必须是"召回分经截断"，不是占位 0、不是重算值。**

    三条判据，缺一不可：

    1. **非全零**：若 cosine 根本没接入（恒 0.0），排序就退化成两项装置。
       只断言"在 [0,1] 内"抓不到这个——0.0 也在范围内。
    2. **池内有方差**：若全是同一个常数，cosine 不提供任何排序信号。
    3. **两个字段同源**：`features` 与 `features_by_tag` 里 gold 的 cosine 必须相等。

    **为什么不能"独立再召回一次比对"**：`evaluate` 内部建临时 store 后销毁，
    外部拿不到同一个 store。真正的独立交叉验证在
    `test_cosine_band.py`（它现场算 gold/distractor 余弦），
    而"召回分本身算得对"由 `test_vector_scored.py::test_scored_values_are_the_cosine` 守。
    """
    from evals.run_retrieval import evaluate

    from memory.retrieval.pool_modes import PoolMode

    emb, data = env
    total_cases = 0
    nonzero_cases = 0
    var_cases = 0
    checked = 0

    for subject in SUBJECTS:
        _ds, rows, specs = data[subject]
        res = evaluate(
            rows,
            all_specs=specs,
            weights_name="uniform",
            enable_dedup=False,
            judge=None,
            k=5,
            pool_mode=PoolMode.UNRELATED,
            paths=("lexical", "vector", "adjacency"),
            embedder=emb,
        )

        for case in res["per_case"]:
            if not case.get("has_gold") or case.get("skipped"):
                continue
            fbt = case.get("features_by_tag") or {}
            if not fbt:
                continue
            checked += 1
            cos_values = [feats["cosine"] for feats in fbt.values()]

            # 1) 非全零
            total_cases += 1
            if any(c > 0.0 for c in cos_values):
                nonzero_cases += 1
            # 2) 池内有方差
            if len(set(cos_values)) > 1:
                var_cases += 1

            # 越界检查（截断后必须在 [0,1]）
            for tag, feats in fbt.items():
                assert 0.0 <= feats["cosine"] <= 1.0, (
                    f"{case['case_id']}/{tag}: cosine={feats['cosine']} 越界"
                )

            # 3) 两个字段同源
            gold_tag = f"gold-{case['case_id']}"
            if case.get("features") and gold_tag in fbt:
                assert case["features"]["cosine"] == fbt[gold_tag]["cosine"], (
                    f"{subject}/{case['case_id']}: features 与 features_by_tag 的 cosine 不一致"
                )

    assert checked > 0, "没有任何 case 被检查——这条测试什么也没验到"

    # **这两条是抓"没接入"的关键**：若 cosine 恒 0，它们会红
    assert nonzero_cases == total_cases, (
        f"只有 {nonzero_cases}/{total_cases} 条 case 的池内有非零 cosine。"
        "若为 0，说明 cosine 没从向量召回路带出来（仍是占位值）"
    )
    assert var_cases == total_cases, (
        f"只有 {var_cases}/{total_cases} 条 case 的池内 cosine 有方差。"
        "若为 0，说明所有候选拿到同一个常数，cosine 不提供排序信号"
    )


def test_cosine_feature_is_truncated_to_unit_interval() -> None:
    """负余弦必须被截断到 0.0，正余弦保持原值（不是 (x+1)/2 映射）。

    **为什么不是 (x+1)/2**：那会把"毫无关系"（0.0）变成 0.5，
    而 0.5 在加权里与"中等相似"不可区分。截断保留"0 = 无信号"的语义。
    """
    from evals.run_retrieval import cosine_feature

    assert cosine_feature(-0.3) == 0.0
    assert cosine_feature(-0.9) == 0.0
    assert cosine_feature(0.0) == 0.0
    assert cosine_feature(0.5) == 0.5, (
        f"0.5 应保持 0.5，得到 {cosine_feature(0.5)}。"
        "若变成 0.75，说明用了 (x+1)/2 映射"
    )
    assert cosine_feature(1.0) == 1.0


def test_cosine_gap_and_band_are_written(env) -> None:
    """每条已召回 gold 的 case 都含 `cosine_gap` 与 `cosine_band`。

    `cosine_gap` 是 float 或 None；`cosine_band` 是三态字符串或 None。
    """
    from evals.run_retrieval import evaluate

    from memory.retrieval.pool_modes import PoolMode

    emb, data = env
    bands: dict[str, set[str]] = {}

    for subject in SUBJECTS:
        _ds, rows, specs = data[subject]
        res = evaluate(
            rows,
            all_specs=specs,
            weights_name="uniform",
            enable_dedup=False,
            judge=None,
            k=5,
            pool_mode=PoolMode.UNRELATED,
            paths=("lexical", "vector", "adjacency"),
            embedder=emb,
        )
        bands[subject] = set()
        for case in res["per_case"]:
            if not case.get("has_gold") or case.get("skipped"):
                continue
            assert "cosine_gap" in case, (
                f"{subject}/{case['case_id']}: 缺 cosine_gap 字段"
            )
            assert "cosine_band" in case, (
                f"{subject}/{case['case_id']}: 缺 cosine_band 字段"
            )
            gap = case["cosine_gap"]
            band = case["cosine_band"]
            assert gap is None or isinstance(gap, float), (
                f"{subject}/{case['case_id']}: cosine_gap={gap!r} 应为 float 或 None"
            )
            assert band is None or band in {"stable", "noise", "negative"}, (
                f"{subject}/{case['case_id']}: cosine_band={band!r} 不是三态之一"
            )
            if band is not None:
                bands[subject].add(band)

    # 三态必须实际用到至少两种：若全是 stable，三态没有存在意义
    for subject in SUBJECTS:
        assert "stable" in bands[subject], f"{subject}: 没有 stable case"
        assert "negative" in bands[subject], (
            f"{subject}: 没有 negative case——三态退化成了两态（{bands[subject]}）"
        )


def test_negative_band_is_not_counted_as_noise(env) -> None:
    """负 gap 归 `negative`，不归 `noise`。两者的处置相反。

    **若把它们合并**，会得出"`billing` 有 25% 不稳定"这种误导性数字——
    而其中大部分是"cosine 已经排错"，那是能力边界，不能排除。
    """
    from evals.run_retrieval import evaluate

    from memory.retrieval.pool_modes import PoolMode

    emb, data = env
    for subject in SUBJECTS:
        _ds, rows, specs = data[subject]
        res = evaluate(
            rows,
            all_specs=specs,
            weights_name="uniform",
            enable_dedup=False,
            judge=None,
            k=5,
            pool_mode=PoolMode.UNRELATED,
            paths=("lexical", "vector", "adjacency"),
            embedder=emb,
        )
        for case in res["per_case"]:
            if not case.get("has_gold") or case.get("skipped"):
                continue
            gap = case["cosine_gap"]
            band = case["cosine_band"]
            if gap is None:
                continue
            if gap < 0:
                assert band == "negative", (
                    f"{subject}/{case['case_id']}: gap={gap:.4f} < 0 但 band={band}。"
                    "负 gap 必须归 negative——它是'已排错'，不是'可能翻转'"
                )
            elif gap < 0.01:
                assert band == "noise", (
                    f"{subject}/{case['case_id']}: 0 <= gap={gap:.4f} < 0.01 但 band={band}"
                )
            else:
                assert band == "stable", (
                    f"{subject}/{case['case_id']}: gap={gap:.4f} >= 0.01 但 band={band}"
                )
