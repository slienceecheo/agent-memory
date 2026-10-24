"""变更标记识别的行为契约（规则部分）。

正则要同时满足两件事：
- 覆盖常见的中文变更表达（否则全走 LLM，慢且不可复现）
- 不误判否定句（"没有改成"不该命中）

只写正例会让"过度匹配"这类错误漏过去，所以每条标记都配一条反例。
"""

from __future__ import annotations

import pytest

from memory.resolver.change_marker import (
    ChangeSource,
    detect_by_rules,
)


@pytest.mark.parametrize(
    "text",
    [
        "我们这个仓库现在改用 npm 了",
        "包管理器改成 pnpm",
        "不再用 yarn 了",
        "以前是 pnpm，现在用 npm",
        "把测试命令换成 pytest",
        "已经从 pnpm 迁移到 npm",
        "我们迁移到 bun 了",
        "现在统一走 npm",
    ],
)
def test_positive_markers_are_detected(text: str) -> None:
    """覆盖常见中文变更表达。缺一种就会多一次 LLM 调用，且不可复现。"""
    result = detect_by_rules(text)

    assert result is not None
    assert result.is_new_state is True
    assert result.source is ChangeSource.RULE


@pytest.mark.parametrize(
    "text",
    [
        "我们用 pnpm",
        "这个仓库使用 npm",
        "测试只跑 pytest",
        "包管理器是 pnpm",
    ],
)
def test_plain_statements_are_not_detected(text: str) -> None:
    """没有变更标记的陈述不该被当成新状态。"""
    assert detect_by_rules(text) is None


@pytest.mark.parametrize(
    "text",
    [
        "没有改成 npm",
        "还没换",
        "不用改",
        "不要改成 pnpm",
    ],
)
def test_negated_change_is_not_detected(text: str) -> None:
    """否定句若被当成变更，会把"保持原样"误判成"改成新值"。"""
    assert detect_by_rules(text) is None


def test_change_marker_returns_matched_phrase() -> None:
    """命中的标记要能展示给人看，用于解释判定依据。"""
    result = detect_by_rules("现在改用 npm 了")

    assert result is not None
    assert result.marker
    assert result.marker in "现在改用 npm 了"


def test_empty_text_returns_none() -> None:
    assert detect_by_rules("") is None
    assert detect_by_rules("   ") is None


def test_marker_is_case_insensitive_for_latin() -> None:
    """中英混排的文本里，拉丁部分的标记也应识别。"""
    result = detect_by_rules("We switched to npm now")

    assert result is not None
    assert result.is_new_state is True
