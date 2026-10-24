"""变更识别的模型兜底与禁用模式。

三种失败都必须有明确出口：
- 模型返回乱码 → 视为"无法确认"，走 CONFLICT 兜底，不能猜测
- 模型抛异常 → 标记 failed，异常不能吞掉原因
- 禁用模型 → 完全不调用，标记 disabled
"""

from __future__ import annotations

import pytest

from memory.llm.client import LLMError, LLMResult
from memory.llm.sse import Usage
from memory.resolver.change_marker import (
    ChangeSource,
    classify_with_llm,
    detect_change,
)


class _FakeLLM:
    def __init__(self, content: str = '{"is_new_state": true}', *, raises: Exception | None = None):
        self.content = content
        self.raises = raises
        self.calls = 0

    def complete(self, messages: object, **kwargs: object) -> LLMResult:
        self.calls += 1
        if self.raises is not None:
            raise self.raises
        return LLMResult(content=self.content, usage=Usage(), finish_reason="stop")


def test_rule_hit_does_not_call_llm() -> None:
    """规则能判断时不该花一次模型调用：慢且不可复现。"""
    llm = _FakeLLM()

    result = detect_change("现在改用 npm 了", llm=llm)

    assert result.source is ChangeSource.RULE
    assert llm.calls == 0


def test_rule_miss_falls_back_to_llm() -> None:
    llm = _FakeLLM('{"is_new_state": true}')

    result = detect_change("我们用 npm", llm=llm)

    assert result.source is ChangeSource.LLM
    assert result.is_new_state is True
    assert llm.calls == 1


def test_llm_false_is_respected() -> None:
    """模型说"不是新状态"时必须采纳，否则会覆盖用户的原有事实。"""
    llm = _FakeLLM('{"is_new_state": false}')

    result = detect_change("我们用 npm", llm=llm)

    assert result.is_new_state is False
    assert result.source is ChangeSource.LLM


def test_unparsable_output_is_marked_failed() -> None:
    """乱码不能当成 false 悄悄放过去——要标记出来，让上层走兜底。"""
    llm = _FakeLLM("我不太确定")

    result = detect_change("我们用 npm", llm=llm)

    assert result.source is ChangeSource.FAILED
    assert result.is_new_state is False


def test_unparsable_does_not_crash() -> None:
    llm = _FakeLLM("")

    result = detect_change("我们用 npm", llm=llm)

    assert result.source is ChangeSource.FAILED


def test_llm_exception_is_marked_failed() -> None:
    """模型不可用时不能让整个判定崩掉，但必须留下痕迹。"""
    llm = _FakeLLM(raises=LLMError("gateway down"))

    result = detect_change("我们用 npm", llm=llm)

    assert result.source is ChangeSource.FAILED
    assert result.is_new_state is False


def test_disabled_mode_never_calls_llm() -> None:
    """消融实验的基础：禁用模式必须完全不碰模型。"""
    llm = _FakeLLM()

    result = detect_change("我们用 npm", llm=llm, allow_llm=False)

    assert result.source is ChangeSource.DISABLED
    assert result.is_new_state is False
    assert llm.calls == 0


def test_disabled_mode_still_succeeds_on_rule_hit() -> None:
    """禁用模型不该影响规则能判断的情形。"""
    result = detect_change("现在改用 npm 了", allow_llm=False)

    assert result.source is ChangeSource.RULE
    assert result.is_new_state is True


def test_bare_true_is_accepted() -> None:
    """有些模型只输出 true，不必强求 JSON。"""
    result = classify_with_llm(_FakeLLM("true"), "我们用 npm")

    assert result.is_new_state is True
    assert result.source is ChangeSource.LLM


@pytest.mark.parametrize(
    "content",
    [
        '{"is_new_state": true}',
        '{"is_new_state":true}',
        'Result: {"is_new_state": true}',
        "TRUE",
    ],
)
def test_lenient_parsing(content: str) -> None:
    """真实模型的输出格式不总是干净，但只在这些明确形态上放宽。"""
    result = classify_with_llm(_FakeLLM(content), "x")

    assert result.source is ChangeSource.LLM
    assert result.is_new_state is True
