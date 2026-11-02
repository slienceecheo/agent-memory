"""轴由池结构派生（tasks 2.1–2.4）。

**这是 TDD 的失败测试**：`derive_axis` / `derive_axis_policy` 尚不存在。

判据（design D2）：

    n_competitors(query) = |{m in pool : relation(m) == relation(gold)}|
    axis(query) = "relation_within" if n_competitors > 0 else "relation_cross"

    对每个 subject，取 A 轴查询与 C 轴查询的 n_competitors **取值集合**；
    `set(A) == set(C)` -> 该 subject 合并为一轴；否则保留两轴。

    **空轴单独处置**：两轴都为空（`set() == set()`）判 `two_axes`，
    因为"两轴都为空"与"两轴同构"是两件不同的事——
    `merged` 的语义是"合并为一轴"，不是"没有轴"。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data" / "retrieval-v2"


def _load(subject: str):
    mems = {
        m["memory_id"]: m
        for m in (
            json.loads(x)
            for x in (DATA / subject / "memories.jsonl")
            .read_text(encoding="utf-8")
            .splitlines()
            if x.strip()
        )
    }
    qs = [
        json.loads(x)
        for x in (DATA / subject / "queries.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
        if x.strip()
    ]
    return mems, qs


def test_derive_axis_returns_within_when_competitors_exist() -> None:
    """池中有同 relation 候选 -> `relation_within`。"""
    from evals.run_retrieval import derive_axis

    mems = {
        "g": {"memory_id": "g", "relation": "r1"},
        "a": {"memory_id": "a", "relation": "r1"},
        "b": {"memory_id": "b", "relation": "r2"},
    }

    assert derive_axis(pool=mems.values(), gold=mems["g"]) == "relation_within"


def test_derive_axis_returns_cross_when_no_competitor() -> None:
    """池中无同 relation 候选 -> `relation_cross`。"""
    from evals.run_retrieval import derive_axis

    mems = {
        "g": {"memory_id": "g", "relation": "r1"},
        "b": {"memory_id": "b", "relation": "r2"},
    }

    assert derive_axis(pool=mems.values(), gold=mems["g"]) == "relation_cross"


def test_derive_axis_excludes_gold_itself() -> None:
    """gold 自己不算竞争者——否则永远 within。"""
    from evals.run_retrieval import derive_axis

    mems = {"g": {"memory_id": "g", "relation": "r1"}}

    assert derive_axis(pool=mems.values(), gold=mems["g"]) == "relation_cross"


def test_derive_axis_requires_memory_id_to_identify_gold() -> None:
    """**缺少 `memory_id` 时必须报错，不能静默退化。**

    实测 bug：用 `getattr(x, "memory_id", None) or x.get("memory_id")` 取值，
    当 dict 缺该键时两条都返回 `None`，于是 `mid == gold_id` 恒真
    （`None == None`），每个候选都被跳过，`within` 恒返回 `cross`——
    **一个"0 竞争者"的假象。**

    所以正确行为是抛错，而不是返回一个看似合法的 axis。
    """
    from evals.run_retrieval import derive_axis

    with_ids = {
        "g": {"memory_id": "g", "relation": "r1"},
        "a": {"memory_id": "a", "relation": "r1"},
    }
    assert derive_axis(pool=with_ids.values(), gold=with_ids["g"]) == "relation_within"

    # 都不带 memory_id -> 无法识别 gold -> 必须报错
    without_ids = {
        "g": {"relation": "r1"},
        "a": {"relation": "r1"},
    }
    with pytest.raises(ValueError, match="memory_id"):
        derive_axis(pool=without_ids.values(), gold=without_ids["g"])


@pytest.mark.parametrize(
    ("cases", "expected", "why"),
    [
        # 真实数据
        ({"A": [3, 3, 3, 3, 2, 2, 2, 2, 2, 2], "C": [0, 0]}, "two_axes", "ledger 事实"),
        ({"A": [2] * 9, "C": [2, 2, 2]}, "merged", "billing 事实"),
        # **样本量不同但结构相同** -> merged（中位数与集合都给 merged，
        #   而有序列表会错判 two_axes）
        ({"A": [2] * 9, "C": [2] * 3}, "merged", "忽略样本量"),
        # **难度不同但都是 within** -> two_axes（集合抓到，标签集合抓不到）
        ({"A": [1, 1, 1], "C": [7, 7, 7]}, "two_axes", "深度不同"),
        # **尾部不同但中位数相同** -> two_axes（集合抓到，中位数抓不到）
        ({"A": [1, 1, 1, 1, 9], "C": [1, 1, 1, 1, 1]}, "two_axes", "尾部不同"),
        # 反例：形状同 ledger 但用假数据
        ({"A": [2, 2, 2], "C": [0, 0, 0]}, "two_axes", "假数据"),
        # 单元素同值
        ({"A": [2], "C": [2]}, "merged", "单元素相同"),
    ],
)
def test_derive_axis_policy(
    cases: dict[str, list[int]], expected: str, why: str
) -> None:
    """`derive_axis_policy` 用取值集合比较，不看 subject 名字、不看样本量。

    **每一条都对应一种判据错误的防线**：

    | 用例 | 抓的错误 |
    |---|---|
    | `[2]×9` vs `[2]×3` | 有序列表混入样本量 |
    | `{1}` vs `{7}` | 标签集合太粗 |
    | `[1,1,1,1,9]` vs `[1,1,1,1,1]` | 中位数漏掉尾部 |
    | `[2,2,2]` vs `[0,0,0]` | 按 subject 名字特判 |
    """
    from evals.run_retrieval import derive_axis_policy

    assert derive_axis_policy(cases) == expected, f"用例：{why}"


def test_derive_axis_policy_rejects_two_empty_axes() -> None:
    """**空轴不能判 `merged`。**

    `set([]) == set([])` 为真，所以朴素的集合比较会把"没有轴"说成"合并为一轴"。
    而这两件事语义不同：

    | 情形 | 含义 | 正确判定 |
    |---|---|---|
    | `A=[2,2]`、`C=[2,2]` | 两轴都有查询、结构相同 | `merged` |
    | `A=[]`、`C=[]` | 两轴都没有查询 | `no_axis`（不可判定） |
    | `A=[2,2]`、`C=[]` | 只有一轴有查询 | `single_axis` |

    **`single_axis` 不是多余的值**：proposal 的"路 2"允许 subject 没有
    cross 轴（`billing` 三个 relation 全多分支，永远产生不了 cross 查询）。
    那时 C 列表为空是**正常数据形状**，不是缺陷——而它既不是 `merged`
    （没有第二轴可合并），也不是 `two_axes`（没有两个轴）。
    """
    from evals.run_retrieval import derive_axis_policy

    assert derive_axis_policy({"A": [2, 2], "C": []}) == "single_axis"
    assert derive_axis_policy({"A": [], "C": [2, 2]}) == "single_axis"
    assert derive_axis_policy({"A": [], "C": []}) == "no_axis"
    assert derive_axis_policy({}) == "no_axis"


def test_derive_axis_policy_three_values_are_distinct() -> None:
    """三值互不相等，且只有 `merged` 表示"两轴同构"。

    **这条防的是退化**：若实现里 `single_axis` 直接返回 `merged`，
    报告会把"只有一轴"写成"两轴合并"，而两者要报的轴数相同（都是 1），
    数字上看不出差别——**这正是"数字相同所以看不出错"的形态。**
    """
    from evals.run_retrieval import derive_axis_policy

    merged = derive_axis_policy({"A": [2, 2], "C": [2, 2]})
    single = derive_axis_policy({"A": [2, 2], "C": []})
    none = derive_axis_policy({"A": [], "C": []})

    assert merged == "merged"
    assert {merged, single, none} == {"merged", "single_axis", "no_axis"}


def test_ledger_and_billing_facts() -> None:
    """记录 v2 的实测事实（tasks 2.3 的 (a) 部分）。

    - `ledger`：`set(A)={2,3}`、`set(C)={0}` -> two_axes
    - `billing`：`set(A)={2}`、`set(C)={2}` -> merged

    **而 `billing` 的 3 条 C 标注查询，池结构上都是 `relation_within`**——
    v2 的 `axis` 标注在那 3 条上是错的（3/12）。
    """
    from evals.run_retrieval import derive_axis, derive_axis_policy

    for subject, expected_policy in (("sample", "two_axes"), ("billing", "merged")):
        mems, qs = _load(subject)
        by_axis: dict[str, list[int]] = {"A": [], "C": []}
        for q in qs:
            g = mems[q["gold_memory_id"]]
            pool = [m for k, m in mems.items() if k != q["gold_memory_id"]]
            n = sum(1 for m in pool if m.get("relation") == g.get("relation"))
            by_axis[str(q.get("axis"))].append(n)

        assert derive_axis_policy(by_axis) == expected_policy, subject

    # 标注与派生的一致性：ledger 0/12 不一致，billing 3/12
    for subject, expected_mismatch in (("sample", 0), ("billing", 3)):
        mems, qs = _load(subject)
        mism = 0
        for q in qs:
            g = mems[q["gold_memory_id"]]
            pool = [m for k, m in mems.items() if k != q["gold_memory_id"]]
            derived = derive_axis(pool=pool, gold=g)
            labeled = (
                "relation_within" if q.get("axis") == "A" else "relation_cross"
            )
            if derived != labeled:
                mism += 1
        assert mism == expected_mismatch, f"{subject}: 标注不一致 {mism} 条"
