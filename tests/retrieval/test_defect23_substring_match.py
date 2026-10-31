"""缺陷 23：`parse_condition` 用子串匹配，短别名命中长词，产生假槽位。

**缺陷定义**：`_ALIASES` 的匹配是 `if alias.casefold() in folded`——子串包含。

**它不是"坏了"这么简单：它同时产生两种后果，性质不同。**

| 类型 | 判据 | 例子 | 是否错 |
|---|---|---|---|
| **误命中** | 两个命中区间**重叠**（长词包含短别名） | `day` ⊂ `holiday` | **一定是错的** |
| **多命中** | 两个命中区间**不重叠** | `本地`+`开发` 在 `本地开发` 里 | **可能都对** |

实测：`本地开发` 得到 `{activity:coding, env:local}`，**语义上是对的**。
所以"子串匹配的 3 对碰撞"里，只有 **1 对是误命中**、**1 对是多命中**、**1 对其实正确**。

**为什么这是行为缺陷而不是死代码**：
`condition_match` 在 `src/memory/retrieval/rerank.py:111` 与
`evals/run_retrieval.py:571` 都是生产路径。

**为什么现在不修**：三种修法对两类问题的处理**不同**。

| 方案 | 修误命中 | 保留多命中 | 代价 |
|---|---|---|---|
| 甲 词边界 | 只修英文 | ✅ | 中文无边界，全词表只改 1 键 |
| 乙 最长优先 | ✅ | ✅ | 改 3 键；需引入区间占位状态 |
| 丙 精确匹配 | ✅ | ❌ 杀掉 | 数据集 3 个**语义正确**的值退化 |

这些测试**锁定现状**，不是认可它。修好后它们会红，届时翻面为正向断言。
"""

from __future__ import annotations

import pytest

from memory.retrieval.condition import _ALIASES, condition_match, parse_condition


def _hit_intervals(text: str) -> list[tuple[str, str, int, int]]:
    """返回 (别名, 槽位, 起, 止)。用于判断命中是否重叠。"""
    folded = text.casefold()
    out = []
    for alias, slot in _ALIASES.items():
        start = folded.find(alias.casefold())
        if start != -1:
            out.append((alias, slot, start, start + len(alias)))
    return out


@pytest.mark.locked_defect
def test_defect23_true_positive_hits_are_real() -> None:
    """误命中：长词包含短别名，两个命中区间重叠。

    这三对才是"错的"。若匹配算法改了，这里会红。
    """
    assert parse_condition("holiday").slots == frozenset(
        {"time:day", "time:holiday"}
    ), "holiday 不再多给 time:day，误命中可能已修"

    assert parse_condition("开发环境").slots == frozenset(
        {"activity:coding", "env:development"}
    ), "开发环境 不再多给 activity:coding，误命中可能已修"

    assert parse_condition("功能开发").slots == frozenset(
        {"activity:coding", "activity:feature"}
    ), "功能开发 不再多给 activity:coding，误命中可能已修"


@pytest.mark.plan_check
def test_defect23_hits_are_overlapping_substrings() -> None:
    """判据本身：三对误命中的区间确实重叠（包含）。

    **依赖词表而非算法**：判定用测试内的 `_hit_intervals()`，它只读 `_ALIASES`。
    所以：

    | 改动 | 这条会红吗 |
    |---|---|
    | 改匹配算法（甲/乙/丙） | ❌ 不会 |
    | 改词表（增删别名） | ✅ 会 |
    | 换数据集 | ❌ 不会 |

    它不是"锁缺陷"——修缺陷 23 时它不会红。它记录的是**当前词表上的区间结构**。
    """
    for text in ("holiday", "开发环境", "功能开发"):
        intervals = _hit_intervals(text)
        assert len(intervals) == 2, f"{text} 的命中数变成 {len(intervals)}"
        (_, _, s1, e1), (_, _, s2, e2) = intervals
        overlaps = s1 < e2 and s2 < e1
        assert overlaps, f"{text} 的命中区间不再重叠：{intervals}"


