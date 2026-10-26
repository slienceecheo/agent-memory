"""统计候选池成员的来源 split。

**为什么需要这个模块**：C4 归档里 test 与 independent 的池成员来自哪里，
此前没有任何记录。实测发现它们几乎全部来自 dev，这使两个 split 的
数字都失去独立性（缺陷 9）。

**为什么必须按对象身份（`is`）匹配，不能用键值匹配**：

本仓库有 8 个重复的逻辑键，例如

    ('project:agent-memory', 'package_manager', 'None', 'pnpm')
        -> dev 出现 6 次，test 出现 2 次

按键值匹配会把同一个键的所有来源都算上，实测后果：

    split         identity            key（错误）
    dev           {'dev': 660}         {'dev': 1816, 'test': 528}
    test          {'dev': 340}         {'dev': 898,  'test': 252}

dev 的条目数会虚增 2.75 倍，并凭空出现 528 条 "test"。
因此调用方必须传入 `select_pool_distractors` 实际返回的那些对象，
不能传入重新构造的副本——本模块依赖"返回的就是 all_specs 里的对象"这一契约
（实测 identity 命中 20/20）。

**两个层级的分母不同，引用数字时必须写明**：

| 层级 | 含义 | dev | test | independent |
|---|---|---|---|---|
| `selection` | `select_pool_distractors` 返回的干扰项次数 | 660 | 340 | 520 |
| `pool` | `build_pool` 去重后仍在池中的**干扰项** | 429 | 231 | 364 |

`pool` 层的数不含 gold。若把 gold 也算进去，test 池是 248（231 dev + 17 test），
independent 池是 390（364 dev + 26 independent）——即"除 gold 外全是 dev"。
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence
from typing import Any


def count_origins(
    selected: Sequence[Mapping[str, Any]],
    all_specs: Sequence[Mapping[str, Any]],
    origins: Sequence[str],
) -> Counter[str]:
    """按对象身份统计一批池候选来自哪些 split。

    参数：
        selected: 被选中的候选对象。**必须是 `select_pool_distractors`
            或 `build_pool` 实际持有过的对象**，不能是重新构造的副本，
            否则身份匹配会全部落空。
        all_specs: 候选全集，与 `selected` 中的对象共享身份。
        origins: 与 `all_specs` 等长的来源标签（如 split 名）。

    返回：
        `{来源: 计数}`。身份匹配不到的条目记为 `"unknown"`。
    """
    if len(all_specs) != len(origins):
        raise ValueError(
            f"all_specs 与 origins 长度不一致（{len(all_specs)} vs {len(origins)}）"
        )

    origin_by_identity = {id(spec): origin for spec, origin in zip(all_specs, origins, strict=True)}
    counts: Counter[str] = Counter()
    for item in selected:
        counts[origin_by_identity.get(id(item), "unknown")] += 1
    return counts


def selection_origins(
    rows: Sequence[Mapping[str, Any]],
    all_specs: Sequence[Mapping[str, Any]],
    origins: Sequence[str],
    *,
    select_fn: Any,
    limit: int = 20,
) -> Counter[str]:
    """`selection` 层：统计所有 case 选出的干扰项次数。"""
    counts: Counter[str] = Counter()
    for row in rows:
        gold = row.get("gold")
        if not gold:
            continue
        picked = select_fn(gold, all_specs, limit=limit)
        counts.update(count_origins(picked, all_specs, origins))
    return counts


def pool_origins(
    rows: Sequence[Mapping[str, Any]],
    all_specs: Sequence[Mapping[str, Any]],
    origins: Sequence[str],
    *,
    select_fn: Any,
    build_fn: Any,
    item_fn: Any,
    limit: int = 20,
) -> Counter[str]:
    """`pool` 层：统计 `build_pool` 去重后**仍在池中的干扰项**来源。

    **不含 gold**。gold 来自本 split，把它算进来会让数字看起来"没那么糟"：
    test 池 248 条里 17 条是 gold 自己，只有 231 条是干扰项。
    """
    counts: Counter[str] = Counter()
    for row in rows:
        gold = row.get("gold")
        if not gold:
            continue
        picked = select_fn(gold, all_specs, limit=limit)
        gold_item = item_fn(row, gold, tag=f"gold-{row['id']}", text=str(row.get("text") or ""))
        distractors = [
            item_fn({"text": ""}, spec, tag=f"d-{row['id']}-{i}", text=None)
            for i, spec in enumerate(picked)
        ]
        pool = build_fn(gold_item, distractors, seed=0)

        for entry in pool.items:
            if entry.id == gold_item.id:
                continue
            index = int(entry.id.rsplit("-", 1)[1])
            counts.update(count_origins([picked[index]], all_specs, origins))
    return counts


__all__ = ["count_origins", "pool_origins", "selection_origins"]
