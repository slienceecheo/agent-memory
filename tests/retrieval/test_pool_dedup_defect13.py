"""缺陷 13：`build_pool` 的逻辑键不含 value，值不同的候选被判重复。

**为什么这条测试断言 `lost > 0` 而不是"`_key` 不含 value"**

`locked_defect` 的约定是**断言缺陷存在**，修好后自然变红
（见缺陷 1 的 `identical == total`、缺陷 3 的 `histogram == {"1": 26}`）。

若断言代码形状（如 `"value" not in _key(item)`），会有两个问题：

1. 修法不止一种：把 value 加进 tuple、改成按 `source_text` 判重、
   或改成"同 key 时保留值不同的所有条目"——都能修好缺陷，
   但只有第一种会让形状断言变红，测试会**惩罚正确的替代修法**
2. 更糟的是反向：按 `source_text` 判重的修法会让缺陷已修而测试仍绿，
   那时 `REPAIRED` 表里没有它、`DEFECT_TESTS` 里还有它，
   而 `test_locked_defect_manifest.py` 只查"编号有没有被覆盖"，
   不查"测试还准不准"，于是这个错误没有任何检查能发现

`lost > 0` 没有这个漏洞：不管怎么修，只要值不同的候选不再被丢弃，
`lost` 就变成 0，测试变红并给出翻面指引。
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

import pytest
from evals.run_retrieval import _item, select_pool_distractors

from memory.retrieval.pool import _key, build_pool
from memory.retrieval.pool_modes import PoolMode

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data" / "conflict-set"
SPLITS = ("dev", "test", "independent")


def _rows(name: str) -> list[dict[str, object]]:
    path = DATA / (name if name.endswith(".jsonl") else f"{name}.jsonl")
    if not path.exists():
        pytest.fail(f"数据集缺失：{path}（ROOT={ROOT}）")
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _all_gold() -> list[dict[str, object]]:
    specs: list[dict[str, object]] = []
    for split in SPLITS:
        specs.extend([r["gold"] for r in _rows(split) if r.get("gold")])  # type: ignore[misc]
    return specs


def count_value_collisions() -> tuple[int, dict[str, int], dict[str, int]]:
    """统计"因逻辑键相同而被丢弃、但 value 不同"的候选。

    返回 `(总数, 按 split, 受影响 case 数)`。
    """
    specs = _all_gold()
    total = 0
    by_split: Counter[str] = Counter()
    affected: Counter[str] = Counter()

    for split in SPLITS:
        for row in _rows(split):
            gold = row.get("gold")
            if not gold:
                continue
            picked = select_pool_distractors(
                gold, specs, mode=PoolMode.UNRELATED, limit=20
            )
            gold_item = _item(
                row, gold, tag=f"gold-{row['id']}", text=str(row.get("text") or "")
            )
            distractors = [
                _item({"text": ""}, spec, tag=f"d-{row['id']}-{i}", text=None)
                for i, spec in enumerate(picked)
            ]
            pool = build_pool(gold_item, distractors, seed=0)
            kept_tags = {entry.id for entry in pool.items}

            kept_by_key: dict[tuple[object, ...], dict[str, object]] = {}
            for entry in pool.items:
                if entry.id == gold_item.id:
                    continue
                index = int(entry.id.rsplit("-", 1)[1])
                kept_by_key[_key(distractors[index])] = picked[index]

            case_hits = 0
            for index, spec in enumerate(picked):
                if f"d-{row['id']}-{index}" in kept_tags:
                    continue
                winner = kept_by_key.get(_key(distractors[index]))
                if winner is not None and str(winner.get("value")) != str(spec.get("value")):
                    total += 1
                    by_split[split] += 1
                    case_hits += 1
            if case_hits:
                affected[split] += 1

    return total, dict(by_split), dict(affected)


@pytest.mark.locked_defect
def test_pool_dedup_drops_distinct_values() -> None:
    """缺陷 13：`_key` 不含 value，值不同的候选被判重复并丢弃。

    **断言缺陷存在**（`lost > 0`），不是断言代码形状。
    修好后 `lost` 变成 0，本测试变红——那时按下面的提示翻面。
    """
    lost, by_split, _affected = count_value_collisions()

    assert lost > 0, (
        "缺陷 13 看起来已修复（lost=0）。"
        "请把本测试翻面成正向断言（assert lost == 0）并移进 REPAIRED 表，"
        "同时更新 C4 报告缺陷 13 的状态。不要直接删掉本测试。"
    )
    assert set(by_split) == set(SPLITS), f"三个 split 都应受影响：{by_split}"


def test_most_competitive_distractor_is_dropped() -> None:
    """缺陷 13 的**最能说明问题的一例**：同 subject/relation/condition、值不同。

    `"能吃花生"` 与 `"不能吃海鲜"` 是同一关系的两个不同答案，
    本该是最难的干扰项（同时命中定位字段，只有 value 不同），
    却被 `_key` 判成重复。
    """
    specs = _all_gold()
    found = False

    for split in SPLITS:
        for row in _rows(split):
            gold = row.get("gold")
            if not gold:
                continue
            picked = select_pool_distractors(
                gold, specs, mode=PoolMode.UNRELATED, limit=20
            )
            gold_item = _item(
                row, gold, tag=f"gold-{row['id']}", text=str(row.get("text") or "")
            )
            distractors = [
                _item({"text": ""}, spec, tag=f"d-{row['id']}-{i}", text=None)
                for i, spec in enumerate(picked)
            ]
            pool = build_pool(gold_item, distractors, seed=0)
            kept_tags = {entry.id for entry in pool.items}
            kept_by_key: dict[tuple[object, ...], dict[str, object]] = {}
            for entry in pool.items:
                if entry.id == gold_item.id:
                    continue
                index = int(entry.id.rsplit("-", 1)[1])
                kept_by_key[_key(distractors[index])] = picked[index]

            for index, spec in enumerate(picked):
                if f"d-{row['id']}-{index}" in kept_tags:
                    continue
                winner = kept_by_key.get(_key(distractors[index]))
                if winner is None or str(winner.get("value")) == str(spec.get("value")):
                    continue
                if _key(distractors[index])[:4] == _key(
                    _item({"text": ""}, gold, tag="x", text=None)
                )[:4]:
                    found = True
                    break
            if found:
                break
        if found:
            break

    assert found, (
        "没有找到'同时命中 subject/relation/condition 但值不同、且被丢弃'的候选。"
        "若数据集变了，本条的前提失效，请更新说明而不是删掉。"
    )


# ---------- 数据指纹（数据换代时更新数字，不是修代码） ----------


def test_data_fingerprint_value_collisions() -> None:
    """当前数据集上"值不同被丢弃"的规模。

    **这是数据指纹，不是行为契约。** 数据换代（如 v2 替代 conflict-set）时，
    处理动作是"更新数字 + 更新报告对应段落"，不是修代码。

    锁两个数而不是一个：只锁 147 不够——若数据只保留 dev，总数会掉到 61，
    但"每条 case 都受影响"这个结构性事实不变。第二个断言锁的正是那个比例。

    测试名以 `test_data_fingerprint_` 开头，使"数据换代"与"代码回归"
    两种红在名字上就可区分。
    """
    lost, by_split, affected = count_value_collisions()

    assert lost == 147
    assert by_split == {"dev": 61, "test": 34, "independent": 52}
    assert affected == {"dev": 33, "test": 17, "independent": 26}


def test_data_fingerprint_collisions_span_whole_split() -> None:
    """受影响的 case 数等于该 split 的全部有 gold case。

    "每条 case 都至少丢了一条值不同的候选"——这是结构性的，
    不随数据量变化。
    """
    _lost, _by_split, affected = count_value_collisions()

    for split in SPLITS:
        total_with_gold = sum(1 for r in _rows(split) if r.get("gold"))
        assert affected[split] == total_with_gold, (
            f"{split}: {affected[split]}/{total_with_gold} 条 case 受影响，"
            "不再全部受影响说明数据或去重规则变了"
        )
