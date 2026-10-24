"""识别"这句话是在陈述新状态，还是在重复旧状态"。

为什么这件事必须做：没有任何确定性方法能区分
- "我们这个仓库现在改用 npm 了" → 新状态
- "我们用 npm" → 可能只是重复

**模型只在这里被允许参与判定**。理由：
1. 这是唯一真正需要语义理解的地方
2. 限制在单个二分类上，"不用模型会差多少"才能被测量（消融）
3. 模型的结论与规则结论在结果里分开标记，可归因

否定句必须被排除：`"没有改成 npm"` 若被判成变更，会把"保持原样"读成"改成新值"。
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from memory.resolver.rules import ChangeSource

__all__ = [
    "ChangeSource",
    "MarkerResult",
    "classify_with_llm",
    "detect_by_rules",
    "detect_change",
]


@dataclass(frozen=True, slots=True)
class MarkerResult:
    is_new_state: bool
    marker: str
    source: ChangeSource


# 变更标记。按长度降序匹配，让"以前…现在…"优先于单独的"现在"。
_POSITIVE_MARKERS: tuple[str, ...] = (
    "以前是",
    "以前用",
    "原本是",
    "原本用",
    "现在改用",
    "现在改用",
    "现在用",
    "改成",
    "换成",
    "改用",
    "不再用",
    "不再",
    "迁移到",
    "已经迁移",
    "从…迁移",
    "统一走",
    "统一用",
    "switched to",
    "migrated to",
    "now uses",
    "changed to",
    "no longer",
    "now using",
)

# 否定/未定标记：出现这些时视为"没有发生变更"
_NEGATIVE_MARKERS: tuple[str, ...] = (
    "没有改",
    "还没改",
    "没有换",
    "还没换",
    "不用改",
    "不要改",
    "不必改",
    "尚未",
    "没变",
    "not changed",
    "no change",
    "don't change",
    "didn't change",
)

_WHITESPACE = re.compile(r"\s+")


def _prepare(text: str) -> str:
    return _WHITESPACE.sub(" ", text.strip().lower())


def detect_by_rules(text: str) -> MarkerResult | None:
    """用正则识别变更标记。

    返回 None 表示"规则无法判断"，由调用方决定是否交给模型。
    注意：返回 None 不等于"不是变更"，只等于"不确定"。
    """
    prepared = _prepare(text)
    if not prepared:
        return None

    for negative in _NEGATIVE_MARKERS:
        if negative in prepared:
            return None

    for marker in _POSITIVE_MARKERS:
        if marker in prepared:
            return MarkerResult(is_new_state=True, marker=marker, source=ChangeSource.RULE)

    return None


_CHANGE_CLASSIFIER_PROMPT = """判断下面这句话是在"陈述一个新的状态"还是在"重复一个已有的状态"。

只回答一个 JSON：{"is_new_state": true} 或 {"is_new_state": false}
不要输出任何其他内容。

句子：{text}
"""


def classify_with_llm(llm: object, text: str) -> MarkerResult:
    """调用模型做二分类。

    解析失败或调用异常时返回 `is_new_state=False` + `source=FAILED`，
    让上层走 CONFLICT 兜底——宁可标冲突，也不猜测覆盖。
    """
    from memory.llm.client import LLMError

    prompt = _CHANGE_CLASSIFIER_PROMPT.replace("{text}", text)
    try:
        result = llm.complete(  # type: ignore[attr-defined]
            [{"role": "user", "content": prompt}],
            response_format={"type": "json_object"},
        )
    except (LLMError, Exception):
        return MarkerResult(
            is_new_state=False, marker="llm_error", source=ChangeSource.FAILED
        )

    content = getattr(result, "content", "") or ""
    parsed = _parse_bool(content)
    if parsed is None:
        return MarkerResult(
            is_new_state=False, marker="unparsable", source=ChangeSource.FAILED
        )
    return MarkerResult(is_new_state=parsed, marker="llm", source=ChangeSource.LLM)


def _parse_bool(content: str) -> bool | None:
    lowered = content.strip().lower()
    if '"is_new_state"' not in lowered:
        # 也接受裸的 true / false，但不猜测更复杂的输出
        if lowered in {"true", "false"}:
            return lowered == "true"
        return None
    if re.search(r'"is_new_state"\s*:\s*true', lowered):
        return True
    if re.search(r'"is_new_state"\s*:\s*false', lowered):
        return False
    return None


def detect_change(
    text: str,
    *,
    llm: object | None = None,
    allow_llm: bool = True,
) -> MarkerResult:
    """先走规则，未命中再按配置决定是否交给模型。

    返回的 `source` 明确区分四种来源，供消融统计。
    """
    rule_result = detect_by_rules(text)
    if rule_result is not None:
        return rule_result

    if not allow_llm or llm is None:
        return MarkerResult(
            is_new_state=False, marker="disabled", source=ChangeSource.DISABLED
        )

    return classify_with_llm(llm, text)
