"""语义等价判断：等义 / 互补 / 无关。

**三分类而不是二分类**：C3 的 9 条语义错误里 6 条是 MERGE（互补）、
3 条是 NOOP（等义）。二分类会把它们混在一起，无法按类别报告"各修好几条"。

**只服务读路径**：等价判断用于检索层的去重与排序，
不参与 C3 的 `decide()`。让它回流会让"规则顺序"的测试失去意义。

**降级而非抛出**：模型失败或输出不可解析时按"无关"处理并记失败次数。
检索不能因为一次模型故障就整批失败——但失败必须可见。
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

_PROMPT = """判断下面两条陈述的关系。

- equivalent：两者说的是同一件事，字面不同但含义相同
- complementary：后者是前者的细化或补充，前者仍然成立
- unrelated：描述不同事实，或互相矛盾

只回答 JSON，三个值之一：equivalent / complementary / unrelated
不要输出其他内容。

第一条：{left}
第二条：{right}
"""


class Equivalence(StrEnum):
    EQUIVALENT = "equivalent"
    COMPLEMENTARY = "complementary"
    UNRELATED = "unrelated"


@dataclass(frozen=True, slots=True)
class EquivalenceResult:
    equivalence: Equivalence
    failed: bool
    cached: bool = False


def parse_equivalence(content: str) -> Equivalence | None:
    """从模型输出里抽三分类。

    **必须容错**：实测同一个提示词下，模型会返回
    `{"relation": "equivalent"}` / `{"关系": "包含"}` /
    `{"label": "complementary"}` / `{"answer": "complementary"}` 等
    多种键名。只认单一格式会让一半以上的响应被降级为"无关"，
    而那个降级看起来像"模型判断错了"。

    策略：不解析 JSON 结构，直接在全文里找类别关键字。
    """
    lowered = content.strip().casefold()
    if not lowered:
        return None

    # 先看英文（模型更常用），中文作为补充
    if "complementary" in lowered or "包含" in lowered or "补充" in lowered:
        return Equivalence.COMPLEMENTARY
    if "equivalent" in lowered or "等价" in lowered or "相同" in lowered or "同一" in lowered:
        return Equivalence.EQUIVALENT
    if "unrelated" in lowered or "无关" in lowered or "不同" in lowered:
        return Equivalence.UNRELATED
    return None


def _judge_prompt(left: str, right: str) -> str:
    return _PROMPT.format(left=left, right=right)


class EquivalenceJudge:
    """带进程内缓存的等价判断器。

    缓存是**对称的**（(a,b) 与 (b,a) 共用），因为三者关系都是对称的。
    这能显著减少调用：去重阶段会比较 top-K 内所有配对。
    """

    def __init__(self, *, llm: object, enabled: bool = True) -> None:
        self._llm = llm
        self._enabled = enabled
        self._cache: dict[tuple[str, str], EquivalenceResult] = {}
        self.calls = 0
        self.failure_count = 0

    @property
    def enabled(self) -> bool:
        return self._enabled

    @property
    def cache_size(self) -> int:
        return len(self._cache)

    def judge(self, left: str, right: str) -> EquivalenceResult:
        a = left.strip()
        b = right.strip()

        if a and a == b:
            return EquivalenceResult(Equivalence.EQUIVALENT, failed=False, cached=True)

        key = (a, b) if a <= b else (b, a)
        cached = self._cache.get(key)
        if cached is not None:
            return EquivalenceResult(cached.equivalence, cached.failed, cached=True)

        if not self._enabled:
            return EquivalenceResult(Equivalence.UNRELATED, failed=False)

        self.calls += 1
        try:
            result = self._llm.complete(  # type: ignore[attr-defined]
                [{"role": "user", "content": _judge_prompt(a, b)}],
                response_format={"type": "json_object"},
            )
        except Exception:
            self.failure_count += 1
            outcome = EquivalenceResult(Equivalence.UNRELATED, failed=True)
            self._cache[key] = outcome
            return outcome

        content = getattr(result, "content", "") or ""
        parsed = parse_equivalence(content)
        if parsed is None:
            self.failure_count += 1
            outcome = EquivalenceResult(Equivalence.UNRELATED, failed=True)
            self._cache[key] = outcome
            return outcome

        outcome = EquivalenceResult(parsed, failed=False)
        self._cache[key] = outcome
        return outcome


def classify_pair(llm: object, left: str, right: str) -> Equivalence:
    """单次判断，不共享缓存。用于一次性评估。"""
    return EquivalenceJudge(llm=llm).judge(left, right).equivalence


__all__ = [
    "Equivalence",
    "EquivalenceJudge",
    "EquivalenceResult",
    "classify_pair",
    "parse_equivalence",
]
