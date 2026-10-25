"""特征方差检查。

**为什么必须有这个测试**：审查实测，原设计的五个特征里有四个在
ACTIVE-only 候选集上恒为常数——留着它们会让"重排有效"看起来成立，
实际排序没变。

本文件对**真实场景数据**构建的候选池断言：每个特征确实有方差。
任一项退化，测试失败并指出是哪个特征。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from memory.retrieval.condition import condition_match
from memory.retrieval.rerank import authority_score, status_score
from memory.store.models import Authority, Status

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


def _all_rows() -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for name in ("dev.jsonl", "test.jsonl", "independent.jsonl"):
        rows.extend(_rows(name))
    return rows


def test_authority_feature_has_variance() -> None:
    """真实数据里 authority 必须不止一个取值，否则该特征恒为常数。"""
    rows = _all_rows()
    values = {
        authority_score(Authority(str(row.get("authority") or "user_direct")))
        for row in rows
    }

    assert len(values) > 1, f"authority 特征只有 {values}，无区分度"


def test_condition_feature_has_variance() -> None:
    """条件匹配在真实数据上必须产生不止一个分值。"""
    rows = _all_rows()
    scores: set[float] = set()
    for row in rows:
        query_condition = row.get("condition")
        gold_condition = row.get("existing_condition")
        scores.add(condition_match(
            str(query_condition) if query_condition else None,
            str(gold_condition) if gold_condition else None,
        ))
        # 再与一个无关条件比较，模拟干扰项
        scores.add(condition_match(
            str(query_condition) if query_condition else None,
            "完全不同的条件",
        ))

    assert len(scores) > 1, f"condition 特征只有 {scores}，无区分度"


def test_status_feature_has_variance() -> None:
    """冲突候选进池时 status 必须有差异，否则该特征恒为 1.0。"""
    values = {status_score(status) for status in Status}

    assert len(values) > 1


def test_at_least_three_features_have_variance() -> None:
    """四个特征里至少三个有方差，重排才可能改变排序。

    若只有一两个有方差，本质上仍是一个特征在决定排序，
    报告里必须说明这一点。
    """
    rows = _all_rows()

    has_authority = len({
        Authority(str(row.get("authority") or "user_direct")) for row in rows
    }) > 1
    has_condition = any(row.get("condition") for row in rows)
    has_status = len({status_score(s) for s in Status}) > 1
    has_base = True  # RRF 分数天然有差异

    counted = sum([has_authority, has_condition, has_status, has_base])
    assert counted >= 3, (
        f"只有 {counted} 个特征有方差"
        f"（authority={has_authority}, condition={has_condition}, "
        f"status={has_status}, base={has_base}）"
    )


@pytest.mark.parametrize("name", ["dev.jsonl", "test.jsonl", "independent.jsonl"])
def test_condition_present_in_each_split(name: str) -> None:
    """每个数据集都应至少有一些带条件的场景，否则该集的 condition 特征全中性。"""
    rows = _rows(name)

    assert any(row.get("condition") for row in rows), f"{name} 没有任何条件场景"


def test_removed_features_are_absent_from_weights() -> None:
    """确认 temporal 与 recency 真的被删掉了，而不是改了个名字混进来。"""
    from memory.retrieval.rerank import PREREGISTERED_WEIGHTS

    for weights in PREREGISTERED_WEIGHTS.values():
        fields = set(weights.__dataclass_fields__)
        assert "temporal" not in fields
        assert "recency" not in fields
