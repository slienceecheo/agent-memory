"""结论 5：三路融合让 top-1 精度低于 lexical 单路。

## 为什么这条必须先于 v3 数据存在

否则 v3 数据造出来后，无法判断"v3 分数低"是**装置**的问题
还是**融合稀释**的问题。两者需要不同的处置：

| 原因 | 处置 |
|---|---|
| 装置（三个特征无语义信号） | 装置变更 |
| **融合稀释**（vector 长尾把 lexical 头部挤出前排） | 检索层变更 |

## 为什么必须配对比较

容易犯的错：拿"lexical 已召回的 5/6 = 0.8333"与"三路的 3/10 = 0.3000"比。
**分母不同**（6 vs 10），不能相减。

正确做法：只比较"两种配置都召回了 gold"的 case。

## 为什么这个测试重跑而不读文件

`results/*.json` 顶层必须保持 48 个。写一份新结果文件会破坏那个约束。
所以**现场重跑**，断言方向与报告一致。

embedding 走缓存，重跑不会调用 API。
"""

from __future__ import annotations

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data" / "retrieval-v2"
SUBJECTS = ("sample", "billing")

#: 报告 §6.1 的配对数字。改动这里必须同时改报告。
EXPECTED = {
    "sample": {"n": 6, "lexical_hit": 5, "triple_hit": 3},
    "billing": {"n": 9, "lexical_hit": 8, "triple_hit": 1},
}


@pytest.fixture(scope="module")
def measured():
    """现场重跑三组配置，返回配对比较的原始计数。"""
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
        rr.PREREGISTERED_WEIGHTS["__concl5"] = RerankWeights(base=0.4, authority=0.3, cosine=0.3)

        for subject in SUBJECTS:
            ds = load_dataset(DATA / subject)
            rows = adapt_rows(ds)
            specs = [r["gold"] for r in rows if r["gold"]]
            within = {
                q.query_id
                for q in ds.queries
                if derived_axis_of(ds, q) == "relation_within"
            }

            def run(paths, *, _rows=rows, _specs=specs, _embedder=embedder):
                return rr.evaluate(
                    _rows,
                    all_specs=_specs,
                    weights_name="__concl5",
                    enable_dedup=False,
                    judge=None,
                    k=5,
                    pool_mode=PoolMode.UNRELATED,
                    paths=paths,
                    embedder=_embedder,
                )

            def collect(res, *, _within=within):
                got: dict[str, dict] = {}
                for c in res["per_case"]:
                    cid = c["case_id"]
                    if cid not in _within:
                        continue
                    if not c.get("has_gold") or c.get("skipped"):
                        continue
                    got[cid] = {
                        "recalled": c.get("rank_after_fusion") is not None,
                        "rank": c.get("rank_after_rerank"),
                    }
                return got

            lex = collect(run(("lexical",)))
            trio = collect(run(("lexical", "vector", "adjacency")))

            paired = [
                cid
                for cid in lex
                if cid in trio and lex[cid]["recalled"] and trio[cid]["recalled"]
            ]
            out[subject] = {
                "lex": lex,
                "trio": trio,
                "paired": paired,
                "lexical_hit": sum(1 for cid in paired if lex[cid]["rank"] == 1),
                "triple_hit": sum(1 for cid in paired if trio[cid]["rank"] == 1),
                "lexical_recalled": sum(1 for v in lex.values() if v["recalled"]),
                "triple_recalled": sum(1 for v in trio.values() if v["recalled"]),
            }
    finally:
        rr.PREREGISTERED_WEIGHTS.clear()
        rr.PREREGISTERED_WEIGHTS.update(original)
    return out


