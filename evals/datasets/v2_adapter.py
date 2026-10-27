"""v2 数据集 → 现有评测入口的行格式适配。

**为什么必须有**：`run_retrieval --dataset` 期望一个 `.jsonl` 文件，字段是
`id` / `query` / `text` / `gold` / `candidate_value`。而 v2 是一个目录
（`memories.jsonl` + `queries.jsonl`），字段完全不同
（`axis` / `cue_type` / `gold_memory_id`）。

实测后果：`--dataset data/retrieval-v2/sample` 报
`PermissionError: [Errno 13] Permission denied`——它试图把目录当文件读。

**硬约束：只做字段映射，不做池构造。**

池构造必须继续走 `build_pool` / `select_pool_distractors`，
否则 v2 会变成第二套池逻辑，A3 的数字就与 C4 不可比。

这条约束写成测试：适配层输出必须能直接喂给 `evaluate_case()`，
不接受任何额外参数。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from evals.datasets.retrieval_v2 import Dataset, Memory, load_dataset


@dataclass(frozen=True, slots=True)
class AdaptedCase:
    """适配后的单条评测行，字段与 `run_retrieval` 的期望一致。"""

    id: str
    query: str
    text: str
    gold: dict[str, Any] | None
    subject: str
    relation: str
    candidate_value: str
    condition: str | None

    def as_row(self) -> dict[str, Any]:
        """转成 `evaluate` 能直接消费的 dict。"""
        return {
            "id": self.id,
            "query": self.query,
            "text": self.text,
            "gold": self.gold,
            "subject": self.subject,
            "relation": self.relation,
            "candidate_value": self.candidate_value,
            "condition": self.condition,
        }


def _gold_spec(memory: Memory) -> dict[str, Any]:
    """把一条 v2 记忆映射成 `run_retrieval` 期望的 gold spec。

    **带上 `memory_text`**，使干扰项也能拿到自己的原文。

    这是修缺陷 2 在 v2 上的复发：`run_retrieval` 构造干扰项时写死
    `text=None`，而 v2 的每条记忆都有 `memory_text`。丢掉它之后，
    FTS 索引里只剩 `subject + relation + value`，共享情境词进不去，
    查询只能用分支的 value 或单字命中——两者都不是"同主题竞争"。

    C4 的 gold spec 天然没有这个字段，所以行为自动分化，不需要开关。
    """
    return {
        "subject": memory.subject,
        "relation": memory.relation,
        "value": memory.value,
        "condition": memory.condition,
        "authority": memory.authority.value,
        "memory_text": memory.memory_text,
    }


def adapt(dataset: Dataset) -> list[AdaptedCase]:
    """把 v2 数据集映射成评测入口的行列表。

    **只做字段映射。** 不构造池、不选干扰项、不计算任何指标。

    映射规则：

    | v2 字段 | 行字段 | 说明 |
    |---|---|---|
    | `query.query` | `query` | 自然提问，原样保留 |
    | `query.gold_memory_id` | `gold` | 查记忆库得到 spec |
    | `gold.memory_text` | `text` | 记忆的源话语 |
    | `query.query_condition` | `condition` | 查询携带的条件 |

    `gold` 为 ADD 类场景（无既有记忆）时留空——
    v2 的 schema 要求 `gold_memory_id` 必填，所以当前不会有这种行。
    """
    cases: list[AdaptedCase] = []
    for query in dataset.queries:
        gold_memory = dataset.memory(query.gold_memory_id)
        cases.append(
            AdaptedCase(
                id=query.query_id,
                query=query.query,
                # 注意：这里故意**不用** gold 的 memory_text 作为 `text`。
                # `text` 在 C4 里既是「gold 的索引原文」又是「demo 的源话语」，
                # 而 v2 的 memory_text 不等于 query（L1 保证），所以可以直接用。
                text=gold_memory.memory_text,
                gold=_gold_spec(gold_memory),
                subject=query.subject,
                relation=gold_memory.relation,
                candidate_value=gold_memory.value,
                condition=query.query_condition,
            )
        )
    return cases


def rows(dataset: Dataset) -> list[dict[str, Any]]:
    """适配后直接可喂 `evaluate` 的行列表。"""
    return [case.as_row() for case in adapt(dataset)]


def load_rows(directory: Path | str) -> list[dict[str, Any]]:
    """一步到位：从 v2 目录加载并适配。"""
    return rows(load_dataset(directory))


__all__ = ["AdaptedCase", "adapt", "load_rows", "rows"]
