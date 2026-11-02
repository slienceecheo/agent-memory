"""`evaluate` 输出 subject 级 `axis_policy`（tasks 2.4b）。

**为什么 policy 必须由"派生轴"分组，不能由数据集标注分组**：

`billing` 的 3 条 C 标注在池结构上都是 `relation_within`。若按标注分组，
`billing` 会得到 A={2}、C={2} -> `merged`——**而正确结论是
`billing` 根本没有 cross 查询**（`single_axis`）。

两个值都会让报告写出"轴数 1"，**数字上看不出差别**；而语义相反：
`merged` 是"两轴同构"，`single_axis` 是"只有一轴"。这条测试就要把这两者分开。

**证据必须进结果文件**：只记一个 policy 字符串，无法区分
"判对了"与"常量返回"。所以同时记两轴的 `n` 与取值集合。
"""

from __future__ import annotations

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data" / "retrieval-v2"


def _run(subject: str) -> dict[str, object]:
    from evals.datasets.retrieval_v2 import load_dataset
    from evals.datasets.v2_adapter import rows as adapt_rows
    from evals.run_retrieval import evaluate

    from memory.retrieval.pool_modes import PoolMode

    path = DATA / subject
    if not path.exists():
        pytest.skip(f"{subject} 数据集缺失")
    rows = adapt_rows(load_dataset(path))
    specs = [r["gold"] for r in rows if r["gold"]]
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


def test_ledger_policy_is_two_axes() -> None:
    """`ledger`：within->`{2,3}`、cross->`{0}` -> `two_axes`。"""
    result = _run("sample")

    assert result["axis_policy"] == "two_axes"

    evidence = result["axis_policy_evidence"]  # type: ignore[assignment]
    assert set(evidence["relation_within"]["values"]) == {2, 3}
    assert set(evidence["relation_cross"]["values"]) == {0}


def test_billing_policy_is_single_axis_not_merged() -> None:
    """**核心**：`billing` 没有 cross 查询 -> `single_axis`，不是 `merged`。

    按标注分组会得 `merged`（A={2}、C={2}）。按派生分组得 `single_axis`。
    而 `billing` 的 3 条 C 标注实为 within，所以"没有 cross 查询"才是事实。
    """
    result = _run("billing")

    assert result["axis_policy"] == "single_axis", (
        "billing 的 3 条 C 标注在池结构上都是 within，"
        "所以不存在 cross 轴——不是'两轴合并'"
    )

    evidence = result["axis_policy_evidence"]  # type: ignore[assignment]
    assert set(evidence["relation_within"]["values"]) == {2}
    assert evidence["relation_cross"]["n"] == 0
    assert evidence["relation_cross"]["values"] == []


def test_axis_policy_evidence_matches_per_case() -> None:
    """证据必须与 `per_case` 的 `n_competitors` 逐条对得上。

    **这条防的是"证据是另算的一份"**：若 policy 用一个独立统计口径，
    它可能与 `per_case` 里的数不一致，而两个数都"看起来合理"。
    """
    for subject in ("sample", "billing"):
        result = _run(subject)
        evidence = result["axis_policy_evidence"]  # type: ignore[assignment]

        recomputed: dict[str, list[int]] = {
            "relation_within": [],
            "relation_cross": [],
        }
        for case in result["per_case"]:  # type: ignore[union-attr]
            if not case.get("has_gold") or case.get("skipped"):
                continue
            recomputed[str(case["axis"])].append(int(case["n_competitors"]))

        for axis, values in recomputed.items():
            assert evidence[axis]["n"] == len(values), (subject, axis)
            assert sorted(evidence[axis]["values"]) == sorted(set(values)), (
                subject,
                axis,
            )


def test_axis_policy_is_a_function_of_values_not_counts() -> None:
    """样本量不参与判定：改条数不改 policy。"""
    from evals.run_retrieval import axis_policy_from_per_case

    def cases(within: int, cross: int) -> list[dict[str, object]]:
        return (
            [
                {"axis": "relation_within", "n_competitors": 2, "has_gold": True}
                for _ in range(within)
            ]
            + [
                {"axis": "relation_cross", "n_competitors": 2, "has_gold": True}
                for _ in range(cross)
            ]
        )

    # 9 条 vs 3 条：结构相同（都是 {2}）-> merged
    assert axis_policy_from_per_case(cases(9, 3))[0] == "merged"
    # 1 条 vs 3 条：结构相同 -> 仍 merged
    assert axis_policy_from_per_case(cases(1, 3))[0] == "merged"


def test_axis_policy_reports_no_axis_when_no_scored_cases() -> None:
    """没有可评分的 case -> `no_axis`，不是 `single_axis`，也不是 `merged`。"""
    from evals.run_retrieval import axis_policy_from_per_case

    assert axis_policy_from_per_case([])[0] == "no_axis"
    assert (
        axis_policy_from_per_case(
            [{"axis": "relation_within", "n_competitors": 2, "has_gold": True, "skipped": True}]
        )[0]
        == "no_axis"
    )
