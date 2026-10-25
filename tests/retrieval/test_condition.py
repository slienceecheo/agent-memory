"""条件槽位的行为契约。

**为什么必须做**：`condition` 在存储里是不透明字符串，
不结构化就无法计算"条件是否匹配"。

**两个真实缺陷必须避免**（审查实测）：

1. **词表不匹配**：dev/test 用英文（`coding`、`prod`），
   independent 用中文（`法定节假日`、`客户应酬`）。
   只列中文示例会让大多数条件 `structured=False`，特征全部退化成中性 0.5。
2. **中英必须归一到同一键**：`coding` 与 `写代码` 是同一个条件，
   不能因为语言不同就算不匹配。
"""

from __future__ import annotations

import pytest

from memory.retrieval.condition import (
    ParsedCondition,
    condition_match,
    parse_condition,
)


def test_english_condition_is_structured() -> None:
    parsed = parse_condition("coding")

    assert parsed.structured is True
    assert parsed.slots


def test_chinese_condition_is_structured() -> None:
    parsed = parse_condition("写代码")

    assert parsed.structured is True


def test_chinese_and_english_map_to_same_slot() -> None:
    """同一条件的中英表达必须归一到同一键，否则跨语言永远不匹配。"""
    zh = parse_condition("写代码")
    en = parse_condition("coding")

    assert zh.slots == en.slots


def test_prod_and_chinese_equivalent() -> None:
    assert parse_condition("prod").slots == parse_condition("生产").slots


def test_meeting_condition() -> None:
    assert parse_condition("meeting").slots == parse_condition("开会").slots


@pytest.mark.parametrize(
    ("text", "expected_slot"),
    [
        ("coding", "activity:coding"),
        ("写代码", "activity:coding"),
        ("meeting", "activity:meeting"),
        ("开会", "activity:meeting"),
        ("prod", "env:production"),
        ("生产", "env:production"),
        ("local", "env:local"),
        ("本地", "env:local"),
        ("节假日", "time:holiday"),
        ("法定节假日", "time:holiday"),
        ("night", "time:night"),
        ("深夜", "time:night"),
        ("morning", "time:morning"),
        ("早上", "time:morning"),
    ],
)
def test_known_expressions_map_to_slots(text: str, expected_slot: str) -> None:
    parsed = parse_condition(text)

    assert expected_slot in parsed.slots


def test_client_dinner_maps_to_activity() -> None:
    """"应酬"是业务场景，不是时间。"""
    parsed = parse_condition("客户应酬")

    assert "activity:client_dinner" in parsed.slots


def test_unknown_condition_keeps_raw_and_flags() -> None:
    """未登记的整体保留，且标记未结构化——让覆盖率可统计。"""
    parsed = parse_condition("某个完全没见过的条件")

    assert parsed.structured is False
    assert parsed.slots
    assert any("某个完全没见过的条件" in slot for slot in parsed.slots)


def test_none_condition_is_structured_and_empty() -> None:
    """无条件是合法状态，不该被算作"未结构化"。"""
    parsed = parse_condition(None)

    assert parsed.structured is True
    assert parsed.slots == frozenset()


def test_empty_string_treated_as_none() -> None:
    parsed = parse_condition("   ")

    assert parsed.slots == frozenset()


# ---------- 匹配度 ----------


def test_identical_conditions_match_fully() -> None:
    assert condition_match("coding", "coding") == pytest.approx(1.0)


def test_cross_language_conditions_match() -> None:
    """这是中英双向词表的直接收益。"""
    assert condition_match("写代码", "coding") == pytest.approx(1.0)


def test_different_conditions_do_not_match() -> None:
    assert condition_match("coding", "meeting") == pytest.approx(0.0)


def test_both_absent_is_neutral() -> None:
    """两侧都没有条件时，不该给满分（那会让"无条件"压过"条件匹配"）。"""
    assert condition_match(None, None) == pytest.approx(0.5)


def test_one_side_absent_is_neutral() -> None:
    """一方缺失时取中性，而不是 0——"没说条件"不等于"条件不符"。"""
    assert condition_match("coding", None) == pytest.approx(0.5)
    assert condition_match(None, "meeting") == pytest.approx(0.5)


def test_partial_overlap_is_between_zero_and_one() -> None:
    left = ParsedCondition(slots=frozenset({"activity:coding", "time:night"}), structured=True)
    right = ParsedCondition(slots=frozenset({"activity:coding", "env:prod"}), structured=True)

    score = condition_match(left, right)

    assert 0.0 < score < 1.0


def test_match_accepts_parsed_objects() -> None:
    left = parse_condition("coding")
    right = parse_condition("写代码")

    assert condition_match(left, right) == pytest.approx(1.0)


def test_unstructured_both_sides_do_not_crash() -> None:
    assert 0.0 <= condition_match("未知甲", "未知乙") <= 1.0