def test_paired_comparison_matches_report(measured) -> None:
    """**配对比较的计数必须与报告 §6.1 一致。**

    这是"文档数字可复算"的判据：改数据或改装置，这条会红，
    而红的时候会告诉你报告里哪一行的数字过期了。

    **为什么不直接比 ratio**：计数（`5/6`）比小数（`0.8333`）更能定位问题——
    若是 `n` 变了、还是分子变了，一眼可分。
    """
    problems: list[str] = []
    for subject in SUBJECTS:
        got = measured[subject]
        want = EXPECTED[subject]
        n = len(got["paired"])
        if n != want["n"]:
            problems.append(f"{subject}: 配对 n 是 {n}，报告写 {want['n']}")
        if got["lexical_hit"] != want["lexical_hit"]:
            problems.append(
                f"{subject}: lexical 命中 {got['lexical_hit']}，报告写 {want['lexical_hit']}"
            )
        if got["triple_hit"] != want["triple_hit"]:
            problems.append(
                f"{subject}: 三路命中 {got['triple_hit']}，报告写 {want['triple_hit']}"
            )

    assert not problems, (
        "配对比较与报告 §6.1 不符：\n  " + "\n  ".join(problems)
    )


def test_fusion_dilution_direction_holds(measured) -> None:
    """**方向必须成立**：lexical 单路的配对 top-1 严格高于三路。

    这条比"数字相等"更根本：即使数据换了、数字变了，
    "融合稀释"这个方向如果反了，结论 5 就不成立。
    """
    for subject in SUBJECTS:
        got = measured[subject]
        n = len(got["paired"])
        assert n > 0, f"{subject}: 没有配对 case"
        lex_r = got["lexical_hit"] / n
        tri_r = got["triple_hit"] / n
        assert lex_r > tri_r, (
            f"{subject}: lexical {lex_r:.4f} 不高于三路 {tri_r:.4f}——"
            "结论 5（融合稀释）在这个方向上不成立，报告要重写"
        )


def test_multi_path_improves_recall(measured) -> None:
    """**与结论 5 配对的限定**：三路召回率更高，不是"多路召回有害"。

    若这条不成立（三路召回没有更好），那"提高召回但降低 top-1 精度"
    这个完整表述就只剩后半句——读者会以为该砍掉 vector 路。
    """
    for subject in SUBJECTS:
        got = measured[subject]
        lex_n = len(got["lex"])
        trio_n = len(got["trio"])
        assert trio_n == lex_n, (
            f"{subject}: 两种配置的 case 总数不同（{lex_n} vs {trio_n}），无法比较"
        )
        assert got["triple_recalled"] > got["lexical_recalled"], (
            f"{subject}: 三路召回 {got['triple_recalled']}/{trio_n} "
            f"不高于 lexical 单路 {got['lexical_recalled']}/{lex_n}——"
            "『提高召回但降低精度』这个表述的后半句不再成立"
        )


def test_all_three_denominators_are_reported(measured) -> None:
    """**三个分母必须都能算出，且数值不同**（否则报告里的三行表没有意义）。

    | 分母 | 含义 |
    |---|---|
    | 全部派生 within | 端到端（召回失败也算错） |
    | 已召回 | 只看召回了的 |
    | 配对 | 重排本身的质量 |

    这条防的是"报告只写了一个数，读者以为是另一个数"。
    """
    for subject in SUBJECTS:
        got = measured[subject]
        n_all = len(got["lex"])
        n_recall = got["lexical_recalled"]
        n_pair = len(got["paired"])

        assert 0 < n_recall <= n_all
        assert 0 < n_pair <= n_recall

        # 三个分母下 lexical 的 top-1 率
        r_all = sum(1 for v in got["lex"].values() if v["rank"] == 1) / n_all
        r_recall = got["lexical_hit"] / n_recall if n_recall else 0.0
        r_pair = got["lexical_hit"] / n_pair

        # 至少要有两个不同（全部 vs 已召回），否则分母没区分度
        assert r_all != r_recall or n_recall == n_all, (
            f"{subject}: 全部分母与已召回分母给出同一个数 {r_all:.4f}，"
            "报告里那三行表会失去意义"
        )
        assert abs(r_pair - r_recall) < 1e-9, (
            f"{subject}: 配对的 {r_pair:.4f} 与已召回的 {r_recall:.4f} 不同——"
            "三路全召回时两者应相等；若不等说明配对筛选有问题"
        )


