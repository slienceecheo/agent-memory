"""缺陷 14：gold 的向量输入不得包含查询原文。

**为什么只改向量、不动 `text` 字段**：

`text` 同时被两条路径使用：

| 路径 | 读什么 | 去掉 text 的后果 |
|---|---|---|
| 向量 | `_embedding_text()` | 泄露消失（要的） |
| 词面 | `sqlite._write_fts()` 拼 `item.text` | **召回塌陷（不要的）** |

实测（P2-b'-0，只读探针）：

```
去掉 gold.text 后：
  召回总条数  41 → 28 (-13)
  gold 被召回 33/33 → 20/33
  零召回 case 0 → 10
```

**10 条 case 直接变成零召回。** 所以 `text` 字段必须保留给 FTS，
只把 `_embedding_text` 的输入改成 `subject + relation + value`。

这样两条路径各自负责一个维度：
- 向量测"结构化字段的语义匹配"，不掺原文
- 词面测"原文 + 字段的词面匹配"

也顺带修好了**对称性**：现在是 gold 有 text、干扰项 text=None，
两边向量输入的构造规则不同。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from evals.run_retrieval import _embedding_text, _item

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data" / "conflict-set"


def _gold_rows() -> list[dict[str, object]]:
    path = DATA / "dev.jsonl"
    if not path.exists():
        pytest.fail(f"数据集缺失：{path}")
    rows = [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    return [r for r in rows if r.get("gold")]


def test_gold_document_text_does_not_contain_query() -> None:
    """缺陷 14 已修复：gold 的向量输入不含查询原文。

    **原先这条是 `locked_defect`，断言"32/33 条泄露"。**
    现在翻面成正向断言：修复提交就是它该翻面的时机
    （`locked_defect` 的失败信息里写明了这个动作）。
    """
    leaking = 0
    total = 0
    for row in _gold_rows():
        total += 1
        gold = _item(row, row["gold"], tag="g", text=str(row.get("text") or ""))  # type: ignore[arg-type]
        if str(row["query"]) in _embedding_text(gold):
            leaking += 1

    assert total > 0
    assert leaking == 0, (
        f"{leaking}/{total} 条 gold 的向量输入含查询原文；"
        "向量路径又会靠自相似把 gold 顶上去"
    )


def test_embedding_text_ignores_text_field() -> None:
    """`_embedding_text` 不读 `item.text`。

    这条是**正向断言**（修好后应恒绿），与上面那条锁定测试互补：
    锁定测试说"现在有 32 条泄露"，这条说"构造规则里不该有 text"。
    """
    source = (ROOT / "evals" / "run_retrieval.py").read_text(encoding="utf-8")
    start = source.index("def _embedding_text")
    end = source.index("\n\n\ndef ", start)
    body = source[start:end]

    assert "parts.append(item.text)" not in body, (
        "_embedding_text 又开始拼 item.text 了；向量输入会再次含查询原文"
    )
    assert "item.subject" in body and "item.relation" in body and "item.value" in body


def test_gold_and_distractor_use_same_rule() -> None:
    """gold 与干扰项的向量输入必须由同一规则构造。

    原先 gold 有 text、干扰项 `text=None`，两者规则不同——
    这本身就使"向量的贡献"无法解释：一路吃了原文，另一路没有。
    """
    row = _gold_rows()[0]
    gold = _item(row, row["gold"], tag="g", text="一段原文")  # type: ignore[arg-type]

    text_input = _embedding_text(gold)
    gold_without = _item(row, row["gold"], tag="g", text=None)  # type: ignore[arg-type]
    none_input = _embedding_text(gold_without)

    assert text_input == none_input, (
        "有无 text 应产生相同的向量输入；若不同，说明规则仍不对称"
    )
    assert "一段原文" not in text_input


def test_lexical_still_sees_source_text() -> None:
    """词面路径仍然索引原文——P2-b'-1 不得牵连 FTS。

    这是**防止过度修复**的保护：有人为了彻底去掉泄露，
    可能把 `MemoryItem.text` 也设成 None，那会让 10 条 case 零召回。
    """
    source = (ROOT / "src" / "memory" / "store" / "sqlite.py").read_text(encoding="utf-8")

    assert "if item.text:" in source
    assert "content = f\"{content} {item.text}\"" in source
