"""`per_case` 记录 `n_competitors` 与派生 `axis`（tasks 2.4a）。

**为什么这些字段必须进 `per_case`**：`rerank_order_tags` 只给顺序，
`pool_tag_meta` 只给（subject, relation）。两者合起来能算"竞争集内名次"，
但**算不出"每条查询面对几个同 relation 对手"**——而那正是轴的定义量。

缺了它，报告只能说"两轴同构 / 不同构"这个结论，**不能复算**。
这条测试的作用就是：`n_competitors` 必须是**结果文件里的数据**，
而不是运行时的中间变量。测试自己用 `pool_tag_meta` 重算一遍对照。

**这条测试防的具体形态**：把 `n_competitors` 写成一个常量
（比如 `pool_size - 1`），或写成 `len(pool_tag_meta)`。
两者在 `billing` 上都是 8 / 9，与真值 2 差得很远，但**不会报错**。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data" / "retrieval-v2"


def _load_labels(subject: str) -> dict[str, str]:
    """读回数据集的 `axis` 标注（A / C）。"""
    return {
        str(q["query_id"]): str(q["axis"])
        for q in (
            json.loads(line)
            for line in (DATA / subject / "queries.jsonl")
            .read_text(encoding="utf-8")
            .splitlines()
            if line.strip()
        )
    }


def _run(subject: str) -> dict[str, object]:
    from evals.datasets.retrieval_v2 import load_dataset
    from evals.datasets.v2_adapter import rows as adapt_rows
    from evals.run_retrieval import evaluate

    from memory.retrieval.pool_modes import PoolMode

    path = DATA / subject
    if not path.exists():
        pytest.skip(f"{subject} 数据集缺失")
    dataset = load_dataset(path)
    rows = adapt_rows(dataset)
    specs = [r["gold"] for r in rows if r["gold"]]
    # 只用 lexical：轴派生是池结构的性质，不该依赖向量或网络。
    return evaluate(
        rows,
        all_specs=specs,
        weights_name="uniform",
        enable_dedup=False,
        judge=None,
        k=5,
        pool_mode=PoolMode.UNRELATED,
        paths=("lexical",),
    )


def _recompute_n(case: dict[str, object]) -> int:
    """从结果文件自己的 `pool_tag_meta` 复算 `n_competitors`。

    **不从数据集复算**：数据集给的是"这个 subject 有几条同 relation 记忆"，
    而 `n_competitors` 是"**本池里**有几条同 relation 候选"。
    池是抽样出来的（`PoolMode.UNRELATED`），两者可以不相等。
    """
    meta: dict[str, dict[str, str]] = case["pool_tag_meta"]  # type: ignore[assignment]
    gold_tag = f"gold-{case['case_id']}"
    gold_rel = meta[gold_tag]["relation"]
    return sum(
        1
        for tag, m in meta.items()
        if tag != gold_tag and m["relation"] == gold_rel
    )


@pytest.mark.parametrize("subject", ["sample", "billing"])
def test_per_case_has_axis(subject: str) -> None:
    """每条 case 都有 `n_competitors`（int）与 `axis`（二元字符串）。"""
    result = _run(subject)
    for case in result["per_case"]:  # type: ignore[union-attr]
        if not case.get("has_gold"):
            continue
        assert "n_competitors" in case, f"{case['case_id']}: 缺 n_competitors"
        assert "axis" in case, f"{case['case_id']}: 缺 axis"
        assert isinstance(case["n_competitors"], int), case["case_id"]
        assert case["axis"] in {"relation_within", "relation_cross"}, case["case_id"]


@pytest.mark.parametrize("subject", ["sample", "billing"])
def test_n_competitors_recomputes_from_pool_meta(subject: str) -> None:
    """**可复算**：`n_competitors` 必须等于用 `pool_tag_meta` 重算的值。

    这条是"结果文件自证"的检查——不依赖运行时变量，也不依赖数据集标注。
    """
    result = _run(subject)
    for case in result["per_case"]:  # type: ignore[union-attr]
        if not case.get("has_gold"):
            continue
        expected = _recompute_n(case)
        assert case["n_competitors"] == expected, (
            f"{case['case_id']}: n_competitors={case['n_competitors']} "
            f"但用 pool_tag_meta 复算是 {expected}"
        )


@pytest.mark.parametrize("subject", ["sample", "billing"])
def test_axis_follows_n_competitors(subject: str) -> None:
    """`axis` 必须是 `n_competitors > 0` 的函数，不能是标注的副本。"""
    result = _run(subject)
    for case in result["per_case"]:  # type: ignore[union-attr]
        if not case.get("has_gold"):
            continue
        expected = (
            "relation_within" if case["n_competitors"] > 0 else "relation_cross"
        )
        assert case["axis"] == expected, (
            f"{case['case_id']}: n={case['n_competitors']} 应为 {expected}，"
            f"实际 {case['axis']}"
        )


def test_billing_axis_labels_disagree_with_pool_structure() -> None:
    """**v2 标注与池结构脱钩的直接证据**：`billing` 有 3 条 C 标注实为 within。

    这条断言的是"派生值与标注不一致的条数"，两个数都来自数据：

    - 标注：`queries.jsonl` 的 `axis` 字段
    - 派生：`per_case` 里的 `axis`

    若某天数据集被改成"标注与结构一致"，这条会红——**那时应该改的是期望，
    不是删掉测试**，因为它记录的是 v2 的一个真实事实。
    """
    labels = _load_labels("billing")
    result = _run("billing")

    mismatches = []
    for case in result["per_case"]:  # type: ignore[union-attr]
        if not case.get("has_gold"):
            continue
        labeled = "relation_within" if labels[case["case_id"]] == "A" else "relation_cross"
        if labeled != case["axis"]:
            mismatches.append(case["case_id"])

    assert sorted(mismatches) == ["billing-c1", "billing-c2", "billing-c3"], (
        f"标注与派生不一致的是 {sorted(mismatches)}，"
        "预期正是那 3 条 C 标注（它们的 gold relation 在池中各有 2 个对手）"
    )


def test_ledger_axis_labels_agree_with_pool_structure() -> None:
    """`ledger` 的 12 条标注全部与池结构一致（0 不一致）。

    **必须与 `billing` 的 3 条一起看**：只测 `billing` 时，
    "全部不一致"这个错误实现也能过（只要它把 A 判 cross、C 判 within）。
    两条一起才把"派生正确"与"标注正确"区分开。
    """
    labels = _load_labels("sample")
    result = _run("sample")

    mismatches = []
    for case in result["per_case"]:  # type: ignore[union-attr]
        if not case.get("has_gold"):
            continue
        labeled = "relation_within" if labels[case["case_id"]] == "A" else "relation_cross"
        if labeled != case["axis"]:
            mismatches.append(case["case_id"])

    assert mismatches == [], f"ledger 标注与派生不一致：{mismatches}"


def test_n_competitors_is_not_pool_size() -> None:
    """**防常量**：`n_competitors` 不能等于 `pool_size - 1` 或 `pool_size`。

    `billing` 的池是 9 条、每条查询的对手数是 2。若实现把
    `n_competitors` 写成池大小，`billing` 上会得 8 或 9，而两者都"是个合理的数"。
    """
    result = _run("billing")
    for case in result["per_case"]:  # type: ignore[union-attr]
        if not case.get("has_gold"):
            continue
        assert case["n_competitors"] < case["pool_size"] - 1, (
            f"{case['case_id']}: n_competitors={case['n_competitors']} "
            f"与 pool_size={case['pool_size']} 太接近，疑似把池大小当成了对手数"
        )
