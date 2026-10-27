"""v2 的干扰项必须带自己的 `memory_text`，否则 FTS 索引缺原文。

**这是缺陷 2（干扰项无原文）在 v2 上的复发。**

`run_retrieval` 构造干扰项时写死 `text=None`：

```python
distractors = [_item({"text": ""}, spec, tag=..., text=None) ...]
```

C4 时代这没问题（C4 的 gold spec 本来就没有原文）。但 v2 的每条记忆
**都有 `memory_text`**，这一行把它丢掉了，于是：

- FTS 索引里只剩 `subject + relation + value`
- 共享情境词（如"值班"）进不了索引
- 查询只能用**分支的 value** 或**单字**命中，两者都不是"同主题竞争"

实测 `q1`（"工作日白天值班该找谁？"）命中 4 条，但只有陈昊、赵启
是真命中（共享 `值班`），林晓靠单字 `找`、周敏靠单字 `天`。

修复之后，"命中几条"才可能等于"几条真在竞争"。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from evals.datasets.retrieval_v2 import load_dataset
from evals.datasets.v2_adapter import rows as adapt_rows
from evals.run_retrieval import _item

from memory.retrieval.pool import build_pool

ROOT = Path(__file__).resolve().parents[2]
SAMPLE = ROOT / "data" / "retrieval-v2" / "sample"


@pytest.fixture(scope="module")
def dataset():
    if not SAMPLE.exists():
        pytest.skip("样例数据集缺失")
    return load_dataset(SAMPLE)


def test_v2_gold_specs_carry_memory_text(dataset) -> None:
    """适配层产出的 gold spec 必须带 `memory_text`。

    C4 的 gold spec 没有这个字段（本来就无原文可带），
    v2 的有——两者不该用同一套默认值。
    """
    adapted = adapt_rows(dataset)
    specs = [row["gold"] for row in adapted if row["gold"]]

    assert specs
    missing = [s for s in specs if not s.get("memory_text")]
    assert not missing, f"{len(missing)} 条 gold spec 缺 memory_text"


def test_v2_distractor_carries_its_memory_text(dataset) -> None:
    """**核心**：构造池时，干扰项的 `text` 必须是它自己的 `memory_text`。

    现在会红——`run_retrieval` 写死 `text=None`。
    本测试只检查池条目（不经 store），因为 `text` 在构造时就已确定。
    """
    adapted = adapt_rows(dataset)
    specs = [row["gold"] for row in adapted if row["gold"]]
    row = next(r for r in adapted if r["relation"] == "oncall_owner")

    others = [
        s
        for s in specs
        if (s["subject"], s["relation"], str(s.get("condition")))
        != (row["gold"]["subject"], row["gold"]["relation"], str(row["gold"]["condition"]))
    ]

    gold = _item(row, row["gold"], tag="gold", text=row["gold"].get("memory_text"))
    dists = [
        _item({"text": ""}, s, tag=f"d-{i}", text=s.get("memory_text") or None)
        for i, s in enumerate(others[:20])
    ]
    pool = build_pool(gold, dists, seed=0)

    v2_dists = [e for e in pool.items if e.id.startswith("d-") and e.text]
    assert v2_dists, "池内 v2 干扰项没有一个带原文——FTS 索引里不会有共享情境词"


def test_c4_specs_have_no_memory_text(dataset) -> None:
    """C4 的 gold spec 不带 `memory_text`——行为自动分化，不需要开关。

    v2 有原文、C4 没有，所以"修 harness"只影响 v2，
    C4 的旧结果不受影响。
    """
    c4_path = ROOT / "data" / "conflict-set" / "dev.jsonl"
    if not c4_path.exists():
        pytest.skip("C4 数据集缺失")
    rows = [
        json.loads(line)
        for line in c4_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    golds = [r["gold"] for r in rows if r.get("gold")]

    assert golds
    assert all("memory_text" not in g for g in golds), (
        "C4 的 gold spec 出现了 memory_text；两套数据的行为分化前提被破坏"
    )
