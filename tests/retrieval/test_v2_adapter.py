"""v2 适配层的契约：只做字段映射，不做池构造。

**核心约束**：适配层输出必须能**直接**喂给 `evaluate_case()`，
不接受任何额外参数。若它开始构造池，v2 就有了第二套池逻辑，
A3 的数字与 C4 不再可比。

**第二条约束**：适配层不得吞掉 L1 的保证（`query != memory_text`）。
若它用 query 当 text，缺陷 14 会在 v2 上复发。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from evals.datasets.retrieval_v2 import load_dataset
from evals.datasets.v2_adapter import adapt, load_rows, rows
from evals.run_retrieval import evaluate

ROOT = Path(__file__).resolve().parents[2]
SAMPLE = ROOT / "data" / "retrieval-v2" / "sample"


@pytest.fixture(scope="module")
def dataset():
    if not SAMPLE.exists():
        pytest.skip("样例数据集缺失")
    return load_dataset(SAMPLE)


def test_rows_have_fields_evaluate_expects(dataset) -> None:
    """每行必须有 `id` / `query` / `text` / `gold`。"""
    adapted = rows(dataset)

    assert adapted
    for row in adapted:
        assert set(row) >= {"id", "query", "text", "gold", "subject", "relation"}
        assert isinstance(row["id"], str) and row["id"]
        assert isinstance(row["query"], str) and row["query"]
        assert isinstance(row["text"], str) and row["text"]


def test_output_feeds_evaluate_directly(dataset) -> None:
    """**核心约束**：不加工就能喂 `evaluate`。

    这里只断言调用能跑通、且返回结构正确，不断言分数——
    分数属 A3，另由 `three-way-recall.md` 记录。
    """
    adapted = rows(dataset)
    specs = [row["gold"] for row in adapted if row["gold"]]

    result = evaluate(
        adapted,
        all_specs=specs,
        weights_name="uniform",
        enable_dedup=False,
        judge=None,
        k=5,
        paths=("lexical",),
    )

    assert result["cases"] == len(adapted)
    assert "path_returns" in result


def test_adapter_does_not_construct_pools() -> None:
    """适配层不得 import 池构造。

    若它开始自己建池，v2 就有了第二套池逻辑，A3 与 C4 不可比。

    **只查代码，不查 docstring**——docstring 里必须提到这些名字
    才能说明"为什么不用它们"。
    """
    import ast
    import inspect

    import evals.datasets.v2_adapter as module

    tree = ast.parse(inspect.getsource(module))
    code = "\n".join(
        ast.unparse(node)
        for node in tree.body
        if not isinstance(node, ast.Expr)  # 跳过模块 docstring
    )
    for forbidden in ("build_pool", "select_pool_distractors", "PoolMode"):
        assert forbidden not in code, f"适配层的代码里不应出现 {forbidden}"


def test_adapter_does_not_use_query_as_text(dataset) -> None:
    """`text` 不得等于 `query`——否则缺陷 14 在 v2 上复发。

    L1 已保证 `query != memory_text`（数据层），适配层不得破坏它。
    """
    for case in adapt(dataset):
        assert case.query.strip() != case.text.strip(), (
            f"{case.id}: query 与 text 相同，适配层把查询当成了记忆原文"
        )


def test_adapter_preserves_gold_values(dataset) -> None:
    """gold spec 的 value / condition 必须与记忆库一致。"""
    for case in adapt(dataset):
        memory = next(m for m in dataset.memories if m.value == case.candidate_value)
        assert case.gold is not None
        assert case.gold["value"] == memory.value
        assert case.gold["condition"] == memory.condition


def test_adapter_carries_query_condition(dataset) -> None:
    """查询条件必须传下去，否则 `condition_match` 恒为中性。"""
    with_condition = [c for c in adapt(dataset) if c.condition]
    assert with_condition, "样例里应有带条件的查询"

    raw = [
        json.loads(line)
        for line in (SAMPLE / "queries.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    expected = sum(1 for q in raw if q.get("query_condition"))
    assert len(with_condition) == expected


def test_load_rows_end_to_end(dataset) -> None:
    """`load_rows` 一步加载并适配，结果与两步一致。"""
    assert load_rows(SAMPLE) == rows(dataset)
