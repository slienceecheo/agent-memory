"""`memory-retrieval` 的 delta 必须写明"v2 产物不适用于本版本"。

**为什么这条要存在**：`memory-retrieval` 的两条 requirement 是 MODIFIED，
归档时它们会**覆盖**正式 spec 的原文。所以那段说明若不写在 delta 里，
归档后就永远没有了——而"spec 说三特征、v2 结果是四特征"会在第一次复算时爆发。

**为什么断言"标题沿用旧名"**：改标题会让归档拒绝
（`MODIFIED failed for header ... not found`）。而标题与正文不一致本身是缺陷，
所以必须显式登记为"已知且只有一处"——否则下一个人会以为正文写错了。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
CHANGE = ROOT / "openspec" / "changes" / "retrieval-v3-apparatus"
DELTA = CHANGE / "specs" / "memory-retrieval" / "spec.md"
RESULTS = ROOT / "results"


def _text() -> str:
    if not DELTA.exists():
        pytest.skip("delta 已归档或不存在")
    return DELTA.read_text(encoding="utf-8")


def test_delta_states_v2_results_do_not_apply() -> None:
    """必须写明 v2 产物不适用于本版本，且给出两代产物的特征数对照。"""
    text = _text()

    assert "不适用于本版本" in text, "delta 未写 'v2 产物不适用于本版本'"
    assert "v2 的 15 份冻结结果" in text
    assert "四元组" in text and "三元组" in text, (
        "缺少两代产物的 weights 字段形态对照（四元组 / 三元组）"
    )


def test_delta_forbids_compat_shim() -> None:
    """必须写明"不得为兼容 v2 而保留 condition 权重"。"""
    text = _text()
    assert "不得为了兼容 v2 产物而保留" in text


def test_delta_flags_title_body_mismatch() -> None:
    """标题沿用"四特征重排"而正文是三特征——这个不一致必须被显式登记。"""
    text = _text()
    assert "### Requirement: 四特征重排" in text, (
        "标题被改过。MODIFIED 的标题是匹配键，改名会让归档拒绝。"
    )
    assert "标题沿用旧名" in text, (
        "标题与正文不一致，但没有登记。下一个人会以为正文写错了。"
    )
    assert "只有一处" in text, "未说明这处不一致的范围"


def test_delta_knowledge_matches_actual_v2_products() -> None:
    """delta 说的"v2 用四特征跑"必须能从 v2 结果文件复算。

    **这条防的是"文档写了一个没被验证的事实"**：
    若某天 v2 结果被重跑成三特征，delta 的说明就成了假的。

    判据是 v2 的 `per_case[0]` **没有** `features` 字段——
    那正是 v3 才加的。有了它，说明这批结果是新格式，delta 的说明要重核。
    """
    sample = RESULTS / "v2-billing-lexical.json"
    if not sample.exists():
        pytest.skip("v2 结果缺失")

    data = json.loads(sample.read_text(encoding="utf-8"))
    per_case = data.get("per_case") or []

    assert per_case, "v2 结果没有 per_case"
    assert "features" not in per_case[0], (
        "v2 结果的 per_case 出现了 features 字段。"
        "若 v2 被重跑成新格式，delta 里'v2 是四特征'的说明要重新核对。"
    )
    # v2 结果带四权重时代的指纹，不是当前代码状态的产物
    assert data.get("code_version") is not None
