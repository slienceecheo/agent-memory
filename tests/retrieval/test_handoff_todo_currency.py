"""HANDOFF 的待办表必须与当前装置一致。

**为什么需要**：待办表第 1 行曾写「`condition` 权重 0.25 让同 relation 内
几乎自动满分」——而 `condition` 已在 `retrieval-v3-apparatus` 退出加权、
`status` 已在 `cosine-as-sort-feature` 删除。那行漂移了两次，无人发现。

同类的「HANDOFF 组数」已经有断言守着
（`test_handoff_v3.py::test_handoff_preregistered_count_matches_reality`），
这条补的是待办表。
"""

from __future__ import annotations

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
HANDOFF = ROOT / "docs" / "HANDOFF.md"


def _text() -> str:
    if not HANDOFF.exists():
        pytest.skip("HANDOFF 缺失")
    return HANDOFF.read_text(encoding="utf-8")


def _todo_section(text: str) -> str:
    """取出「## 待办」那一节，到最近的二级标题为止。"""
    marker = "## 待办"
    assert marker in text, "HANDOFF 里找不到「## 待办」这一节"
    rest = text.split(marker, 1)[1]
    end = rest.find("\n## ")
    return rest[:end] if end >= 0 else rest


def test_todo_does_not_claim_condition_still_has_weight() -> None:
    """待办表不得声称 `condition` 仍有排序权重。

    **实测历史**：该行曾写
    「未开始。`condition` 权重 0.25 让同 relation 内几乎自动满分」，
    而 `RerankWeights` 早已没有 `condition` 字段
    （`test_rerank.py::test_preregistered_weights_are_all_valid` 守着这一点）。

    **为什么这条写在 HANDOFF 侧而不是产品侧**：产品侧已经不可能有
    `condition` 权重（`RerankWeights` 的字段集被断言锁定）。
    这里防的是**文档描述一个不存在的产品状态**。
    """
    section = _todo_section(_text())

    # 允许出现 condition（第 2 条在讨论它），但不允许声称它有「权重」
    for line in section.splitlines():
        if "condition" not in line:
            continue
        assert "权重 0.25" not in line, (
            "待办表里有一行仍写 `condition` 权重 0.25，而该特征已退出加权。\n"
            f"行内容：{line.strip()[:120]}"
        )
        assert "让同 relation 内几乎自动满分" not in line, (
            "待办表里有一行仍把 A 轴易满分归因于 `condition` 权重，"
            "而那是 v2 装置的性质。\n"
            f"行内容：{line.strip()[:120]}"
        )


def test_todo_names_the_three_feature_gain_as_the_v3_goal() -> None:
    """v3 的第一个待办必须是「测三特征装置的增益」，不是「修 A 轴难度」。

    **为什么**：「修 A 轴难度」的前提（`condition` 让满分容易）已消失，
    而真正要回答的问题变成了「三特征装置在派生 within 轴上的增益是多少」。
    两个目标对数据的要求不同——前者要「条件更难」，
    后者要「语义相近、字面不同」。
    """
    section = _todo_section(_text())

    assert "三特征" in section, (
        "待办表没提「三特征装置的增益」——v3 的第一个目标应该就是它"
    )
    assert "修 A 轴难度" not in section, (
        "待办表仍以「修 A 轴难度」为第一目标，而它的前提已消失"
    )


def test_todo_offers_both_condition_dispositions() -> None:
    """`condition` 的待办必须给出**两条**路：消费它，或明确永不消费。

    **为什么必须有两个选项**：只写「让它进入召回」是预设结论。
    而 v2 的教训是「有权重但直通」，v3 是「无权重也无用途」——
    两种都不好，所以要么给它一个真实用途，要么承认它只是审计并彻底移除。

    **判据只查正文的「前置」段，不查标题**：标题里就有「或明确永不消费」
    这句话，查全文会让标题把正文的空缺顶替掉——那是本项目反复出现的
    「用同一段文本的另一处顶替」。
    """
    section = _todo_section(_text())

    # 定位条件那条的**正文**（第 4 列）。
    # 表格行按 `|` 切分为 5 段：['', '#', '事项标题', '正文', '']。
    # **取错列就会让标题顶替正文**——实测过：取 [2] 是标题，
    # 而标题里恰好有「或明确永不消费」，于是删掉正文后断言仍绿。
    line = next(
        (ln for ln in section.splitlines() if "condition" in ln and "消费" in ln),
        None,
    )
    assert line is not None, "待办里找不到 condition 消费点那一条"

    cells = line.split("|")
    assert len(cells) >= 5, f"待办行不是 4 列：{line[:100]}"
    body = cells[3]

    assert "消费" in body, "正文没提「给 condition 找消费点」"
    assert "永不消费" in body or "彻底移除" in body, (
        "正文没给「明确永不消费」这条路——"
        "那是避免「为了用上它而硬加用途」的唯一出口。\n"
        f"正文：{body.strip()[:160]}"
    )
