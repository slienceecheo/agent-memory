"""检索评测入口的行为契约。

三个必须锁住的性质：

1. **池太小时跳过而不是给假分数**：`same_relation` 模式在独立集上
   选不出干扰项，若不跳过会得到 SEH=1.000 的假结果。
2. **结果 JSON 记录运行次数**：使"test 只跑一次"可验证。
3. **三种池模式分开报告**：跨模式比较会误导。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from evals.run_retrieval import evaluate, select_pool_distractors

from memory.retrieval.pool_modes import PoolMode

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data" / "conflict-set"


def _rows(name: str) -> list[dict[str, object]]:
    path = DATA / name
    if not path.exists():
        pytest.skip(f"{name} 不存在")
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _all_specs() -> list[dict[str, object]]:
    specs: list[dict[str, object]] = []
    for name in ("dev.jsonl", "test.jsonl", "independent.jsonl"):
        specs.extend([row["gold"] for row in _rows(name) if row.get("gold")])  # type: ignore[misc]
    return specs


def test_select_unrelated_returns_requested_count() -> None:
    specs = _all_specs()
    gold = specs[0]

    picked = select_pool_distractors(gold, specs, mode=PoolMode.UNRELATED, limit=20)

    assert len(picked) == 20


def test_select_same_relation_may_be_empty() -> None:
    """独立集里 28/29 个 relation 唯一，所以同 relation 干扰项常常为 0。

    这是数据的真实约束，不是实现缺陷。
    """
    specs = _all_specs()
    gold = next(s for s in specs if s.get("relation") == "wifi_password")

    picked = select_pool_distractors(gold, specs, mode=PoolMode.SAME_RELATION, limit=20)

    assert picked == []


def test_evaluate_skips_when_pool_too_small() -> None:
    """池不足 K 时必须跳过并计数，而不是给出 SEH=1.000。"""
    rows = _rows("independent.jsonl")
    specs = _all_specs()

    result = evaluate(
        rows,
        all_specs=specs,
        weights_name="uniform",
        enable_dedup=False,
        judge=None,
        k=5,
        pool_mode=PoolMode.SAME_RELATION,
    )

    assert result["skipped_small_pool"] > 0
    assert result["with_gold"] == 0
    assert result["seh_at_k"] == 0.0


def test_evaluate_records_pool_mode() -> None:
    rows = _rows("independent.jsonl")[:3]
    specs = _all_specs()

    result = evaluate(
        rows,
        all_specs=specs,
        weights_name="uniform",
        enable_dedup=False,
        judge=None,
        k=5,
        pool_mode=PoolMode.UNRELATED,
    )

    assert result["pool_mode"] == "unrelated"


def test_unrelated_pool_is_evaluable() -> None:
    """低难度模式必须有足够样本，否则整份报告没有数字。"""
    rows = _rows("independent.jsonl")
    specs = _all_specs()

    result = evaluate(
        rows,
        all_specs=specs,
        weights_name="uniform",
        enable_dedup=False,
        judge=None,
        k=5,
        pool_mode=PoolMode.UNRELATED,
    )

    assert result["with_gold"] >= 20


def test_attribution_has_all_three_keys() -> None:
    rows = _rows("independent.jsonl")
    specs = _all_specs()

    result = evaluate(
        rows,
        all_specs=specs,
        weights_name="uniform",
        enable_dedup=False,
        judge=None,
        k=5,
        pool_mode=PoolMode.UNRELATED,
    )

    assert set(result["attribution"]) == {"NOT_IN_POOL", "LOW_RANK", "RERANK_DROPPED"}


def test_without_gold_cases_are_counted() -> None:
    """ADD 类场景没有 gold，必须被计数而不是静默消失。"""
    rows = _rows("independent.jsonl")
    specs = _all_specs()

    result = evaluate(
        rows,
        all_specs=specs,
        weights_name="uniform",
        enable_dedup=False,
        judge=None,
        k=5,
        pool_mode=PoolMode.UNRELATED,
    )

    assert result["without_gold"] == 4


def test_low_difficulty_scores_are_locked() -> None:
    """低难度模式的分数锁定在 SEH=1.0。

    这个数字**不代表检索能力强**，只代表"在无关记忆里能找到相关的"。
    若它变化，说明池构造或召回逻辑被改动了。
    """
    rows = _rows("independent.jsonl")
    specs = _all_specs()

    result = evaluate(
        rows,
        all_specs=specs,
        weights_name="uniform",
        enable_dedup=False,
        judge=None,
        k=5,
        pool_mode=PoolMode.UNRELATED,
    )

    assert result["seh_at_k"] == pytest.approx(1.0)