@pytest.mark.locked_defect
def test_defect23_multi_hits_are_not_overlapping_and_are_correct() -> None:
    """多命中：`本地开发` 的 `本地` 与 `开发` 区间不相交，且结果语义正确。

    **这一类不该被修掉。** 列在这里是为了防止"修误命中"时顺手把正确行为也删了。
    """
    intervals = _hit_intervals("本地开发")
    assert len(intervals) == 2, f"命中数变成 {len(intervals)}"

    (_, _, s1, e1), (_, _, s2, e2) = sorted(intervals, key=lambda i: i[2])
    assert not (s1 < e2 and s2 < e1), "本地/开发 的区间重叠了，分类需要重写"

    assert parse_condition("本地开发").slots == frozenset(
        {"activity:coding", "env:local"}
    )


@pytest.mark.locked_defect
def test_defect23_produces_a_false_positive_similarity() -> None:
    """语义无关的两个条件，因为共享误命中槽位而得到 0.5。

    0.5 在本模块的口径里表示"一方没提条件"，而这里两边都提了。
    **这个 0.5 是巧合，不是设计。**
    """
    assert condition_match("开发环境", "写代码") == pytest.approx(0.5)
    assert condition_match("功能开发", "写代码") == pytest.approx(0.5)


@pytest.mark.locked_defect
def test_defect23_chinese_english_pair_is_not_equal() -> None:
    """`holiday` 与 `节假日` 这对"中英对照"实际不相等。

    而 `tests/retrieval/test_condition.py` 的 parametrize 用的是
    `assert expected_slot in parsed.slots`（子集断言），所以多出来的槽位看不见。
    """
    en = parse_condition("holiday").slots
    zh = parse_condition("节假日").slots

    assert en != zh
    assert en - zh == frozenset({"time:day"})


@pytest.mark.locked_defect
def test_defect23_dataset_values_split_into_three_groups() -> None:
    """41 个数据集条件值：26 精确键 / 3 靠子串 / 12 本来就 raw。

    **组 C 不该算进"被打断"**——它们在两种方案下都是 raw。
    """
    import json
    from pathlib import Path

    root = Path(__file__).resolve().parents[2]
    values: set[str] = set()
    for path in (root / "data").rglob("*.jsonl"):
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            v = row.get("condition")
            if isinstance(v, str) and v.strip():
                values.add(v.strip())
            gold = row.get("gold")
            if isinstance(gold, dict):
                gv = gold.get("condition")
                if isinstance(gv, str) and gv.strip():
                    values.add(gv.strip())

    folded = {a.casefold() for a in _ALIASES}
    group_a = [v for v in values if v.casefold() in folded]
    group_b = [
        v for v in values if v.casefold() not in folded and parse_condition(v).structured
    ]
    group_c = [
        v
        for v in values
        if v.casefold() not in folded and not parse_condition(v).structured
    ]

    assert len(values) == 41, f"数据集条件值变成 {len(values)}"
    assert len(group_a) == 26, f"精确键变成 {len(group_a)}"
    assert len(group_b) == 3, f"靠子串命中的值变成 {len(group_b)}：{group_b}"
    assert len(group_c) == 12, f"本来就 raw 的值变成 {len(group_c)}"


@pytest.mark.plan_check
def test_defect23_datasets_group_b_and_collisions_are_disjoint() -> None:
    """**关键区分**：3 对碰撞全是误命中；组 B 的 3 个值全是多命中或正确。

    这两组是不同的问题：

    - 碰撞（`holiday`/`开发环境`/`功能开发`）在**词表键**上，都该修
    - 组 B（`工作日白天`/`本地开发`/`生产环境`）在**数据集值**上，都不该修

    **依赖词表而非算法**：只用测试内的 `_hit_intervals()` 读 `_ALIASES`。
    改匹配算法不会让这条变红；改词表才会。
    """
    collisions = [
        (short, long)
        for short in _ALIASES
        for long in _ALIASES
        if short != long
        and short.casefold() in long.casefold()
        and _ALIASES[short] != _ALIASES[long]
    ]
    assert len(collisions) == 3

    # 每组误命中都是"长词包含短别名"的重叠结构
    for text in ("holiday", "开发环境", "功能开发"):
        intervals = _hit_intervals(text)
        assert len(intervals) == 2
        (_, _, s1, e1), (_, _, s2, e2) = intervals
        assert s1 < e2 and s2 < e1, f"{text} 不是重叠结构"

    # 组 B 的三个值都不含任何重叠命中
    for text in ("工作日白天", "本地开发", "生产环境"):
        intervals = _hit_intervals(text)
        for i, (_, _, s1, e1) in enumerate(intervals):
            for _, _, s2, e2 in intervals[i + 1 :]:
                assert not (s1 < e2 and s2 < e1), f"{text} 出现了重叠命中"