def test_report_states_the_three_denominators() -> None:
    """**报告必须写出三个分母**，不能只写一个数。

    **判据必须是表格行，不是关键词**：
    `"配对"` 这个词在 §6 里出现 8 次，用 `"配对" in section` 会在
    整行被删掉时仍然通过——那是字符串包含的顶替形态。

    所以检查 §6.2 那张表的**三行首列**：

    | 分母 |
    |---|
    | 全部派生 within |
    | 已召回 |
    | **配对（都召回）** |

    **为什么括号要包含在内**：`| 已召回 |` 是 `| 已召回 | 5/6 ... |` 的前缀，
    单独匹配前者会与"三路全召回"那行混淆。带上完整单元格能区分。
    """
    report = (ROOT / "docs" / "reports" / "v2-what-it-measures.md").read_text(
        encoding="utf-8"
    )
    section = report.split("## 6. 结论 5")[1].split("\n## ")[0]
    table = section.split("### 6.2")[1].split("### 6.3")[0]

    rows = [
        ln.strip() for ln in table.splitlines() if ln.strip().startswith("|")
    ]
    first_cells = []
    for row in rows:
        cells = [c.strip() for c in row.strip("|").split("|")]
        if cells:
            first_cells.append(cells[0].replace("*", "").strip())

    for label in ("全部派生 within", "已召回", "配对（都召回）"):
        assert label in first_cells, (
            f"报告 §6.2 的表格缺少分母行「{label}」——"
            f"实际首列是 {first_cells}。\n"
            "只写一个分母会让读者把'召回差'读成'重排差'。"
        )


def test_report_marks_fusion_dilution_not_multi_path_harm() -> None:
    """**报告必须明确说"这不是多路召回有害"**。

    否则读者会把 `0.8333 -> 0.5000` 读成"该砍掉 vector 路"，
    而实际是"召回变好、融合排序没跟上"。
    """
    report = (ROOT / "docs" / "reports" / "v2-what-it-measures.md").read_text(
        encoding="utf-8"
    )
    section = report.split("## 6. 结论 5")[1].split("\n## ")[0]

    assert "不是「多路召回有害」" in section or "不是\"多路召回有害\"" in section, (
        "报告 §6 缺少「这不是多路召回有害」的限定——"
        "读者会把它读成该砍掉某一路"
    )
    assert "召回" in section and "精度" in section, (
        "报告 §6 必须同时出现「召回」与「精度」，说明两个指标方向相反"
    )


def test_report_states_mechanism_is_undifferentiated() -> None:
    """**报告必须写明"机制未区分"**，不能只写现象。

    结论 5 只说"三路融合后 top-1 变低"，而两个不同机制都能产生同样的数字：

    | 机制 | 处置 |
    |---|---|
    | 融合规则（RRF 稀释） | 改融合 |
    | vector 召回质量（cosine 排序差） | 改召回 |

    **若不写这句限定，下一个人会以为结论 5 已经解释了原因**，
    从而直接去改融合——而真正的原因可能是 cosine 排序。

    **这条也解释了为什么本章止于现象**：区分两者需要产物记录 cosine，
    而现有 15 份冻结产物都没有。
    """
    report = (ROOT / "docs" / "reports" / "v2-what-it-measures.md").read_text(
        encoding="utf-8"
    )
    section = report.split("## 6. 结论 5")[1].split("\n## ")[0]

    assert "机制未区分" in section, (
        "报告 §6 缺少「机制未区分」这一节——"
        "读者会以为结论 5 已经解释了融合稀释的原因"
    )
    assert "融合规则" in section and "vector 召回质量" in section, (
        "§6 必须并列写出两个可能的机制，否则「未区分」没有对象"
    )
    assert "cosine" in section, (
        "§6 必须点明区分两者需要 cosine 分——否则读者不知道为什么不能归因"
    )


