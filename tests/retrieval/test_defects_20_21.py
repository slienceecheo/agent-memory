"""缺陷 20 与 21：v2 上的两条可修复违规。

**为什么它们必须进 `locked_defect`**（判据：问"怎样才能变绿"）：

| 候选 | 修法 | 修好后 |
|---|---|---|
| 20 条件直通 | adapter 不传 `query_condition`，或造数据不填副本 | 断言"等于副本"变红 |
| 21 authority 临界点 | 调权重，或要求降级必须有场景依据 | 断言"两者相等"变红 |

**对照（不该进）**：

- "词面在 A 轴无增量"：修法只能是改数据让它有增量——那不是修缺陷，是换实验
- "22/22 四特征模型"：模型解释力，没有"修好"状态

这两条区别很重要：前者是**代码/数据契约违反了应有性质**，
后者是**我们测到了什么**。混在一起会让清单混入永远无法结案的条目。

---

缺陷 20 与缺陷 1 的关系：**同一个错误在另一个字段上的复发。**

| | C4 缺陷 1 | v2 缺陷 20 |
|---|---|---|
| 字段 | `query` | `query_condition` |
| 写法 | `query = row["text"]` | `query_condition = gold.condition` |
| 后果 | 词面必然命中 | `condition_match` 必然 1.00 |
"""

from __future__ import annotations

import pytest
from evals.datasets.retrieval_v2 import Axis, Dataset, load_dataset

from memory.retrieval.rerank import _AUTHORITY_SCORE
from memory.store.models import Authority


@pytest.mark.locked_defect
def test_query_condition_is_a_verbatim_copy_of_gold(
    dataset: Dataset,
) -> None:
    """缺陷 20：每条 A 轴查询的 `query_condition` 都是 `gold.condition` 的副本。

    这让 `condition_match` 对 gold 恒为 1.00、对兄弟恒为 0.00——
    系统不需要推断条件，只需要字符串相等。

    **修复后这条会红**：修法是 adapter 不传该字段，或造数据不填副本。
    届时应翻面成"条件必须从文本推断"的正向断言。
    """
    a_queries = [q for q in dataset.queries if q.axis is Axis.A]
    assert a_queries, "没有 A 轴查询"

    copies = [
        q.query_id
        for q in a_queries
        if q.query_condition == dataset.memory(q.gold_memory_id).condition
    ]

    assert len(copies) == len(a_queries), (
        f"只有 {len(copies)}/{len(a_queries)} 条是副本——"
        "缺陷 20 可能已修复，请翻面成正向断言并更新清单"
    )


@pytest.mark.locked_defect
def test_condition_match_degenerates_to_string_equality(
    dataset: Dataset,
) -> None:
    """缺陷 20 的后果：兄弟分支的 `condition_match` 恒为 0.00。

    这是"不同条件值之间没有任何语义桥接"的直接证据：
    19 个值两两相比，只有 1.00（相同）与 0.00（不同）两个取值。
    """
    from memory.retrieval.condition import condition_match

    a_queries = [q for q in dataset.queries if q.axis is Axis.A]
    scores: set[float] = set()
    for q in a_queries:
        gold = dataset.memory(q.gold_memory_id)
        for m in dataset.memories:
            if m.memory_id == gold.memory_id:
                continue
            if m.subject != gold.subject or m.relation != gold.relation:
                continue
            scores.add(condition_match(q.query_condition, m.condition))

    assert scores == {0.0}, (
        f"兄弟的 condition_match 出现非 0 值 {scores}——"
        "缺陷 20 可能已修复"
    )


@pytest.mark.locked_defect
def test_authority_penalty_equals_condition_bonus() -> None:
    """缺陷 21 的**前提在 v3 已消失**，但观察保留。

    v2 的等式是：

        penalty = w.authority  × (1.0 − _AUTHORITY_SCORE[THIRD_PARTY])
        bonus   = w.condition  × 1.0

    两式在 `uniform`（各 0.25）下相等，所以一条 `third_party` 的 gold
    会失去全部条件优势，胜负完全由 base 决定。

    **v3 之后 `condition` 没有权重，"加成"这个概念不存在**——
    所以原等式**不能成立也不该成立**。这不是"修好了缺陷 21"，
    是"这个比较本身失去了对象"。

    **保留下来的观察**：`third_party` 的 authority 罚分是否还会
    压倒 base 优势。若会，那缺陷 19 的机制在 v3 仍在（事实如此，见
    `test_q4_loses_to_unrelated_entries_on_authority`）。

    **`w` 必须从 `PREREGISTERED_WEIGHTS` 读，不能抄常量。**
    """
    from memory.retrieval.rerank import PREREGISTERED_WEIGHTS, FeatureScores, rerank

    w = PREREGISTERED_WEIGHTS["uniform"]

    # condition 不再是权重字段——这正是本条要锁的事实
    assert not hasattr(w, "condition"), (
        "`RerankWeights` 又有 condition 字段了——v3 的 BREAKING 被回退"
    )

    # 原等式无定义：把 condition 从 0 改到 1，得分不变
    class _C:
        def __init__(self, f: FeatureScores) -> None:
            self.item_id = "x"
            self.features = f

    lo = FeatureScores(base=0.5, condition=0.0, authority=1.0, status=1.0)
    hi = FeatureScores(base=0.5, condition=1.0, authority=1.0, status=1.0)
    assert rerank([_C(lo)], weights=w)[0].score == pytest.approx(
        rerank([_C(hi)], weights=w)[0].score
    ), "condition 又影响了得分"

    # 保留观察：third_party 罚分仍压倒 base 优势
    penalty = (1.0 - _AUTHORITY_SCORE[Authority.THIRD_PARTY]) * w.authority
    base_advantage = w.base * (1.0 - 0.910)
    assert penalty > base_advantage, (
        f"罚分 {penalty} 不再压倒 base 优势 {base_advantage}——"
        "缺陷 19 的机制可能已变，需重估"
    )


@pytest.mark.locked_defect
def test_only_one_case_triggers_the_authority_critical_point(
    dataset: Dataset,
) -> None:
    """缺陷 21 的触发面：A 轴上只有 1 条 `third_party` gold。

    **这是"算术精确、经验 n=1"的来源。** 若将来有更多 `third_party`，
    这条会红，届时"n=1"的限定要更新。
    """
    third_party = [
        q.query_id
        for q in dataset.queries
        if q.axis is Axis.A
        and dataset.memory(q.gold_memory_id).authority is Authority.THIRD_PARTY
    ]

    assert len(third_party) == 1, (
        f"`third_party` 的 A 轴 gold 有 {len(third_party)} 条：{third_party}——"
        "报告里的 'n=1' 需要更新"
    )


@pytest.fixture(scope="module")
def dataset() -> Dataset:
    """两个 subject 合并成一个数据集，因为缺陷 20/21 都跨 subject 成立。"""
    from pathlib import Path

    root = Path(__file__).resolve().parents[2]
    memories: list[object] = []
    queries: list[object] = []
    for name in ("sample", "billing"):
        ds = load_dataset(root / "data" / "retrieval-v2" / name)
        memories.extend(ds.memories)
        queries.extend(ds.queries)

    return Dataset(memories=tuple(memories), queries=tuple(queries))  # type: ignore[arg-type]
