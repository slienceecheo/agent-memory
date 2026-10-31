"""缺陷 23：`parse_condition` 用子串匹配，短别名命中长词，产生假槽位。

**缺陷定义**：`_ALIASES` 的匹配是 `if alias.casefold() in folded`——子串包含。
于是短别名会命中包含它的长词，给出语义上不该有的槽位。

| 短别名 | 被误命中的词 | 语义上应得 |
|---|---|---|
| `day` = `time:day` | `holiday` | 只有 `time:holiday` |
| `开发` = `activity:coding` | `开发环境` | 只有 `env:development` |
| `开发` = `activity:coding` | `功能开发` | 只有 `activity:feature` |

**为什么这是行为缺陷而不是死代码**：
`condition_match` 在 `src/memory/retrieval/rerank.py:111` 与
`evals/run_retrieval.py:571` 都是生产路径。

**为什么现在不修**：三种修法各有代价，都需要设计决策。

- 甲（词边界）：中文没有词边界，只对英文有效
- 乙（最长匹配优先）：绕不开"`开发环境` 该不该同时给两个槽位"
- 丙（精确匹配）：数据集里 3 个值会退化为 `raw`

这些测试**锁定现状**，不是认可它。修好后它们会红，届时翻面为正向断言。
"""

from __future__ import annotations

import pytest

from memory.retrieval.condition import _ALIASES, condition_match, parse_condition


@pytest.mark.locked_defect
def test_defect23_false_positives_are_real() -> None:
    """三对子串误命中确实产生多余槽位。

    若哪天匹配改成词边界/精确/最长优先，这里会红——那时翻面。
    """
    assert parse_condition("holiday").slots == frozenset(
        {"time:day", "time:holiday"}
    ), "holiday 不再多给 time:day，缺陷 23 可能已修"

    assert parse_condition("开发环境").slots == frozenset(
        {"activity:coding", "env:development"}
    ), "开发环境 不再多给 activity:coding，缺陷 23 可能已修"

    assert parse_condition("功能开发").slots == frozenset(
        {"activity:coding", "activity:feature"}
    ), "功能开发 不再多给 activity:coding，缺陷 23 可能已修"


@pytest.mark.locked_defect
def test_defect23_produces_a_false_positive_similarity() -> None:
    """语义无关的两个条件，因为共享误命中槽位而得到 0.5。

    0.5 在本模块的口径里表示"一方没提条件"，而这里两边都提了。
    **这个 0.5 是巧合，不是设计。**
    """
    assert condition_match("开发环境", "写代码") == pytest.approx(0.5)
    assert condition_match("功能开发", "写代码") == pytest.approx(0.5)


@pytest.mark.locked_defect
def test_defect23_chinese_english_pair_is_not_equal() -> None:
    """`holiday` 与 `节假日` 这对"中英对照"实际不相等。

    而 `tests/retrieval/test_condition.py` 的 parametrize 用的是
    `assert expected_slot in parsed.slots`（子集断言），所以多出来的槽位看不见，
    4 条 parametrize 全绿。
    """
    en = parse_condition("holiday").slots
    zh = parse_condition("节假日").slots

    assert en != zh
    assert en - zh == frozenset({"time:day"})


@pytest.mark.locked_defect
def test_defect23_is_exactly_three_collisions() -> None:
    """子串误命中恰好 3 对。数字变了说明词表或匹配规则被改过。"""
    collisions = [
        (short, long)
        for short in _ALIASES
        for long in _ALIASES
        if short != long
        and short.casefold() in long.casefold()
        and _ALIASES[short] != _ALIASES[long]
    ]

    assert len(collisions) == 3, f"子串误命中变成 {len(collisions)} 对：{collisions}"


@pytest.mark.locked_defect
def test_defect23_spec_example_does_not_match() -> None:
    """spec 举的例子 `应酬 / client dinner` 实测 0.000。

    `client_dinner`（下划线）才是 1.000。
    **修 spec 例子会让这条 scenario 从失败变通过，而实现没变**——
    所以必须与缺陷 23 同时处置，否则只是降低了标准。
    """
    assert condition_match("应酬", "client dinner") == pytest.approx(0.0)
    assert condition_match("应酬", "client_dinner") == pytest.approx(1.0)

    assert "client dinner" not in _ALIASES
    assert "client_dinner" in _ALIASES


@pytest.mark.locked_defect
def test_defect23_exact_matching_would_break_three_values() -> None:
    """丙方案（精确匹配）的代价：3 个数据集值退化为 `raw`。

    这条锁定的是"为什么不能简单改成精确匹配"——它是设计决策的证据。
    """
    folded = {a.casefold() for a in _ALIASES}
    affected = [
        v
        for v in ("工作日白天", "本地开发", "生产环境")
        if v.casefold() not in folded and parse_condition(v).structured
    ]

    assert affected == ["工作日白天", "本地开发", "生产环境"]
