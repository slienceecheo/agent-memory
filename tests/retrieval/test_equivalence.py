"""语义等价判断的行为契约。

**为什么是读路径而不是写路径**：C3 的 9 条语义错误看起来可以靠它修好，
但如果回流到写路径，C3 的判定就变成"规则 + 模型"，
此前所有关于规则顺序的测试都失去意义。所以它只服务检索。

**为什么是三分类**：C3 的 9 条里 6 条是 MERGE（互补）、3 条是 NOOP（等义）。
二分类会把它们混在一起，无法回答"各修好几条"。
"""

from __future__ import annotations

import pytest

from memory.llm.client import LLMError, LLMResult
from memory.llm.sse import Usage
from memory.retrieval.equivalence import (
    Equivalence,
    EquivalenceJudge,
    classify_pair,
    parse_equivalence,
)


class _FakeLLM:
    def __init__(
        self,
        content: str = '{"relation": "equivalent"}',
        *,
        raises: Exception | None = None,
    ):
        self.content = content
        self.raises = raises
        self.calls = 0

    def complete(self, messages: object, **kwargs: object) -> LLMResult:
        self.calls += 1
        if self.raises is not None:
            raise self.raises
        return LLMResult(content=self.content, usage=Usage(), finish_reason="stop")


# ---------- 解析 ----------


@pytest.mark.parametrize(
    ("content", "expected"),
    [
        ('{"relation": "equivalent"}', Equivalence.EQUIVALENT),
        ('{"relation": "complementary"}', Equivalence.COMPLEMENTARY),
        ('{"relation": "unrelated"}', Equivalence.UNRELATED),
        ('{"relation":"EQUIVALENT"}', Equivalence.EQUIVALENT),
        ('result: {"relation": "complementary"}', Equivalence.COMPLEMENTARY),
    ],
)
def test_parse_known_values(content: str, expected: Equivalence) -> None:
    assert parse_equivalence(content) is expected


@pytest.mark.parametrize(
    ("content", "expected"),
    [
        ('{"关系":"包含"}', Equivalence.COMPLEMENTARY),
        ('{"relation":"neutral"}', None),
        ('{"label":"complementary"}', Equivalence.COMPLEMENTARY),
        ('{"answer":"complementary"}', Equivalence.COMPLEMENTARY),
        ('{"关系":"等价"}', Equivalence.EQUIVALENT),
        ('{"关系":"无关"}', Equivalence.UNRELATED),
    ],
)
def test_parse_tolerates_other_key_names(content: str, expected: Equivalence | None) -> None:
    """实测模型会返回 `关系` / `label` / `answer` 等不同键名。

    只认单一格式会让一半响应被降级为"无关"，而那个降级看起来像
    "模型判断错了"——这是最难发现的一类失真。
    """
    assert parse_equivalence(content) is expected


def test_complementary_takes_priority_over_equivalent() -> None:
    """解释性输出可能同时出现"相同"与"补充"，必须优先取互补。

    理由：判成互补只是保守地保留两条，判成等义会真的合并掉一条。
    宁可少合并，不可错合并。
    """
    content = '两者有相同主题，但后者是补充，所以 {"relation": "complementary"}'

    assert parse_equivalence(content) is Equivalence.COMPLEMENTARY


@pytest.mark.parametrize(
    "content",
    ["", "我不确定", '{"relation": "maybe"}', "{}"],
)
def test_parse_unknown_returns_none(content: str) -> None:
    """解析不了时必须返回 None，让调用方走降级，而不是猜一个。"""
    assert parse_equivalence(content) is None


# ---------- 三分类语义 ----------


def test_equivalent_pair() -> None:
    judge = EquivalenceJudge(llm=_FakeLLM('{"relation": "equivalent"}'))

    result = judge.judge("每周日凌晨维护", "每周日零点维护")

    assert result.equivalence is Equivalence.EQUIVALENT
    assert result.failed is False


def test_complementary_pair() -> None:
    judge = EquivalenceJudge(llm=_FakeLLM('{"relation": "complementary"}'))

    result = judge.judge("靠窗那一排", "C区第三排左数第二个工位")

    assert result.equivalence is Equivalence.COMPLEMENTARY


def test_unrelated_pair() -> None:
    judge = EquivalenceJudge(llm=_FakeLLM('{"relation": "unrelated"}'))

    result = judge.judge("我用 pnpm", "今天天气不错")

    assert result.equivalence is Equivalence.UNRELATED


# ---------- 降级 ----------


def test_unparsable_output_degrades_to_unrelated() -> None:
    """审查要求：解析失败按"无关"处理，检索继续。"""
    judge = EquivalenceJudge(llm=_FakeLLM("我不确定"))

    result = judge.judge("a", "b")

    assert result.equivalence is Equivalence.UNRELATED
    assert result.failed is True


def test_exception_degrades_to_unrelated() -> None:
    judge = EquivalenceJudge(llm=_FakeLLM(raises=LLMError("gateway down")))

    result = judge.judge("a", "b")

    assert result.equivalence is Equivalence.UNRELATED
    assert result.failed is True


def test_failure_count_is_tracked() -> None:
    """失败次数要能被报告出来，否则"降级"是静默的。"""
    judge = EquivalenceJudge(llm=_FakeLLM("乱码"))

    judge.judge("a", "b")
    judge.judge("c", "d")

    assert judge.failure_count == 2


# ---------- 关闭 ----------


def test_disabled_never_calls_llm() -> None:
    """消融的基础：关闭时完全不碰模型。"""
    llm = _FakeLLM()
    judge = EquivalenceJudge(llm=llm, enabled=False)

    result = judge.judge("a", "b")

    assert llm.calls == 0
    assert judge.calls == 0
    assert result.equivalence is Equivalence.UNRELATED


def test_disabled_still_returns_valid_result() -> None:
    judge = EquivalenceJudge(llm=_FakeLLM(), enabled=False)

    result = judge.judge("同一条", "同一条")

    assert result is not None


# ---------- 缓存与调用计数 ----------


def test_identical_pair_uses_cache() -> None:
    """同一对重复判断不该重复调用模型。"""
    llm = _FakeLLM()
    judge = EquivalenceJudge(llm=llm)

    judge.judge("a", "b")
    judge.judge("a", "b")

    assert llm.calls == 1
    assert judge.calls == 1


def test_order_does_not_matter_for_cache() -> None:
    """等义关系是对称的，(a,b) 与 (b,a) 应共用缓存。"""
    llm = _FakeLLM()
    judge = EquivalenceJudge(llm=llm)

    judge.judge("a", "b")
    judge.judge("b", "a")

    assert llm.calls == 1


def test_identical_strings_short_circuit() -> None:
    """完全相同的一对没有歧义，不必调模型。"""
    llm = _FakeLLM()
    judge = EquivalenceJudge(llm=llm)

    result = judge.judge("同一条", "同一条")

    assert llm.calls == 0
    assert result.equivalence is Equivalence.EQUIVALENT


def test_classify_pair_helper() -> None:
    """便捷接口：单次判断，不共享缓存。"""
    llm = _FakeLLM('{"relation": "complementary"}')

    assert classify_pair(llm, "a", "b") is Equivalence.COMPLEMENTARY
