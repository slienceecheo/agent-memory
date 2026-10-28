"""条件消融：A 轴测的是"区分"，不是"召回"。

**这是本样例里最有说服力的一个实验**，因为它是零改动的：
把全部查询的 `query_condition` 置空，重跑三路。

结果（`results/v2-sample-condition-ablation.json`）：

| 指标 | 有 condition | 消融后 | 掉幅 |
|---|---|---|---|
| A 轴 `SEH@1` | 0.9000 | 0.3000 | **+0.6000** |
| implicit `SEH@1` | 0.7500 | 0.0000 | +0.7500 |
| explicit `SEH@1` | 1.0000 | 0.5000 | +0.5000 |

`never_recalled` 两种配置下都是 0——**变的是名次，不是召回**。

若没有这个实验，`0.9000` 会被读成"能召回 gold"；
而消融证明它是"能靠 condition 排到第 1"。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
ABLATION = ROOT / "results" / "v2-sample-condition-ablation.json"


def _load() -> dict[str, object]:
    if not ABLATION.exists():
        pytest.skip("条件消融结果缺失，先跑 evals.tools.ablate_condition")
    return json.loads(ABLATION.read_text(encoding="utf-8"))


def test_condition_contributes_to_axis_a() -> None:
    """F20：A 轴 `SEH@1` 的掉幅必须 ≥ 0.3。"""
    payload = _load()

    assert payload["axis_a_seh1_with"] == pytest.approx(0.9, abs=1e-4)
    assert payload["axis_a_seh1_without"] == pytest.approx(0.3, abs=1e-4)
    assert payload["drop"] == pytest.approx(0.6, abs=1e-4)
    assert payload["passed"] is True


def test_ablation_changes_ranks_not_recall() -> None:
    """**核心证据**：消融后没有一条变成 None。

    说明三路召回在两种配置下都能找到 gold——变的只是名次。
    这是"A 轴测区分而非召回"的直接证明。
    """
    payload = _load()

    assert payload["never_recalled_with"] == 0
    assert payload["never_recalled_without"] == 0


def test_implicit_depends_on_condition_entirely() -> None:
    """implicit 的 `SEH@1` 消融后归零——它们完全依赖 condition。"""
    payload = _load()

    assert payload["implicit_with"] == pytest.approx(0.75, abs=1e-4)
    assert payload["implicit_without"] == pytest.approx(0.0, abs=1e-4)


def test_explicit_drops_but_not_to_zero() -> None:
    """explicit 也掉，但**掉不到零**——它们有时能靠 base 分排第 1。

    这一条更正了一个曾写进对话的推断：「explicit 只有 33% 依赖 condition」。
    实测是 3/6 变化、`SEH@1` 从 1.0000 掉到 0.5000。
    """
    payload = _load()

    assert payload["explicit_with"] == pytest.approx(1.0, abs=1e-4)
    assert payload["explicit_without"] == pytest.approx(0.5, abs=1e-4)


def test_seven_cases_change() -> None:
    """7 条变化：4 条 implicit + 3 条 explicit。

    具体是 q1/q2/q5（explicit）与 q3/q4/q7/q8（implicit）。
    """
    payload = _load()
    changed = set(payload["changed"])  # type: ignore[arg-type]

    assert len(changed) == 7
    assert {"ledger-q3", "ledger-q4", "ledger-q7", "ledger-q8"} <= changed
    assert {"ledger-q1", "ledger-q2", "ledger-q5"} <= changed
