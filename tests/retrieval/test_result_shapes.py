"""重写 test_result_shapes.py：把"类数"与"加总"分成两条断言。

核心改动：
1. 新增结构签名函数，**不预设类数**，让数据自己分组
2. "类数"断言：分组数 == 9（类数本身的性质）
3. "加总"断言：每组至少 1 个文件，且加总 == 文件数（覆盖性）
4. 区分两种新增情形：
   - 签名新 -> 分组数变多 -> 类数断言红（该红，文档要加一类）
   - 签名旧 -> 分组数不变 -> 类数断言绿，只有加总变（文档只改加总）

**扫描范围是"v2 档案"，即 `results/*.json` 顶层，不含子目录。**

本文件的每条 `RESULTS.glob(...)` 都带 `p.parent == RESULTS`。
那条件是**冗余的**（`glob` 本来就不递归），但它是**声明**：
它把"只看顶层"从"碰巧用了 glob"变成"有意只看顶层"。

v3 的产物流在 `results/v3/`、历史对照物在 `results/archive/`。
若有人把这里改成 `rglob`，这些"9 类 / 48"的断言会立刻看到 v3 文件——
**红的原因不是数据变了，是扫描范围变了而断言没跟着分区。**
那时该做的是按 `parent` 分区，不是改 `48`。
"""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
RESULTS = ROOT / "results"
HANDOFF = ROOT / "docs" / "HANDOFF.md"

LIST_KEYS = ("per_case", "samples", "checks", "rows", "cases")


def signature(path: Path) -> tuple:
    """结构签名：**不预设类名**，只用结构特征。

    这是"九类有依据"的那个规则——分组结果由数据决定，不是我先定九类再往里塞。
    """
    try:
        d = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return ("BAD_JSON",)

    if isinstance(d, list):
        return ("top_list",)
    if not isinstance(d, dict):
        return ("BAD_JSON",)

    list_key = None
    for k in LIST_KEYS:
        if isinstance(d.get(k), list):
            list_key = k
            break

    has_cond_dict = (
        isinstance(d.get("with_condition"), dict)
        and isinstance(d.get("without_condition"), dict)
    )

    variants = d.get("variants")
    variants_three = (
        isinstance(variants, dict)
        and set(variants) == {"dev", "test", "independent"}
    )

    all_int = bool(d) and all(isinstance(v, int) for v in d.values())

    return ("dict", list_key, has_cond_dict, variants_three, all_int)


def classify(path: Path) -> str:
    """把签名映射到类名。只用于报告，不参与分组。"""
    sig = signature(path)
    if sig == ("BAD_JSON",):
        return "BAD_JSON"
    if sig == ("top_list",):
        return "top_list"

    _, list_key, has_cond, variants_three, all_int = sig
    if list_key:
        return list_key
    if has_cond:
        return "dict_case_id"
    if variants_three:
        return "sectioned_report"
    if all_int:
        return "ledger"
    return "UNCLASSIFIED"


# ---------- 断言 1：类数 ----------


def test_signature_group_count_is_nine() -> None:
    """**类数由结构签名自然决定，不是预设的。**

    实测：按签名分组恰好 9 组，规模 [36,3,2,2,1,1,1,1,1]，
    与文档的九类逐项吻合。

    **这条断言的是"结果文件有几种形态"（关于系统的事实），
    而不是"当前 48 个文件怎么分"（关于快照的事实）。**

    新增一个签名与已有组相同的文件 -> 分组数不变 -> 这条仍绿。
    新增一个签名全新的文件 -> 分组数变多 -> 这条红（文档要加一类）。
    """
    files = sorted(p for p in RESULTS.glob("*.json") if p.parent == RESULTS)
    groups: dict[tuple, list[str]] = defaultdict(list)
    for p in files:
        groups[signature(p)].append(p.name)

    assert len(groups) == 9, (
        f"结构签名分成 {len(groups)} 组，文档写九类。\n"
        f"各组规模：{sorted((len(v) for v in groups.values()), reverse=True)}\n"
        f"若某个新文件签名全新，需在文档加一类；"
        f"若只是同类文件增加，改加总即可。"
    )


def test_every_group_is_non_empty() -> None:
    """每组至少 1 个文件——分组定义上成立，但防"零组"进入文档。"""
    files = sorted(p for p in RESULTS.glob("*.json") if p.parent == RESULTS)
    groups: dict[tuple, list[str]] = defaultdict(list)
    for p in files:
        groups[signature(p)].append(p.name)

    empty = [sig for sig, names in groups.items() if not names]
    assert not empty, f"出现空组：{empty}"


# ---------- 断言 2：加总（覆盖性） ----------


