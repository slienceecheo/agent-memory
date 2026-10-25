"""去重阶段的行为契约。

**为什么必须有这个消费者**：审查指出，原设计实现了等价判断但**没有任何地方
调用它**，所以它不可能改变任何被测量的结果。E5 只是在 9 条手写对上测分类器。

本阶段的产出必须是**可观测的**：去重前后的候选数变化。
"""

from __future__ import annotations

from memory.llm.client import LLMResult
from memory.llm.sse import Usage
from memory.retrieval.dedup import dedup
from memory.retrieval.equivalence import EquivalenceJudge


class _ScriptedLLM:
    """按预设答案回答，用于构造确定的等价关系。"""

    def __init__(self, answers: dict[frozenset[str], str]) -> None:
        self._answers = answers
        self.calls = 0

    def complete(self, messages: object, **kwargs: object) -> LLMResult:
        self.calls += 1
        text = str(messages[0]["content"])  # type: ignore[index]
        for pair, answer in self._answers.items():
            if all(item in text for item in pair):
                return LLMResult(
                    content=f'{{"relation": "{answer}"}}',
                    usage=Usage(),
                    finish_reason="stop",
                )
        return LLMResult(
            content='{"relation": "unrelated"}', usage=Usage(), finish_reason="stop"
        )


def _judge(answers: dict[frozenset[str], str], *, enabled: bool = True) -> EquivalenceJudge:
    return EquivalenceJudge(llm=_ScriptedLLM(answers), enabled=enabled)


def test_equivalent_candidates_are_merged() -> None:
    judge = _judge({frozenset({"甲", "乙"}): "equivalent"})
    ranked = [("id1", "甲", 1.0), ("id2", "乙", 0.9), ("id3", "丙", 0.5)]

    kept, stats = dedup(ranked, judge=judge)

    assert [item[0] for item in kept] == ["id1", "id3"]
    assert stats.merged == 1


def test_higher_scored_item_is_kept() -> None:
    """合并时保留融合分更高的那条。"""
    judge = _judge({frozenset({"甲", "乙"}): "equivalent"})
    ranked = [("id1", "乙", 0.5), ("id2", "甲", 1.0)]

    kept, _ = dedup(ranked, judge=judge)

    assert [item[0] for item in kept] == ["id2"]


def test_complementary_is_not_merged() -> None:
    """互补意味着两者都有价值，不能合并——那会丢信息。"""
    judge = _judge({frozenset({"甲", "乙"}): "complementary"})
    ranked = [("id1", "甲", 1.0), ("id2", "乙", 0.9)]

    kept, stats = dedup(ranked, judge=judge)

    assert len(kept) == 2
    assert stats.merged == 0


def test_unrelated_is_not_merged() -> None:
    judge = _judge({})
    ranked = [("id1", "甲", 1.0), ("id2", "乙", 0.9)]

    kept, _ = dedup(ranked, judge=judge)

    assert len(kept) == 2


def test_disabled_dedup_changes_nothing() -> None:
    """关闭时代价为零，且候选数不变——这是消融的可观测产出。"""
    judge = _judge({frozenset({"甲", "乙"}): "equivalent"}, enabled=False)
    ranked = [("id1", "甲", 1.0), ("id2", "乙", 0.9)]

    kept, stats = dedup(ranked, judge=judge)

    assert len(kept) == 2
    assert stats.compared == 0


def test_stats_record_input_and_output_counts() -> None:
    judge = _judge({frozenset({"甲", "乙"}): "equivalent"})
    ranked = [("id1", "甲", 1.0), ("id2", "乙", 0.9), ("id3", "丙", 0.5)]

    _, stats = dedup(ranked, judge=judge)

    assert stats.before == 3
    assert stats.after == 2


def test_only_top_k_are_compared() -> None:
    """只对前 K 条比较，否则每对的模型调用会随候选数平方增长。"""
    judge = _judge({frozenset({"甲", "丁"}): "equivalent"})
    ranked = [("id1", "甲", 1.0), ("id2", "乙", 0.9), ("id3", "丙", 0.8), ("id4", "丁", 0.1)]

    kept, stats = dedup(ranked, judge=judge, top_k=2)

    assert len(kept) == 4
    assert stats.compared <= 1


def test_empty_input() -> None:
    judge = _judge({})

    kept, stats = dedup([], judge=judge)

    assert kept == []
    assert stats.before == 0


def test_single_item_no_comparison() -> None:
    judge = _judge({})

    kept, stats = dedup([("id1", "甲", 1.0)], judge=judge)

    assert len(kept) == 1
    assert stats.compared == 0


def test_order_preserved_after_merge() -> None:
    """合并后剩余条目的相对顺序不变，否则排名语义被破坏。"""
    judge = _judge({frozenset({"乙", "丙"}): "equivalent"})
    ranked = [
        ("id1", "甲", 1.0),
        ("id2", "乙", 0.9),
        ("id3", "丙", 0.8),
        ("id4", "丁", 0.7),
    ]

    kept, _ = dedup(ranked, judge=judge)

    assert [item[0] for item in kept] == ["id1", "id2", "id4"]


def test_failure_does_not_merge() -> None:
    """判断失败时保守处理：不合并。"""
    judge = _judge({})  # 全部返回 unrelated
    ranked = [("id1", "甲", 1.0), ("id2", "乙", 0.9)]

    kept, _ = dedup(ranked, judge=judge)

    assert len(kept) == 2


def test_identical_text_merged_without_llm_call() -> None:
    """完全相同的文本无需模型判断。"""
    llm = _ScriptedLLM({})
    judge = EquivalenceJudge(llm=llm)
    ranked = [("id1", "同一条", 1.0), ("id2", "同一条", 0.9)]

    kept, _ = dedup(ranked, judge=judge)

    assert len(kept) == 1
    assert llm.calls == 0


def test_stats_dataclass_is_serializable() -> None:
    from dataclasses import asdict

    judge = _judge({frozenset({"甲", "乙"}): "equivalent"})
    _, stats = dedup([("id1", "甲", 1.0), ("id2", "乙", 0.9)], judge=judge)

    payload = asdict(stats)
    assert payload["before"] == 2
    assert payload["after"] == 1
