"""候选池的三种难度模式。

**为什么需要三种**：第一次评测得到 SEH@5 = 1.000，诊断后发现是任务太简单——
干扰项取自其他场景，主题与 query 毫不相干（`package_manager` vs
`dietary_restriction`），词面召回几乎无竞争。

真实检索的难度来自**同主题、相似但不能回答**的干扰项。
只报一种难度会把"跨主题命中"误读成"检索能力强"。

**数据的真实约束**：independent 集有 29 个 relation，其中 28 个只出现 1 次。
因此 `same_relation` 与 `adversarial` 模式在这批数据上样本极少。
这不是实现缺陷，是数据限制——报告必须说明，"同主题检索"需要另建数据集。
"""

from __future__ import annotations

from enum import StrEnum

from memory.store.models import MemoryItem


class PoolMode(StrEnum):
    UNRELATED = "unrelated"
    SAME_RELATION = "same_relation"
    ADVERSARIAL = "adversarial"


def select_distractors(
    gold: MemoryItem,
    candidates: list[MemoryItem],
    *,
    mode: PoolMode,
    limit: int,
) -> list[MemoryItem]:
    """按模式挑干扰项。

    - `unrelated`：任意主题（原方案，最简单）
    - `same_relation`：同 relation、不同 subject（同主题但不同对象）
    - `adversarial`：同 relation **且**与 gold 的 value 有字符重叠（最接近"相似但错了"）
    """
    if mode is PoolMode.UNRELATED:
        return candidates[:limit]

    same = [item for item in candidates if item.relation == gold.relation]
    if mode is PoolMode.SAME_RELATION:
        return same[:limit]

    gold_chars = set(gold.value)
    overlapping = [
        item for item in same if gold_chars & set(item.value)
    ]
    return overlapping[:limit]


def describe_modes() -> dict[str, str]:
    return {
        PoolMode.UNRELATED.value: "干扰项来自无关主题（低难度）",
        PoolMode.SAME_RELATION.value: "干扰项同 relation、不同 subject（中难度）",
        PoolMode.ADVERSARIAL.value: "干扰项同 relation 且与 gold 字符重叠（高难度）",
    }