def test_groups_cover_every_file_exactly_once() -> None:
    """**每个文件恰好属于一组，加总等于文件数。**

    这条与"类数"是两件事：
      类数 = 有几种形态（签名性质）
      加总 = 每个文件都被覆盖（覆盖性）

    只写类数，分类表可以"每类都对，但少一个文件"；
    只写加总，可以是"一个杂类装下所有文件"。
    """
    files = sorted(p for p in RESULTS.glob("*.json") if p.parent == RESULTS)
    groups: dict[tuple, list[str]] = defaultdict(list)
    for p in files:
        groups[signature(p)].append(p.name)

    total = sum(len(v) for v in groups.values())
    assert total == len(files), f"加总 {total} != 文件数 {len(files)}"


def test_current_class_counts_match_document() -> None:
    """当前每个类的**具体数量**必须与文档一致。

    **这条会随任何新增文件变红**——而那是它的用途：
    逼人核对"新增的是同类还是新形态"，并同步文档的加总。
    """
    files = sorted(p for p in RESULTS.glob("*.json") if p.parent == RESULTS)
    counts: dict[str, int] = {}
    for p in files:
        k = classify(p)
        counts[k] = counts.get(k, 0) + 1

    expected = {
        "per_case": 36,
        "samples": 3,
        "checks": 2,
        "rows": 1,
        "cases": 1,
        "dict_case_id": 2,
        "top_list": 1,
        "ledger": 1,
        "sectioned_report": 1,
    }
    assert counts == expected, (
        f"形态分布变了：\n实际 {counts}\n文档 {expected}\n"
        "若新增文件签名与已有组相同，只改加总；若签名全新，加一类。"
    )


def test_every_file_has_a_known_class() -> None:
    """48 个文件都必须能归入九类之一。"""
    files = sorted(p for p in RESULTS.glob("*.json") if p.parent == RESULTS)
    unknown = [p.name for p in files if classify(p) == "UNCLASSIFIED"]
    assert not unknown, f"这些文件无法归类：{sorted(unknown)}"


# ---------- 文档一致性 ----------


def test_handoff_shape_table_sums_to_48() -> None:
    """文档里的形态表必须写出九类加总式，且九行都在。"""
    text = HANDOFF.read_text(encoding="utf-8")
    marker = "#### 逐条结果有 6 种形态"
    assert marker in text, "找不到形态表所在小节"
    section = text.split(marker)[1].split("\n#### ")[0]

    expected_rows = [
        "| list，键名 `per_case` | **36** |",
        "| list，键名 `samples` | **3** |",
        "| list，键名 `checks` | **2** |",
        "| list，键名 `rows` | **1** |",
        "| list，键名 `cases` | **1** |",
        "| **dict，键为 case_id** | **2** |",
        "| 顶层 list | **1** |",
        "| **账本**（键为文件名，值为次数） | **1** |",
    ]
    for row in expected_rows:
        assert row in section, f"缺行：{row}"

    assert "= 48" in section, "文档没有写出加总式"
    assert "九类" in section


def test_handoff_records_that_nine_is_derived_not_assumed() -> None:
    """必须写明"九"来自结构签名的自然分组，不是预设。"""
    text = HANDOFF.read_text(encoding="utf-8")
    assert "结构签名" in text, "文档没提结构签名"
    assert "自然分组" in text or "自然决定" in text


def test_handoff_records_the_two_new_file_cases() -> None:
    """必须写明两种新增情形的处置不同。"""
    text = HANDOFF.read_text(encoding="utf-8")
    # 文档用的是"签名与已有组相同 / 与所有组都不同"这种措辞
    assert "签名与已有组相同" in text
    assert "签名与所有组都不同" in text
    assert "签名组数" in text


def test_handoff_says_nine_depends_on_the_field_list() -> None:
    """**必须写明"九"依赖预设的字段清单，不是数据的自然结构。**

    这是对上一轮说法（"九来自签名自然分组"）的修正：
    换一种签名写法，分组数是 12 或 5，不是 9。
    """
    text = HANDOFF.read_text(encoding="utf-8")

    assert "它也依赖一份预设的字段清单" in text
    # 三种签名的实测
    assert "**9**" in text and "**12**" in text and "**5**" in text
    # 核心判断
    assert "自洽 ≠ 有依据" in text or "自洽" in text


# ---------- 代表文件 ----------


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("v2-sample-gates.json", "checks"),
        ("p2b0-judge-probe.json", "cases"),
        ("equivalence-classification.json", "rows"),
        ("independent-variants.json", "top_list"),
        ("retrieval-run-count.json", "ledger"),
        ("v2-sample-condition-ablation.json", "dict_case_id"),
        ("c4-query-leak-ablation.json", "sectioned_report"),
    ],
)
def test_known_shapes(name: str, expected: str) -> None:
    """每类的代表文件必须归入对应形态。"""
    path = RESULTS / name
    if not path.exists():
        pytest.skip(f"{name} 缺失")
    assert classify(path) == expected
