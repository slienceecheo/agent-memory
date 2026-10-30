"""两轴的有效特征数不同，指标必须分开算。

**为什么需要这组测试**：`ablate_condition` 原先只提取 A 轴指标。
C 轴的逐条 rank 一直在 `with_condition` / `without_condition` 里，但从未被算成指标。

补上之后得到一条独立结论：**C 轴不依赖 `condition`。**

| 轴 | `condition_match` 取值 | 有效特征数 |
|---|---|---|
| A | gold 1.00 / 兄弟 0.00 | **4** |
| C | 恒 0.50（`query_condition` 为空） | **3** |

所以两轴的分数**不可直接比较**——与"分母不同"是同一层的提醒。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
LEDGER = ROOT / "results" / "v2-sample-condition-ablation.json"
BILLING = ROOT / "results" / "v2-billing-condition-ablation.json"


def _load(path: Path) -> dict[str, object]:
    if not path.exists():
        pytest.skip(f"{path.name} 缺失")
    return json.loads(path.read_text(encoding="utf-8"))


def test_axis_c_metrics_are_extracted() -> None:
    """C 轴必须有 SEH@1、SEH@5、n、逐条 rank 四项。"""
    for path in (LEDGER, BILLING):
        payload = _load(path)
        for key in (
            "axis_c_seh1_with",
            "axis_c_seh1_without",
            "axis_c_seh5_with",
            "axis_c_seh5_without",
            "axis_c_n",
            "axis_c_ranks_with",
            "axis_c_ranks_without",
        ):
            assert key in payload, f"{path.name} 缺 {key}"


def test_axis_c_ablation_changes_nothing() -> None:
    """**C 轴消融前后逐条相同**——因为它的 `condition_match` 恒为 0.5。

    实测：
      ledger  q11=1, q12=1  ->  不变
      billing c1=2, c2=2, c3=3  ->  不变

    这说明 C 轴的失败与 condition 无关。billing 的 C 轴排到第 2、第 3，
    既不是第 1，也不是未召回——是**能力不足**的干净证据。
    """
    for path in (LEDGER, BILLING):
        payload = _load(path)
        assert payload["axis_c_ranks_with"] == payload["axis_c_ranks_without"], (
            f"{path.name}: C 轴消融改变了名次，说明它并非恒 0.5"
        )


def test_axis_c_seh1_and_seh5_split_the_verdict() -> None:
    """**billing 的 C 轴两个指标给出相反结论，这是本条测试的核心。**

    SEH@1 = 0/3  -> 读成"C 轴完全失败"
    SEH@5 = 3/3  -> 读成"C 轴完美"

    两者都对：系统能找到正确答案（排进前 5），但排不到第 1。
    只报一个会得出错误结论。
    """
    payload = _load(BILLING)

    assert payload["axis_c_n"] == 3
    assert payload["axis_c_seh1_with"] == pytest.approx(0.0, abs=1e-9)
    assert payload["axis_c_seh5_with"] == pytest.approx(1.0, abs=1e-9)
    # 逐条确认：没有一条排第 1，但都在前 5
    ranks = payload["axis_c_ranks_with"]
    assert all(r is not None for r in ranks.values())  # type: ignore[union-attr]
    assert all(r > 1 for r in ranks.values())  # type: ignore[union-attr]
    assert all(r <= 5 for r in ranks.values())  # type: ignore[union-attr]


def test_ledger_axis_c_is_perfect_and_billing_is_not() -> None:
    """两个 subject 的 C 轴能力不同，不能合并成一个数。"""
    led = _load(LEDGER)
    bil = _load(BILLING)

    assert led["axis_c_seh1_with"] == pytest.approx(1.0, abs=1e-9)
    assert bil["axis_c_seh1_with"] == pytest.approx(0.0, abs=1e-9)


def test_axis_c_sample_size_is_reported() -> None:
    """C 轴样本量必须随结果一起报——n=2 / n=3 不足以支撑统计结论。"""
    led = _load(LEDGER)
    bil = _load(BILLING)

    assert led["axis_c_n"] == 2
    assert bil["axis_c_n"] == 3
    # n 太小时，SEH@5 的"高于随机"没有统计意义
    assert led["axis_c_n"] < 10
    assert bil["axis_c_n"] < 10


def test_axis_a_and_axis_c_use_different_feature_counts() -> None:
    """A 轴的 condition 有区分度、C 轴恒 0.5——两轴分数不可直接比较。

    用 `ablate` 的语义验证：A 轴消融有掉幅，C 轴没有。
    """
    led = _load(LEDGER)
    bil = _load(BILLING)

    assert led["drop"] > 0.3, "A 轴应当依赖 condition"
    assert bil["drop"] > 0.3, "A 轴应当依赖 condition"

    for payload, label in ((led, "ledger"), (bil, "billing")):
        same = payload["axis_c_ranks_with"] == payload["axis_c_ranks_without"]
        assert same, f"{label}: C 轴不应当依赖 condition"
