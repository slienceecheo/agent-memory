"""核实结果文件的九类形态，并断言加总等于文件总数。

**为什么必须有一条这样的测试**：我原先写的表格是
「八类，覆盖 48 个文件」，而八类的数值加总是 47。
`48 - 47 = 1` 这个减法本可以自己算，却是在被指出后才发现的。

**所以判据不是"每一类对不对"，而是"加总等于总数"。**
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
RESULTS = ROOT / "results"
HANDOFF = ROOT / "docs" / "HANDOFF.md"

LIST_KEYS = ("per_case", "samples", "checks", "rows", "cases")


def classify(path: Path) -> str:
    """返回该文件所属的形态名；无法归类返回 'UNCLASSIFIED'。"""
    try:
        d = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return "BAD_JSON"

    if isinstance(d, list):
        return "top_list"
    if not isinstance(d, dict):
        return "BAD_JSON"

    for key in LIST_KEYS:
        if isinstance(d.get(key), list):
            return key

    if isinstance(d.get("with_condition"), dict) or isinstance(
        d.get("without_condition"), dict
    ):
        return "dict_case_id"

    # 账本：键是 *.json 文件名，值是次数
    if (
        d
        and all(isinstance(v, int) for v in d.values())
        and all(str(k).endswith(".json") for k in d)
    ):
        return "ledger"

    # 分节报告：顶层键是分析维度（dict/list），没有逐条 case 结构
    if d and any(isinstance(v, (dict, list)) for v in d.values()):
        return "sectioned_report"

    return "UNCLASSIFIED"


def test_every_result_file_has_a_shape() -> None:
    """48 个文件都必须能归入九类之一。"""
    files = sorted(RESULTS.glob("*.json"))
    unclassified = [p.name for p in files if classify(p) == "UNCLASSIFIED"]

    assert not unclassified, (
        f"这些文件无法归类，需要补一类或修正判据：{sorted(unclassified)}"
    )


def test_shape_counts_sum_to_total() -> None:
    """**九类计数之和必须等于文件总数。**

    这是这一条存在的唯一理由：分类表的价值在于"穷尽"，
    而穷尽只能靠加总验证，不能靠逐类看。
    """
    files = sorted(RESULTS.glob("*.json"))
    counts: dict[str, int] = {}
    for p in files:
        kind = classify(p)
        counts[kind] = counts.get(kind, 0) + 1

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
        "若新增了结果文件，同步更新 HANDOFF 的形态表并重算加总。"
    )
    assert sum(counts.values()) == len(files) == 48, (
        f"九类加总 {sum(counts.values())} != 文件数 {len(files)}"
    )


def test_handoff_shape_table_sums_to_48() -> None:
    """文档里的形态表必须写明加总等于 48，并且九行都在。"""
    text = HANDOFF.read_text(encoding="utf-8")
    marker = "#### 逐条结果有 6 种形态"
    assert marker in text, "找不到形态表所在小节"
    section = text.split(marker)[1].split("\n#### ")[0]

    # **每一类必须整行匹配**，否则 `| **1** |` 会命中别的行
    expected_rows = [
        "| list，键名 `per_case` | **36** |",
        "| list，键名 `samples` | **3** |",
        "| list，键名 `checks` | **2** |",
        "| list，键名 `rows` | **1** |",
        "| list，键名 `cases` | **1** |",
        "| **dict，键为 case_id** | **2** |",
        "| 顶层 list | **1** |",
        "| **账本**（键为文件名，值为次数） | **1** |",
        "| **分节报告**（顶层键为分析维度，非逐条） | **1** |",
    ]
    for row in expected_rows:
        assert row in section, f"缺行：{row}"

    # 加总式
    assert "36 + 3 + 2 + 1 + 1 + 2 + 1 + 1 + 1 = 48" in section, (
        "文档没有写出九类加总式"
    )
    # 九类声明
    assert "九类，覆盖全部 48 个文件" in section
    # 无重复命中的实测
    assert "无重复命中" in section


def test_sectioned_report_is_the_48th() -> None:
    """第 48 个必须是 c4-query-leak-ablation，且它的 variants 不是 case_id 映射。"""
    path = RESULTS / "c4-query-leak-ablation.json"
    if not path.exists():
        pytest.skip("文件缺失")
    d = json.loads(path.read_text(encoding="utf-8"))

    assert classify(path) == "sectioned_report"

    variants = d.get("variants")
    assert isinstance(variants, dict)
    # 键是 variant 名（dev/test/independent），不是 case id
    assert set(variants) == {"dev", "test", "independent"}, (
        f"variants 的键变了：{sorted(variants)}"
    )
    # 所以它不该被第 6 类（dict 键为 case_id）吞掉
    assert classify(path) != "dict_case_id"


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
