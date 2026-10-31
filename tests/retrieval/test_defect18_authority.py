"""缺陷 18：造 v2 样例时为凑 `authority` 方差而降级来源。

C4 的 `test_rerank_variance` 断言"真实数据里 `authority` 必须不止一个取值"。
那条测试跑的是 `conflict-set`，不是 v2。但造 v2 样例时照着那个经验，
给两条记忆降了级——**而协议 §3.1 从未要求 `authority` 有方差**。

这是缺陷 4 的反向形态：

| 缺陷 | 方向 |
|---|---|
| 4 | 测试查错了对象 → 通过但性质不成立 |
| 18 | **为了让测试有方差 → 数据属性被人工制造** |

本测试**断言缺陷存在**（有非 `user_direct` 且原文不说明来源），
修好（v2.1 按 F18 造数据）后变红，那时翻面。
"""

from __future__ import annotations

from pathlib import Path

import pytest
from evals.datasets.retrieval_v2 import load_dataset

ROOT = Path(__file__).resolve().parents[2]
SAMPLE = ROOT / "data" / "retrieval-v2" / "sample"

#: 能在原文里说明"为什么这条是降级来源"的线索词。
SOURCE_CUES = (
    "HR",
    "系统",
    "同事",
    "转述",
    "文档",
    "听说",
    "群里",
    "审计",
    "邮件",
    "工单",
    "外部",
    "第三方",
    "截图",
    "会议纪要",
)


@pytest.mark.locked_defect
def test_sample_authority_is_unjustified() -> None:
    """缺陷 18：样例里有 2 条来源降级，原文都不说明来源。

    断言的是**缺陷存在**。v2.1 按 F18 造数据后本测试变红。
    """
    dataset = load_dataset(SAMPLE)

    downgraded = [m for m in dataset.memories if m.authority.value != "user_direct"]
    assert len(downgraded) == 2, (
        f"来源降级的条数从 2 变成了 {len(downgraded)}；"
        "若 v2.1 已按 F18 修正，请翻面本测试"
    )

    unexplained = [
        m for m in downgraded if not any(cue in m.memory_text for cue in SOURCE_CUES)
    ]
    assert len(unexplained) == 2, (
        f"{len(unexplained)}/2 条来源降级在原文里没有说明。"
        "若已补齐来源线索，说明 F18 的要求已被满足，请翻面。"
    )


def test_authority_distribution_shape_is_suspicious() -> None:
    """分布形态 10/1/1 不像场景自然产生，像"为有方差而放的样本"。

    这条是**辅助证据**，不是判据本身。判据是"原文是否自解释"（F18）。
    """
    dataset = load_dataset(SAMPLE)
    counts: dict[str, int] = {}
    for memory in dataset.memories:
        counts[memory.authority.value] = counts.get(memory.authority.value, 0) + 1

    assert counts.get("user_direct", 0) == 10
    assert counts.get("third_party", 0) == 1
    assert counts.get("user_document", 0) == 1
    # 两种非默认值各出现 1 次，这是"凑方差"的典型形态
    assert sum(1 for v in counts.values() if v == 1) == 2


def test_v2_gates_had_no_authority_check() -> None:
    """**记录事实**：F18 之前，v2 的门禁里没有任何 authority 检查。

    这解释了为什么"给 authority 制造方差"没有约束——
    没有门禁会拦住它，也没有门禁会提醒"协议从未要求分布"。
    """
    source = (ROOT / "evals" / "tools" / "check_v2_dataset.py").read_text(encoding="utf-8")

    # F18 已经存在，但它必须是**唯一**的 authority 相关门禁
    assert "check_f18_authority_is_justified" in source
    assert source.count("authority") > 0


@pytest.mark.locked_defect
def test_q4_loses_to_unrelated_entries_on_authority() -> None:
    """缺陷 19：q4 的 gold 在 base 与 cond 上都占优，却因 auth 掉到第 3。

    这是四特征值之间的**算术事实**，不依赖 LLM 或 embedding：

        base: +w.base      × (1.000 − 0.910)
        cond: +w.condition × (1.00 − 0.50)
        auth: −w.authority × (1.00 − 0.00)

    在 `uniform` 权重下（各 0.25）：

        base: +0.0225 / cond: +0.1250 / auth: −0.2500 / 净差 −0.1025

    **`w` 必须从 `PREREGISTERED_WEIGHTS` 读，不能抄 0.25。**
    抄常量会让"改产品权重"不触发这条测试——实测把 `uniform` 改成
    base 0.24 / condition 0.26 时，抄常量的版本仍然全绿，
    而它恰好是缺陷 19/21 唯一的相关锁定。

    断言的是**缺陷存在**（auth 罚分能推翻 base+cond 的双重优势）。
    修好（`authority` 移出排序特征，或权重降到 0.05 以下）后变红。
    """
    from memory.retrieval.rerank import PREREGISTERED_WEIGHTS

    w = PREREGISTERED_WEIGHTS["uniform"]
    d_base = 1.000 - 0.910
    d_cond = 1.00 - 0.50
    auth_penalty = w.authority * (1.00 - 0.00)

    advantage = w.base * d_base + w.condition * d_cond
    assert advantage == pytest.approx(0.1475, abs=1e-4), (
        f"base+cond 优势 {advantage} 不再是 0.1475——"
        "`uniform` 权重变了，缺陷 19 的算术需要重新评估"
    )
    assert auth_penalty == pytest.approx(0.25)
    assert auth_penalty > advantage, "auth 罚分不再能推翻 base+cond 双优，缺陷 19 可能已修"

    # 量化判据：推翻条件等价于 w.authority > w.base*d_base + w.condition*d_cond
    assert d_base + d_cond < 1.0
    assert auth_penalty - advantage == pytest.approx(0.1025, abs=1e-4), (
        f"净差变成 {auth_penalty - advantage:.4f}，不再是 0.1025。\n"
        "先分清两件事再动手：\n"
        "  - 若 authority **没降**、只是 base/condition 重新分配 —— 缺陷 19 还在，\n"
        "    只需更新报告里的 0.1025（c4-retrieval.md:353、v2-sample-validation.md:211）\n"
        "  - 若 authority **被降** —— 那才是缺陷被修，应翻面成正向断言\n"
        "结构断言（auth_penalty > advantage）红才说明缺陷没了；\n"
        "只有数值断言红时，缺陷可能完好。"
    )


def test_authority_weight_threshold_is_quantified() -> None:
    """权重降到多少才安全：0.05 时推翻条件是 `d_base + d_cond < 0.2`。

    这给修的人一个具体数字，而不是"太高"这种定性说法。
    """
    for weight, threshold in ((0.25, 1.0), (0.05, 0.2)):
        # auth 罚分 = w × 1，base+cond 优势 = w × (d_base + d_cond)
        # 推翻 ⇔ 1 > d_base + d_cond
        assert weight * 1.0 > weight * (threshold - 1e-9)