@pytest.mark.plan_check
def test_defect23_longest_match_fixes_all_collisions_and_keeps_group_b() -> None:
    """乙方案：修掉全部误命中，同时组 B 三个值**一个都不变**。

    这是"乙看起来最好"的实测依据。

    **为什么标 `plan_check` 而不是 `locked_defect`**：它用的是测试内的
    `longest()`，不调用产品的匹配逻辑。`parse_condition` 只作为**比较基准**
    出现在最后一段，而那三个值无论修不修都不变——所以：

    | 改动 | 这条会红吗 |
    |---|---|
    | 修缺陷 23（实现乙） | ❌ 不会（组 B 不变；三对误命中的断言用的是本地实现） |
    | 改词表 | ✅ 会 |
    | 换数据集 | ❌ 不会 |

    它测的是"如果实现乙，会得到什么结果"，不是"现状有问题"。
    """
    folded_table = {a.casefold(): slot for a, slot in _ALIASES.items()}

    def longest(text: str) -> frozenset[str]:
        hits = sorted(_hit_intervals(text), key=lambda h: (-(h[3] - h[2]), h[2]))
        taken: list[tuple[int, int]] = []
        slots: set[str] = set()
        for _alias, slot, start, end in hits:
            if any(start < e and s < end for s, e in taken):
                continue
            taken.append((start, end))
            slots.add(slot)
        return frozenset(slots) or frozenset({f"raw:{text}"})

    assert folded_table  # 词表非空

    # 修掉 3 对误命中
    assert longest("holiday") == frozenset({"time:holiday"})
    assert longest("开发环境") == frozenset({"env:development"})
    assert longest("功能开发") == frozenset({"activity:feature"})

    # 组 B 的三个值与现状完全相同
    for text in ("工作日白天", "本地开发", "生产环境"):
        assert longest(text) == parse_condition(text).slots, f"{text} 在乙下改变了"


@pytest.mark.locked_defect
def test_defect23_spec_example_does_not_match() -> None:
    """spec 举的例子 `应酬 / client dinner` 实测 0.000。

    `client_dinner`（下划线）才是 1.000。
    **修 spec 例子会让这条 scenario 从失败变通过，而实现没变**——
    所以必须与缺陷 23 同时处置，否则只是降低了标准。
    """
    assert condition_match("应酬", "client dinner") == pytest.approx(0.0)
    assert condition_match("应酬", "client_dinner") == pytest.approx(1.0)

    assert "client dinner" not in _ALIASES
    assert "client_dinner" in _ALIASES


@pytest.mark.locked_defect
def test_defect23_exact_matching_would_break_three_values() -> None:
    """丙方案（精确匹配）的代价：3 个**语义正确**的值退化为 `raw`。

    这条锁定的是"为什么不能简单改成精确匹配"——它是设计决策的证据。
    而这 3 个值当前解析出的槽位都是对的，不是错的。
    """
    folded = {a.casefold() for a in _ALIASES}
    affected = [
        v
        for v in ("工作日白天", "本地开发", "生产环境")
        if v.casefold() not in folded and parse_condition(v).structured
    ]

    assert affected == ["工作日白天", "本地开发", "生产环境"]

    # 它们当前的结果不是"错的多余槽位"，而是各自语义正确的槽位
    assert parse_condition("工作日白天").slots == frozenset({"time:day"})
    assert parse_condition("本地开发").slots == frozenset(
        {"activity:coding", "env:local"}
    )
    assert parse_condition("生产环境").slots == frozenset({"env:production"})