def test_report_does_not_claim_462_is_per_case() -> None:
    """**报告必须说明 `path_returns.vector = 462` 是累加值**。

    错误读法：以为单条 case 的 vector 返回 462 条。
    实际：单条 case 返回 == `pool_size`（14 / 9），vector 路返回**整个池**。

    **这个数被误读的代价**：会以为"vector 返回了海量噪声"，
    从而去"压缩 vector 召回"。而实际它返回的就是全部候选，
    没有可压缩的东西。
    """
    report = (ROOT / "docs" / "reports" / "v2-what-it-measures.md").read_text(
        encoding="utf-8"
    )
    section = report.split("## 6. 结论 5")[1].split("\n## ")[0]

    assert "累加" in section, (
        "§6 必须写明 462 是累加值，否则会被读成单条 case 的返回数"
    )
    assert "返回了整个池" in section or "返回整个池" in section, (
        "§6 必须说明 vector 路返回整个池——这是它 SEH@1 低的直接原因"
    )


def test_product_shows_vector_returns_whole_pool() -> None:
    """**`path_returns.vector == pool_size` 这个事实必须能从产物复算。**

    这条**只读产物**，是 §6.7 那句"返回了整个池"的依据。
    它不检查文档——文档那句由 `test_report_documents_vector_returns_whole_pool` 管。

    **两条分开写的理由**：若合成一条，删掉文档那句时断言仍绿
    （因为产物没变），而名字看起来覆盖了文档。实测过这个假阳性。

    **不读 `v2-sample-*`**：那份文件不存在（`sample` 只有 `a3-*.json`）。
    """
    import json

    cases: list[tuple[str, int, int]] = []
    for name in (
        "a3-lexical-vector-adjacency.json",
        "v2-billing-lexical-vector-adjacency.json",
    ):
        path = ROOT / "results" / name
        assert path.exists(), f"缺少产物 {name}"
        data = json.loads(path.read_text(encoding="utf-8"))
        for case in data.get("per_case") or []:
            pool = case.get("pool_size")
            vec = (case.get("path_returns") or {}).get("vector")
            if vec is not None and pool:
                cases.append((name, pool, vec))

    assert cases, "没有任何可检查的 case"
    mismatched = [(n, p, v) for n, p, v in cases if p != v]
    assert not mismatched, (
        f"这些 case 的 path_returns.vector != pool_size：{mismatched[:3]}。\n"
        "若不再相等，'vector 返回整个池'这个结论要重核。"
    )

    pools = {p for _, p, _ in cases}
    assert pools == {14, 9}, (
        f"池大小变成 {sorted(pools)}（原为 9 与 14）——"
        "数据或池构造变了，§6.7 的数字要更新"
    )


def test_report_documents_vector_returns_whole_pool() -> None:
    """**报告必须写出"vector 路返回整个池"这句**。

    这条**只读文档**。产物侧的对应事实由
    `test_product_shows_vector_returns_whole_pool` 管。

    **为什么必须分开**：名称相同但只读产物时，删掉文档那句不会红——
    那会让"文档有没有写"这件事没有守卫。
    """
    report = (ROOT / "docs" / "reports" / "v2-what-it-measures.md").read_text(
        encoding="utf-8"
    )
    section = report.split("## 6. 结论 5")[1].split("\n## ")[0]
    sub = section.split("### 6.7")[1].split("### 6.8")[0]

    assert "返回了整个池" in sub, (
        "§6.7 必须明确写出「vector 路返回了整个池」——"
        "这是它 SEH@1 低的直接原因，也是'462 不是噪声洪流'的依据"
    )
    assert "cosine 全序" in sub, (
        "§6.7 必须说明 vector 的排序就是 cosine 全序——"
        "否则读者会以为 vector 路还有别的排序逻辑"
    )
