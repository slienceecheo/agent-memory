"""三条基线。

- `no-memory`：不给任何事实（下界）
- `full-context`：给全部事实（上界，但随长度爆炸）
- `naive-rag`：按词面相似度取 top-k（现实中最常见的做法）
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Sequence

from evals.baselines.base import Baseline, render_context

_TOKEN_PATTERN = re.compile(r"[a-z0-9]+|[\u4e00-\u9fff]")


def _tokens(text: str) -> list[str]:
    """英文按词、中文按单字切分。够用且无需分词依赖。"""
    return _TOKEN_PATTERN.findall(text.lower())


class NoMemoryBaseline(Baseline):
    name = "no-memory"
    strategy = "none"


class FullContextBaseline(Baseline):
    name = "full-context"
    strategy = "full"


class NaiveRagBaseline(Baseline):
    """词面 BM25 的极简近似：按查询词的重合度排序，取前 k 条。"""

    name = "naive-rag"
    strategy = "rag"

    def __init__(self, *, llm: object, tracer: object, top_k: int = 5, **_: object) -> None:
        super().__init__(llm=llm, tracer=tracer)  # type: ignore[arg-type]
        if top_k <= 0:
            raise ValueError("top_k 必须为正整数")
        self._top_k = top_k

    def _context(self, question: str, facts: Sequence[str]) -> str:
        if not facts:
            return ""
        query = Counter(_tokens(question))
        scored = []
        for index, fact in enumerate(facts):
            tokens = Counter(_tokens(fact))
            overlap = sum(min(count, query[token]) for token, count in tokens.items())
            # 同分时保留原始顺序（编号小者在前），保证可复现
            scored.append((-overlap, index, fact))
        scored.sort()
        selected = [fact for _, _, fact in scored[: self._top_k]]
        return render_context(selected, strategy="full")


BASELINES: tuple[str, ...] = ("no-memory", "full-context", "naive-rag")


class UnknownBaselineError(KeyError):
    """请求的基线名未注册。"""


def build_baseline(name: str, *, llm: object, tracer: object, **kwargs: object) -> Baseline:
    registry: dict[str, type[Baseline]] = {
        "no-memory": NoMemoryBaseline,
        "full-context": FullContextBaseline,
        "naive-rag": NaiveRagBaseline,
    }
    try:
        factory = registry[name]
    except KeyError:
        raise UnknownBaselineError(
            f"未知基线 {name!r}。可用基线：{', '.join(BASELINES)}"
        ) from None
    return factory(llm=llm, tracer=tracer, **kwargs)

