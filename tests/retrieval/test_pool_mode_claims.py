"""`SAME_RELATION` 模式的成员构成与它的 docstring 不符。

**这是 C4 的第六个缺陷**：`pool_modes.select_distractors` 的注释说
`same_relation` 是"同 relation、不同 subject"，但代码只排除了与 gold
**同逻辑键**的条目，没有 subject 条件。

本文件把这个事实钉住，使两件事不会同时发生：
1. 有人悄悄改代码补上 subject 条件，而报告仍说它"混轴"
2. 有人悄悄改 docstring 让它"变成对的"，而代码没动

无论哪一边先改，这里都会失败，提示同时更新报告与协议。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from evals.run_retrieval import select_pool_distractors

from memory.retrieval.pool_modes import PoolMode

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data" / "conflict-set"


def _rows(name: str) -> list[dict[str, object]]:
    path = DATA / name
    if not path.exists():
        pytest.skip(f"{name} 不存在")
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _all_specs() -> list[dict[str, object]]:
    specs: list[dict[str, object]] = []
    for name in ("dev.jsonl", "test.jsonl", "independent.jsonl"):
        specs.extend([row["gold"] for row in _rows(name) if row.get("gold")])  # type: ignore[misc]
    return specs


@pytest.mark.locked_defect
def test_same_relation_mixes_subjects() -> None:
    """`SAME_RELATION` 选出的干扰项里，有相当一部分与 gold 同 subject。

    这意味着这个模式**同时混进了 A 轴的真兄弟与非 A 轴**，
    测出来的分数无法归因到任何一条难度轴。

    若这个数字变成 0，说明代码被改成"不同 subject"了——
    那时必须同时更新 C4 报告第 0.1 节与 v2 协议 §5。
    """
    specs = _all_specs()
    total = 0
    same_subject = 0
    for name in ("dev.jsonl", "test.jsonl", "independent.jsonl"):
        for row in _rows(name):
            gold = row.get("gold")
            if not gold:
                continue
            picked = select_pool_distractors(
                gold, specs, mode=PoolMode.SAME_RELATION, limit=20
            )
            for candidate in picked:
                total += 1
                if candidate.get("subject") == gold.get("subject"):
                    same_subject += 1

    assert total > 0
    assert same_subject == 62, (
        f"同 subject 的干扰项由 62 变成 {same_subject}（共 {total}）。"
        "若这是有意的修复，请同步更新 C4 报告第 0.1 节与 v2 协议 §5"
    )


@pytest.mark.locked_defect
def test_unrelated_mode_is_a_file_order_prefix() -> None:
    """`UNRELATED` 取的是文件顺序的前 N 条，不是随机采样。

    这使 76 条场景只有 15 种不同的干扰项组合。若有人加了随机采样，
    这个测试会失败——那是有益的改动，但报告里的"固定前缀"结论必须一起改。
    """
    specs = _all_specs()
    compositions = set()
    for name in ("dev.jsonl", "test.jsonl", "independent.jsonl"):
        for row in _rows(name):
            gold = row.get("gold")
            if not gold:
                continue
            picked = select_pool_distractors(gold, specs, mode=PoolMode.UNRELATED, limit=20)
            compositions.add(tuple((s.get("subject"), s.get("relation")) for s in picked))

    assert len(compositions) < 20, (
        f"干扰项组合有 {len(compositions)} 种；"
        "若已改为随机采样，需同步更新报告第 0.1 节的 '15 种组合'"
    )
