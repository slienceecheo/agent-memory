"""F19a 与 F19b 必须分开：数据完整 ≠ 能被召回。

**这是"名字覆盖两件事、实现只做一件"的又一实例。**

F19 原名"implicit 查询的 gold 可被召回"，实现却只检查
"gold 在 memories.jsonl 里且有 memory_text"。

两者在当前样例上恰好等价（12/12 都能召回），但机制不同：

| 检查 | 做法 |
|---|---|
| 数据完整性（F19a） | gold 在库且有原文 |
| 可被召回（F19b） | 真跑一次召回，看 gold 是否出现在返回列表里 |

**实测反例**：`ledger-q3` 的 gold（林晓）在库、有原文，
但**词面路径召回 0 条**。只看 F19a 它通过，而那 0 分实际是召回失败。
"""

from __future__ import annotations

from pathlib import Path

import pytest
from evals.datasets.retrieval_v2 import load_dataset
from evals.tools.check_v2_dataset import (
    check_f19a_implicit_gold_complete,
    check_f19b_implicit_gold_recalled,
)

ROOT = Path(__file__).resolve().parents[2]
SAMPLE = ROOT / "data" / "retrieval-v2" / "sample"
ABLATION = ROOT / "results" / "v2-sample-condition-ablation.json"


def test_f19a_and_f19b_are_separate_checks() -> None:
    """两条门禁的代码不同、编号不同。"""
    a = check_f19a_implicit_gold_complete
    b = check_f19b_implicit_gold_recalled

    assert a is not b
    assert "F19a" in a.__doc__ or "F19a" in (a.__doc__ or "")
    assert "F19b" in b.__doc__ or "F19b" in (b.__doc__ or "")


def test_f19a_checks_fields_only() -> None:
    """F19a 只读数据集字段，不跑评测。"""
    if not SAMPLE.exists():
        pytest.skip("样例数据集缺失")

    result = check_f19a_implicit_gold_complete(load_dataset(SAMPLE))

    assert result.code == "F19a"
    assert result.passed
    assert "gold 都在库且有原文" in result.detail


def test_f19b_filters_to_implicit_only() -> None:
    """F19b 只统计 implicit，C 轴召回失败不应影响它。

    **这是它第一次实现里的缺陷**：变量名叫 `implicit_no_recall`，
    装的却是**全部** case（含 C 轴），且从未按 `cue_type` 过滤。
    """
    if not SAMPLE.exists() or not ABLATION.exists():
        pytest.skip("样例数据集或消融结果缺失")

    dataset = load_dataset(SAMPLE)
    result = check_f19b_implicit_gold_recalled(dataset)

    implicit_count = sum(
        1 for q in dataset.queries if q.cue_type.value == "implicit"
    )
    assert result.code == "F19b"
    assert result.passed
    assert f"{implicit_count} 条 implicit" in result.detail

    # 全数据集条数应当更多——若两者相等，说明过滤没生效
    total = len(dataset.queries)
    assert implicit_count < total


def test_f19b_reads_ablation_result() -> None:
    """F19b 读消融结果里的 `with_condition`，不重复跑评测。"""
    if not SAMPLE.exists() or not ABLATION.exists():
        pytest.skip("消融结果缺失")

    result = check_f19b_implicit_gold_recalled(load_dataset(SAMPLE))

    assert result.code == "F19b"
    assert result.passed
    assert "全部被召回" in result.detail


def test_f19a_passes_even_when_lexical_recall_fails() -> None:
    """**核心**：F19a 通过不意味着召回成功。

    实测 q3 的 gold 在库有原文（F19a 通过），但词面召回 0 条。
    这正是需要 F19b 的理由。
    """
    if not SAMPLE.exists():
        pytest.skip("样例数据集缺失")

    dataset = load_dataset(SAMPLE)
    q3 = next(q for q in dataset.queries if q.query_id == "ledger-q3")
    gold = dataset.memory(q3.gold_memory_id)

    # F19a 检查的两项都满足
    assert gold.memory_text.strip()
    assert q3.query.strip()

    # 但词面召回是 0——需要 F19b 才能发现
    lexical_result = ROOT / "results" / "v2-lexical.json"
    if not lexical_result.exists():
        pytest.skip("词面结果缺失")
    import json

    payload = json.loads(lexical_result.read_text(encoding="utf-8"))
    case = next(c for c in payload["per_case"] if c["case_id"] == "ledger-q3")
    assert case["path_returns"]["lexical"] == 0


def test_both_gates_are_in_run_all() -> None:
    """两条都必须收进 `run_all()`，不能只留在独立脚本里。"""
    from evals.tools.check_v2_dataset import ALL_CHECKS

    codes = {check.__name__ for check in ALL_CHECKS}

    assert "check_f19a_implicit_gold_complete" in codes
    assert "check_f19b_implicit_gold_recalled" in codes
    assert "check_f20_condition_contributes" in codes
