"""答案匹配指标的行为契约。

`substring_exact_match` 是 FactConsolidation 的官方口径，必须与官方一致，
否则所有分数都不可比。这些测试用字面期望值，不复用被测代码的逻辑。
"""

from __future__ import annotations

import pytest

from memory.eval.metrics import substring_exact_match


@pytest.mark.parametrize(
    ("gold", "prediction"),
    [
        ("Paris", "Paris"),
        ("paris", "  Paris  "),
        ("Paris", "The answer is Paris."),
        ("北京", "北京。"),
        ("北京", "答案是北京"),
        ("42", "The count is 42"),
    ],
)
def test_matches(gold: str, prediction: str) -> None:
    """去掉归一化会让大小写/空白/中文标点全部漏判。"""
    assert substring_exact_match(gold, prediction) is True


@pytest.mark.parametrize(
    ("gold", "prediction"),
    [
        ("Paris", "London"),
        ("Paris", ""),
        ("北京", "上海"),
    ],
)
def test_non_matches(gold: str, prediction: str) -> None:
    """过度宽松（比如只比首字符）会让命中率虚高。"""
    assert substring_exact_match(gold, prediction) is False


def test_numeric_prefix_is_a_known_false_positive() -> None:
    """官方口径的已知弱点：`42` 是 `421` 的子串，因此判为命中。

    这条测试是**特征锁定**，不是正确性声明。它存在的意义：
    如果有人"顺手优化"成词边界匹配，与官方分数就不再可比，
    这条测试会立刻失败并提醒必须同步修改报告口径。
    """
    assert substring_exact_match("42", "421") is True


def test_empty_prediction_is_false_not_error() -> None:
    """空预测若抛异常，一条坏样本会中断整次评测。"""
    assert substring_exact_match("x", "") is False


def test_empty_gold_raises() -> None:
    """空标准答案无法用于子串匹配，静默返回 False 会污染分数。"""
    with pytest.raises(ValueError, match="空"):
        substring_exact_match("", "anything")


def test_whitespace_only_gold_raises() -> None:
    """只有空白的标准答案同样是无效数据。"""
    with pytest.raises(ValueError, match="空"):
        substring_exact_match("   ", "anything")


def test_none_prediction_is_false() -> None:
    """未产出答案的样本必须算未命中，而不是让整批崩掉。"""
    assert substring_exact_match("x", None) is False


def test_casefold_handles_turkish_i() -> None:
    """用 lower() 会在土耳其语等场景出错；这里只锁定大小写不敏感这一契约。"""
    assert substring_exact_match("ISTANBUL", "istanbul") is True


def test_unicode_normalization_is_applied() -> None:
    """全角与半角数字不同码位，不做 NFKC 会漏判。"""
    assert substring_exact_match("42", "４２") is True
