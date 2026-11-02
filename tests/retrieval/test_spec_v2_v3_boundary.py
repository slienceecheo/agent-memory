"""`memory-retrieval` 的正式 spec 必须写明"v2 产物不适用于本版本"。

**这条原来断言的是 delta，而 delta 归档后会被移走** —— 于是三条断言变成
`pytest.skip("delta 已归档或不存在")`，在 CI 里只是三个 `s`。

而它们守的是**唯一一条**"v2 结果不能用 v3 代码读"的机械断言。
**所以改为断言归档后的正式 spec。**

**改路径必须同时改措辞**：归档把那段散文改写成了一条 scenario，
而 scenario 用的是另一套词：

| 归档前（delta 散文） | 归档后（spec scenario） |
|---|---|
| 不适用于本版本 | **不同构** + **跨版本误用** |
| 不得为了兼容 v2 产物而保留 | **MUST NOT 为了兼容…而保留** |
| 标题沿用旧名 / 只有一处 | **标题与正文的这处不一致是已知的** |

**只改路径不改措辞会立刻红**，而红的原因不是"约束丢了"，
是"同一语义换了说法"。所以这里的断言按**语义**写，不按旧字面写。

**但不能放宽成"文件里出现 15 份冻结结果"** —— 那样几乎不断言。
下面每条断言都对应一个**可被违反的**判据。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
# 归档后 delta 在 archive 下；正式 spec 是唯一权威
ARCHIVED = (
    ROOT / "openspec" / "changes" / "archive" / "2026-11-02-retrieval-v3-apparatus"
)
SPEC = ROOT / "openspec" / "specs" / "memory-retrieval" / "spec.md"
RESULTS = ROOT / "results"


def _text() -> str:
    """读**正式 spec**（归档后的唯一权威）。

    **没有 skip 分支**：spec 不存在说明仓库坏了，应该红而不是跳过。
    上一版有 `if not DELTA.exists(): pytest.skip(...)`，
    而归档恰好让那个条件永远成立——**skip 条件写宽了就是这个后果**。
    """
    assert SPEC.exists(), f"正式 spec 不存在：{SPEC}"
    return SPEC.read_text(encoding="utf-8")


def _requirement_block(title: str) -> str:
    """取某条 requirement 的完整块（到下一个 ### Requirement 为止）。"""
    text = _text()
    start = text.index(f"### Requirement: {title}")
    rest = text[start + 5 :]
    nxt = rest.find("\n### Requirement: ")
    return rest if nxt < 0 else rest[:nxt]


def test_spec_states_v2_results_are_not_comparable() -> None:
    """必须写明 v2 产物与本版本**不同构**，且给出两代产物的特征数对照。"""
    block = _requirement_block("四特征重排")

    assert "不同构" in block, (
        "未写两代产物'不同构'。这是'不可比'的定性——"
        "没有它，读者会以为 v2 的数字仍可与 v3 比较。"
    )
    assert "四个" in block and "三个" in block, (
        "缺少特征数对照（四个 vs 三个）。只说'不同构'而不给数，读者无法自查。"
    )
    assert "v2 的 15 份冻结结果" in block
    assert "四元组" in block and "三元组" in block, (
        "缺少两代产物的 weights 字段形态对照"
    )


def test_spec_calls_reading_v2_with_v3_code_a_misuse() -> None:
    """必须把"用 v3 代码读 v2 结果"定性为**跨版本误用**，不是解析失败。"""
    block = _requirement_block("四特征重排")

    assert "跨版本误用" in block, (
        "未写'跨版本误用'。若只说'解析失败'，读者会去修解析器——"
        "而正确处置是'这份结果不属于本装置'。"
    )
    # 反向：不能把这件事降级成"解析失败"
    assert "而不是" in block and "解析失败" in block


def test_spec_forbids_compat_shim() -> None:
    """必须写明"不得为兼容 v2 而保留 condition 权重"。"""
    block = _requirement_block("四特征重排")

    # 一条完整句子一起断言：分开断言时，删掉整句只会让第一条红，
    # 后面几条等于没被独立验证过。
    combined = "MUST NOT 为了兼容"
    assert combined in block, (
        "未写'不得为兼容 v2 产物而保留'。"
        "缺它的后果：有人会加一个兼容层让 v2 结果可读——"
        "而那会把'三特征'退回'四特征'。"
    )
    assert "`condition`" in block, "禁令没点名 condition 权重"
    # 写明后果
    assert "重新变成四特征" in block, (
        "未写明后果。只说'不得'而不说'为什么'，下一个人会认为这条是洁癖。"
    )


def test_spec_forbids_recomputing_v2_with_v3_tool() -> None:
    """必须写明"复算 v2 的数字要用 v2 的代码状态"。"""
    block = _requirement_block("四特征重排")

    assert "复算 v2 的数字 MUST 使用 v2 的代码状态" in block, (
        "未写复算规则。缺它的后果：有人会用本版本的 recompute_order "
        "去复算 v2 结果，得到差异后误判为'实现回归'。"
    )
    assert "MUST NOT 用本版本的 `recompute_order`" in block, (
        "未写出具体禁止的工具名。只写'用 v2 的代码状态'太抽象，"
        "读者不知道本版本哪个工具不该用。"
    )


def test_spec_claim_about_v2_products_is_verifiable() -> None:
    """spec 说的"v2 用四特征跑"必须能从 v2 结果文件复算。

    **这条防的是"文档写了一个没被验证的事实"**：
    若某天 v2 结果被重跑成三特征，spec 里那段说明就成了假的。

    判据是 v2 的 `per_case[0]` **没有** `features` 字段——
    那正是 v3 才加的。有了它，说明这批结果是新格式，spec 的说明要重核。
    """
    sample = RESULTS / "v2-billing-lexical.json"
    if not sample.exists():
        pytest.skip("v2 结果缺失")

    data = json.loads(sample.read_text(encoding="utf-8"))
    per_case = data.get("per_case") or []

    assert per_case, "v2 结果没有 per_case"
    assert "features" not in per_case[0], (
        "v2 结果的 per_case 出现了 features 字段。"
        "若 v2 被重跑成新格式，spec 里'v2 是四特征'的说明要重新核对。"
    )
    assert data.get("code_version") is not None
