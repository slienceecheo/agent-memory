"""`dedup` 的比较文本：必须同时含 condition 与 value。

**三个不同的文本规则，不能统一**：

| 用途 | 构造 | 为什么 |
|---|---|---|
| `_embedding_text` | `subject + relation + value` | 向量不掺条件 |
| **`_dedup_text`** | `subject + relation + value + condition` | 去重必须区分分支 |
| `items_fts` | `subject + relation + value + 原文` | 词面要桥接词汇差异 |

向量不掺条件：条件不同的分支在语义上仍是"同一属性"，掺进去会人为拉近或推远。
去重必须含条件：`ruff/None` 与 `ruff/backend` **必须并存**。
词面保留原文：否则 C3 那 9 条"原文与存储值零重叠"的场景结构性失明。

**为什么 dedup 必须含 condition**（实测）：

若两边都用不含 condition 的合成文本，33/33 条 case 的池里都存在
"合成文本完全相同、但 condition 不同"的一对：

```
project:agent-memory code_style ruff   conditions=['None', 'backend']
```

判官看到两条一字不差的文本，几乎必然判 `equivalent`，于是把一条删掉——
而那正是 BRANCH 语义下必须并存的两条。

**为什么不用源行 `text`**：实测 660 条干扰项里只有 44.1% 的
`spec.value` 出现在源行 `text` 中。其余 55.9% 描述的是**另一个值**
（BRANCH 行的 `text` 说的是 `candidate_value`，而 spec 取的是该行的 gold）。
用源行 text 等于给干扰项贴上一句描述别的值的话，
比回退到 tag 更糟——tag 至少不会误导判官。
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from evals.run_retrieval import _dedup_text

from memory.store.models import Authority, MemoryItem, Scope, Source, Status

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data" / "conflict-set"
NOW = datetime(2026, 1, 1, tzinfo=UTC)


def _item_raw(*, value: str, condition: str | None, text: str | None = None) -> MemoryItem:
    return MemoryItem(
        owner="o",
        scope=Scope.PROJECT,
        subject="project:agent-memory",
        relation="code_style",
        value=value,
        condition=condition,
        status=Status.ACTIVE,
        valid_from=NOW,
        valid_to=None,
        recorded_at=NOW,
        authority=Authority.USER_DIRECT,
        source=Source(session_id="s"),
        text=text,
    )


# ---------- 单元 ----------


def test_dedup_text_includes_condition() -> None:
    """含 condition：`ruff/None` 与 `ruff/backend` 必须可区分。"""
    bare = _dedup_text(_item_raw(value="ruff", condition=None))
    scoped = _dedup_text(_item_raw(value="ruff", condition="backend"))

    assert bare != scoped
    assert "ruff" in bare and "ruff" in scoped
    assert "backend" in scoped and "backend" not in bare


def test_dedup_text_includes_value() -> None:
    """含 value：`postgres` 与 `sqlite` 必须可区分（同 relation 不同答案）。"""
    a = _dedup_text(_item_raw(value="postgres", condition=None))
    b = _dedup_text(_item_raw(value="sqlite", condition=None))

    assert a != b


def test_dedup_text_includes_subject_and_relation() -> None:
    text = _dedup_text(_item_raw(value="ruff", condition="backend"))

    assert "project:agent-memory" in text
    assert "code_style" in text


def test_dedup_text_ignores_source_text() -> None:
    """不读 `item.text`：那是候选值的话，不是本条记忆的话。"""
    a = _dedup_text(_item_raw(value="ruff", condition="backend", text="前端目录用 prettier"))
    b = _dedup_text(_item_raw(value="ruff", condition="backend", text=None))

    assert a == b
    assert "prettier" not in a


def test_dedup_text_differs_from_embedding_text() -> None:
    """两者规则不同，是**有意的**，不是重复实现。

    `_embedding_text` 不含 condition（向量不该区分分支），
    `_dedup_text` 含 condition（去重必须区分）。
    若有人把两者合并，本条会红。
    """
    from evals.run_retrieval import _embedding_text

    item = _item_raw(value="ruff", condition="backend")

    assert _embedding_text(item) == "project:agent-memory code_style ruff"
    assert _dedup_text(item) == "project:agent-memory code_style ruff backend"


# ---------- 数据层：dedup 在现有 harness 里没有合法目标 ----------


@pytest.mark.locked_defect
def test_dedup_has_no_legal_merge_target_after_pool_build() -> None:
    """缺陷 15 的一半：`build_pool` 已按 `_key` 去重，池内不存在同 key 同 value 的对。

    **这不是 bug，是职责重叠的结果。**

    `build_pool._key` 是 `(owner, scope, subject, relation, condition)`，
    任何同 key 的两条都会在这里被删掉一条。于是 dedup 拿到的是
    "key 全不同"的池，而它唯一该合并的形态（同 key 同 value）物理上不存在。

    三类两两组合（实测 3300 对）：

    | 形态 | 对数 | 该不该合并 |
    |---|---|---|
    | 值不同、key 不同 | 2970 | 不该 |
    | 值相同、key **不同**（BRANCH） | 33 | **不该**（判官判 complementary） |
    | 同 key | **0** | — |

    若将来 `build_pool` 不再去重（或 `_key` 加上 value），本条应转红——
    那时 dedup 才开始有工作可做，需要重新评估它与 `build_pool` 的职责分工。
    """
    from evals.run_retrieval import _item as _make
    from evals.run_retrieval import select_pool_distractors

    from memory.retrieval.pool import _key, build_pool
    from memory.retrieval.pool_modes import PoolMode

    rows = [
        json.loads(line)
        for line in (DATA / "dev.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    specs = [
        r["gold"]
        for name in ("dev", "test", "independent")
        for r in (
            json.loads(line)
            for line in (DATA / f"{name}.jsonl").read_text(encoding="utf-8").splitlines()
            if line.strip()
        )
        if r.get("gold")
    ]

    same_key_pairs = 0
    total_pairs = 0
    for row in rows:
        gold = row.get("gold")
        if not gold:
            continue
        picked = select_pool_distractors(gold, specs, mode=PoolMode.UNRELATED, limit=20)
        gold_item = _make(row, gold, tag=f"gold-{row['id']}", text=str(row.get("text") or ""))
        dists = [
            _make({"text": ""}, sp, tag=f"d-{row['id']}-{i}", text=None)
            for i, sp in enumerate(picked)
        ]
        pool = build_pool(gold_item, dists, seed=0)
        keys = [_key(entry) for entry in pool.items]
        for i in range(len(keys)):
            for j in range(i + 1, len(keys)):
                total_pairs += 1
                if keys[i] == keys[j]:
                    same_key_pairs += 1

    assert total_pairs > 3000, f"对数太少，数据可能不全：{total_pairs}"
    assert same_key_pairs == 0, (
        f"池内出现了 {same_key_pairs} 对同 key 的条目。"
        "说明 build_pool 不再按 key 去重——dedup 现在有合法目标了，"
        "请重新评估它与 build_pool 的职责分工，并更新缺陷 15。"
    )


@pytest.mark.locked_defect
def test_dedup_breaks_ties_by_id_not_by_input_order() -> None:
    """缺陷 8 的残留：并列分数时，`dedup` 按 id 排序而非保持输入顺序。

    **为什么用固定 id 而不是真数据**：真数据的 id 是 uuid4，
    同进程内两次调用会得到相同结果（uuid 已生成），
    跨进程才有差异。用随机性测随机性不可靠。

    给固定 id 之后，这个变换完全由字典序决定：

    输入 `zzz, aaa, mmm`（分数全 1.0）→ 输出 `aaa, mmm, zzz`

    这是函数对外唯一的可观测契约，不依赖源码写法。

    **修好后的信号**：若 `dedup` 改成保持输入顺序，输出会变成
    `zzz, aaa, mmm`，本测试变红——那时翻面成正向断言，
    并更新 C4 报告缺陷 8 的残留说明。
    """
    from memory.retrieval.dedup import dedup
    from memory.retrieval.equivalence import Equivalence

    class _AlwaysUnrelated:
        enabled = True

        def judge(self, left: str, right: str) -> object:
            return type("R", (), {"equivalence": Equivalence.UNRELATED})()

    ranked = [("zzz", "t1", 1.0), ("aaa", "t2", 1.0), ("mmm", "t3", 1.0)]
    kept, stats = dedup(ranked, judge=_AlwaysUnrelated(), top_k=5)  # type: ignore[arg-type]

    assert stats.merged == 0, "全部判无关，不该合并"
    assert [e[0] for e in kept] == ["aaa", "mmm", "zzz"], (
        "并列时不再按 id 排序。若是有意改成保持输入顺序，"
        "说明缺陷 8 的残留已消除——请翻面成正向断言并更新 C4 报告。"
    )


def test_dedup_preserves_score_order_when_distinct() -> None:
    """分数不同时，必须按分数降序——这是 `dedup` 的核心职责。"""
    from memory.retrieval.dedup import dedup
    from memory.retrieval.equivalence import Equivalence

    class _AlwaysUnrelated:
        enabled = True

        def judge(self, left: str, right: str) -> object:
            return type("R", (), {"equivalence": Equivalence.UNRELATED})()

    ranked = [("aaa", "t1", 0.3), ("zzz", "t2", 0.9), ("mmm", "t3", 0.6)]
    kept, _ = dedup(ranked, judge=_AlwaysUnrelated(), top_k=5)  # type: ignore[arg-type]

    assert [e[0] for e in kept] == ["zzz", "mmm", "aaa"]

    """缺陷 15：`build_pool` 已按 `_key` 去重，所以池内不存在同 key 同 value 的对。

    **这不是 bug，是职责重叠的结果。**

    `build_pool._key` 是 `(owner, scope, subject, relation, condition)`，
    任何同 key 的两条都会在这里被删掉一条。于是 dedup 拿到的是
    "key 全不同"的池，而它唯一该合并的形态（同 key 同 value）物理上不存在。

    三类两两组合（实测 3300 对）：

    | 形态 | 对数 | 该不该合并 |
    |---|---|---|
    | 值不同、key 不同 | 2970 | 不该 |
    | 值相同、key **不同**（BRANCH） | 33 | **不该**（判官判 complementary） |
    | 同 key | **0** | — |

    所以 dedup 在当前 harness 上无论输入什么文本，都不该合并任何一对。
    接线之后分数不变是**预期**，不是接线失败。

    若将来 `build_pool` 不再去重（或 `_key` 加上 value），本条应转红——
    那时 dedup 才开始有工作可做，需要重新评估它与 `build_pool` 的职责分工。
    """
    from evals.run_retrieval import _item as _make
    from evals.run_retrieval import select_pool_distractors

    from memory.retrieval.pool import _key, build_pool
    from memory.retrieval.pool_modes import PoolMode

    rows = [
        json.loads(line)
        for line in (DATA / "dev.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    specs = [
        r["gold"]
        for name in ("dev", "test", "independent")
        for r in (
            json.loads(line)
            for line in (DATA / f"{name}.jsonl").read_text(encoding="utf-8").splitlines()
            if line.strip()
        )
        if r.get("gold")
    ]

    same_key_pairs = 0
    total_pairs = 0
    for row in rows:
        gold = row.get("gold")
        if not gold:
            continue
        picked = select_pool_distractors(gold, specs, mode=PoolMode.UNRELATED, limit=20)
        gold_item = _make(row, gold, tag=f"gold-{row['id']}", text=str(row.get("text") or ""))
        dists = [
            _make({"text": ""}, sp, tag=f"d-{row['id']}-{i}", text=None)
            for i, sp in enumerate(picked)
        ]
        pool = build_pool(gold_item, dists, seed=0)
        keys = [_key(entry) for entry in pool.items]
        for i in range(len(keys)):
            for j in range(i + 1, len(keys)):
                total_pairs += 1
                if keys[i] == keys[j]:
                    same_key_pairs += 1

    assert total_pairs > 3000, f"对数太少，数据可能不全：{total_pairs}"
    assert same_key_pairs == 0, (
        f"池内出现了 {same_key_pairs} 对同 key 的条目。"
        "说明 build_pool 不再按 key 去重——dedup 现在有合法目标了，"
        "请重新评估它与 build_pool 的职责分工，并更新缺陷 15。"
    )
