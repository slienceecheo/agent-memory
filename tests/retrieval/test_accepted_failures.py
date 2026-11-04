"""哪些门禁失败是可接受的——必须写成测试，否则后来者会去"修"它们。

**为什么需要**：协议 §11.0 的新判据是：

    (a) 每条未通过的门禁，都在报告里写明"为什么这个失败是正确的"
    (b) 该说明有一条测试锁定

**(b) 是关键**：没有它，下一个人看到 `F13 = 40%` 会去补 implicit 查询——
而那是**改数据**，违反协议 §1.2（看到分数后不许改数据）。
写了测试，他改动时会先看到"这是已登记的失败，不是待修的 bug"。

### 分类

| 类型 | 含义 | 能不能修 |
|---|---|---|
| 构造性 | 数据规模不够 | 铺开时自然通过 |
| 正确的失败 | 数据本身有缺陷，修它要改数据 | **不修，作为证据保留** |
| 真实不足 | 阈值没达到 | 补数据（不是改已有数据） |
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
RESULTS = ROOT / "results"
PROTOCOL = ROOT / "docs" / "requirements" / "retrieval-dataset-v2.md"

# 已登记的未通过项及其分类（两个 subject 的并集，共 7 条）。
#
# **这是唯一权威清单。** 新增未通过项必须同时改这里与协议 §11.0.1，
# 否则 `test_no_unregistered_failure` 会红。
#
# 实测分布（**读的是冻结的 v2 装置文件**，不是当前 run_all）：
#   sample  6 条：F6 / F13 / F17b / F18 / F21a / F21b
#            （F20/F24 在 sample 上是**通过**，不在失败列表里）
#   billing 3 条：F6 / F21b / F24
#            （F20 在 billing 上通过）
#
# **当前代码是 v3 装置**，F20/F24 都 `applicable=False`（跨装置）。
# 那份"不适用"与这里的"失败"是两件事，两者的差异是有意的。
ACCEPTED_FAILURES: dict[str, str] = {
    "F6": "构造性：单作者，第二作者转入 v3（两个 subject 都失败）",
    "F21b": "构造性：subject 总数不足 5+5（两个 subject 都失败）",
    "F13": "真实不足：ledger implicit 40% < 50%",
    "F17b": "正确的失败：ledger C 轴只覆盖 2/5 个 relation",
    "F18": "正确的失败：ledger 2 条 authority 降级无依据（缺陷 18）",
    "F21a": "正确的失败：ledger 有 5 个 relation，协议上限 3",
    "F24": "正确的失败：**billing** A 轴 SEH@1 = 1.0000（sample 上是通过）",
}


def _checks(name: str) -> list[dict[str, object]]:
    path = RESULTS / name
    if not path.exists():
        pytest.skip(f"{name} 缺失")
    payload = json.loads(path.read_text(encoding="utf-8"))
    return list(payload["checks"]) if isinstance(payload, dict) else list(payload)


@pytest.mark.parametrize("dataset", ["v2-sample-gates.json", "v2-billing-gates.json"])
def test_no_unregistered_failure(dataset: str) -> None:
    """每个未通过项都必须已登记为"可接受的失败"。

    新增一条未登记的失败会让这条红——**这正是它的作用**：
    提醒你必须先写清"为什么这个失败是正确的"，再打 frozen tag。
    """
    failed = {c["code"] for c in _checks(dataset) if not c["passed"]}
    unregistered = failed - set(ACCEPTED_FAILURES)

    assert not unregistered, (
        f"{dataset} 有未登记的失败：{sorted(unregistered)}。"
        "若它是「正确的失败」，先写进协议 §11.0.1 与本文件的 ACCEPTED_FAILURES"
    )


@pytest.mark.parametrize("code", sorted(ACCEPTED_FAILURES))
def test_accepted_failure_failed_in_v2_apparatus(code: str) -> None:
    """已登记的失败必须在**冻结的 v2 装置下**真的失败。

    **这条读的是冻结文件（`v2-*-gates.json`，`47e4785-dirty`），
    验的是"当年失败"，不是"现在失败"。**

    当前代码是 v3 装置，`F20`/`F24` 现在 `applicable=False`（跨装置，判据不成立），
    与"失败"是两件事。所以：

    | 来源 | `F20`/`F24` |
    |---|---|
    | 冻结文件（v2 装置） | `sample`：都通过；`billing`：`F20` 通过、`F24` 失败 |
    | 当前 `run_all()`（v3 装置） | 都 `applicable=False` |

    **两者的差异是有意的**，不是不一致：装置变了，判据的适用性也变了。

    若某条在**冻结文件里**变成通过（数据被改），这条会红——
    那时要确认"是不是为了让它通过而改了数据"。
    """
    sample = {c["code"]: c["passed"] for c in _checks("v2-sample-gates.json")}
    billing = {c["code"]: c["passed"] for c in _checks("v2-billing-gates.json")}

    if code not in sample and code not in billing:
        pytest.skip(f"{code} 不在任何一份门禁结果里")

    failures = []
    if code in sample and not sample[code]:
        failures.append("sample")
    if code in billing and not billing[code]:
        failures.append("billing")

    assert failures, (
        f"{code} 在冻结的 v2 装置下现在通过了——"
        "若是有意修复，请从 ACCEPTED_FAILURES 与协议 §11.0.1 里移除，"
        "并说明改了什么。"
        "\n注意：本测试读冻结文件，与当前 v3 装置的判定**无关**。"
    )


def test_protocol_lists_all_accepted_failures() -> None:
    """协议 §11.0.1 必须列出全部 6 条，与测试清单一致。"""
    if not PROTOCOL.exists():
        pytest.skip("协议缺失")

    text = PROTOCOL.read_text(encoding="utf-8")
    section = text.split("### 11.0.1")[1].split("### 11.0.2")[0]

    for code in ACCEPTED_FAILURES:
        assert f"**{code}**" in section or f"| {code} |" in section, (
            f"协议 §11.0.1 未列出 {code}"
        )


def test_protocol_states_three_categories() -> None:
    """三类失败必须都有定义，且写明哪些不能修。"""
    text = PROTOCOL.read_text(encoding="utf-8")
    section = text.split("### 11.0.1")[1].split("### 11.0.2")[0]

    assert "构造性" in section
    assert "正确的失败" in section
    assert "真实不足" in section
    # 关键：正确的失败不能修
    assert "不修" in section or "禁止" in section


def test_protocol_explains_tag_semantics() -> None:
    """tag message 的含义必须写明：frozen ≠ 合格。"""
    text = PROTOCOL.read_text(encoding="utf-8")
    section = text.split("### 11.0.2")[1]

    assert "不是" in section and "合格" in section
    # 与 C4 的区别
    assert "C4" in section
    assert "反面证据" in section or "正面证据" in section


def test_gates_results_carry_fingerprint() -> None:
    """门禁结果也必须有指纹——它也是数字，也要能复算。

    原先 `v2-*-gates.json` 只写一个裸 list，没有 `code_version`。
    后果："21/27 是在哪个代码版本上跑的"无法验证，
    与消融文件曾经的问题同型。
    """
    for name in ("v2-sample-gates.json", "v2-billing-gates.json"):
        path = RESULTS / name
        if not path.exists():
            pytest.skip(f"{name} 缺失")
        payload = json.loads(path.read_text(encoding="utf-8"))

        assert isinstance(payload, dict), f"{name} 仍是裸 list，没有指纹"
        assert payload.get("code_version"), f"{name} 缺 code_version"
        assert payload.get("code_diff_hash"), f"{name} 缺 code_diff_hash"
        assert payload.get("checks"), f"{name} 缺 checks"
