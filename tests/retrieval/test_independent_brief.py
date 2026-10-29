"""交接材料必须自己合格，且不泄漏我的数据形状。

**两类风险**：

1. **示例不合格**：第二作者会先看示例、再看规则。示例只有 3 条查询、
   1 条 C 轴时，他不会去补另外两条。所以示例必须自己满足第 0 节的规模要求。
2. **泄漏**：一旦他知道我的 domain、relation 名、任何分数，
   就会照着凑，独立性就没了。

这组测试把两件事都变成可复算的断言。
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
BRIEF = ROOT / "docs" / "requirements" / "v2-independent-author-brief.md"


def _text() -> str:
    if not BRIEF.exists():
        pytest.skip("交接材料缺失")
    return BRIEF.read_text(encoding="utf-8")


def _example() -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    blocks = re.findall(r"```json\n(.*?)```", _text(), re.S)
    assert len(blocks) >= 2, "交接材料必须同时给出 memories 与 queries 的示例"
    memories = [json.loads(x) for x in blocks[0].strip().splitlines() if x.strip()]
    queries = [json.loads(x) for x in blocks[1].strip().splitlines() if x.strip()]
    return memories, queries


def test_example_passes_all_applicable_gates(tmp_path: Path) -> None:
    """示例必须自己通过 L1–L4、F13、F17a、F17b、F21a、F23。

    否则它会教给第二作者一个不合格的形状。
    """
    from evals.datasets.retrieval_v2 import load_dataset
    from evals.tools.check_v2_dataset import (
        check_f13_cue_mix,
        check_f17a_axis_a_covers_every_branch,
        check_f17b_every_relation_has_axis_c,
        check_f21a_relation_count,
        check_f23_axis_a_query_floor,
        check_l1_no_verbatim_text,
        check_l2_no_gold_value,
        check_l3_char_overlap,
        check_l4_every_memory_has_text,
    )

    memories, queries = _example()
    (tmp_path / "memories.jsonl").write_text(
        "\n".join(json.dumps(m, ensure_ascii=False) for m in memories) + "\n",
        encoding="utf-8",
    )
    (tmp_path / "queries.jsonl").write_text(
        "\n".join(json.dumps(q, ensure_ascii=False) for q in queries) + "\n",
        encoding="utf-8",
    )
    dataset = load_dataset(tmp_path)

    for check in (
        check_l1_no_verbatim_text,
        check_l2_no_gold_value,
        check_l3_char_overlap,
        check_l4_every_memory_has_text,
        check_f21a_relation_count,
        check_f23_axis_a_query_floor,
        check_f13_cue_mix,
        check_f17a_axis_a_covers_every_branch,
        check_f17b_every_relation_has_axis_c,
    ):
        result = check(dataset)
        assert result.passed, f"示例未通过 {result.code}：{result.detail}"


def test_example_scale_matches_the_stated_minimum(tmp_path: Path) -> None:
    """示例的规模必须等于第 0 节写的最小合法 subject（7 记忆 / 9 查询）。"""
    memories, queries = _example()

    assert len(memories) == 7
    assert len(queries) == 9

    relations = {str(m["relation"]) for m in memories}
    assert len(relations) == 3, "示例应用 3 个 relation 示范上限"

    a_queries = [q for q in queries if q["axis"] == "A"]
    c_queries = [q for q in queries if q["axis"] == "C"]
    assert len(a_queries) == 6
    assert len(c_queries) == 3


def test_example_has_an_implicit_majority(tmp_path: Path) -> None:
    """示例的 implicit 必须 ≥50% 且 ≥5 条中的至少 4 条（示例规模下的等价值）。"""
    _, queries = _example()
    a_queries = [q for q in queries if q["axis"] == "A"]
    implicit = [q for q in a_queries if q["cue_type"] == "implicit"]

    assert len(implicit) / len(a_queries) >= 0.5
    assert len(implicit) >= 4


def test_scale_requirements_appear_before_the_example() -> None:
    """规模要求必须在示例**之前**。

    人读文档先看结构再看细节；规模放在最后容易被跳过，
    于是拿示例的尺寸当模板。
    """
    text = _text()
    scale_pos = text.find("## 0. 先看这一节：规模要求")
    example_pos = text.find("## 7. 填写示例")

    assert scale_pos != -1, "缺少规模要求一节"
    assert example_pos != -1, "缺少填写示例一节"
    assert scale_pos < example_pos, "规模要求必须在示例之前"


def test_no_leak_of_my_domains_or_relations() -> None:
    """不得出现我的 domain 名、relation 名，或任何分数。

    出现任何一个，第二作者就会照着凑，独立性就没了。
    """
    text = _text()
    forbidden = [
        "ledger",
        "billing",
        "inventory",
        "oncall_owner",
        "deploy_target",
        "code_style",
        "package_manager",
        "test_command",
        "invoice_currency",
        "tax_region",
        "settlement_cycle",
        "payment_gateway",
        "SEH",
        "MRR",
        "SRS",
        "0.9000",
        "0.6667",
        "0.9167",
        "样例有",
    ]
    hits = [word for word in forbidden if word in text]
    assert not hits, f"交接材料泄漏：{hits}"


def test_no_gate_numbers_leaked() -> None:
    """不得出现门禁编号或通过数——他知道了就会去凑那几条。"""
    text = _text()

    assert not re.search(r"\bF\d+[ab]?\b", text), "出现了门禁编号"
    assert "通过率" not in text or "任何通过率" in text
    assert not re.search(r"\d+/\d+ 通过", text)


def test_example_domain_differs_from_any_real_domain() -> None:
    """示例必须是 `project:docs-site`，且是全新的。"""
    memories, _ = _example()

    subjects = {str(m["subject"]) for m in memories}
    assert subjects == {"project:docs-site"}


def test_counter_examples_section_exists() -> None:
    """必须有反例——只给正例时，读者不知道什么算不合格。"""
    text = _text()

    assert "反例" in text
    assert "A 轴 5 条" in text or "explicit = 0" in text
