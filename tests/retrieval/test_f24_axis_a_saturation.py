"""F24：A 轴不得满分。协议 §7.1 只管了 `SEH@5` 饱和，漏了 `SEH@1`。

**两个 subject 给出相反的判定，这是本条门禁存在的理由**：

| subject | A 轴 `SEH@1` | 随机基线 | 判定 |
|---|---|---|---|
| `project:ledger` | 0.9000 | 0.3000 | 有区分空间 |
| `project:billing` | **1.0000** | 0.3333 | **失败** |

而 `SEH@1 = 1.0000` 比 `SEH@5 = 1.0000` 更严重：

| | 原因 | 性质 |
|---|---|---|
| `SEH@5` 饱和 | 池小于 K | **数学恒等**，与系统无关 |
| `SEH@1` 满分 | 数据太简单 | **测不到区分能力**，是实验设计失败 |

billing 的满分**不是装置问题**——逐条查过 gold 与第二名的加权总分差，
9 条全部为正（0.085–0.253），0 条并列。所以它反映真实能力，
而真实能力满分意味着这份数据没有难度。

根因：`condition_match` 命中给 1.0、不命中给 0.0，权重 0.25，
所以只要 base 分差 < 0.25，condition 命中就必然排第 1。
而同一 subject 同 relation 的分支 base 分天然接近（共享 subject/relation 词面）。
"""

from __future__ import annotations

from pathlib import Path

import pytest
from evals.datasets.retrieval_v2 import load_dataset
from evals.tools.check_v2_dataset import ALL_CHECKS, check_f24_axis_a_not_saturated

ROOT = Path(__file__).resolve().parents[2]
SAMPLE = ROOT / "data" / "retrieval-v2" / "sample"
BILLING = ROOT / "data" / "retrieval-v2" / "billing"


def test_f24_is_registered() -> None:
    assert "check_f24_axis_a_not_saturated" in {
        c.__name__ for c in ALL_CHECKS
    }


def test_f24_passes_on_ledger() -> None:
    """ledger 的 A 轴 SEH@1 = 0.9000，有区分空间。"""
    if not SAMPLE.exists():
        pytest.skip("样例数据集缺失")

    result = check_f24_axis_a_not_saturated(load_dataset(SAMPLE))

    assert result.code == "F24"
    assert result.passed, result.detail
    assert "0.3000" in result.detail


def test_f24_fails_on_billing() -> None:
    """**billing 的 A 轴 SEH@1 = 1.0000 —— 这是正确的失败。**

    它不是装置问题：0 条并列，gold 与第二名差距 0.085–0.253。
    所以失败的含义是"这份数据测不到区分能力"，不是"门禁写错了"。
    """
    if not BILLING.exists():
        pytest.skip("billing 数据集缺失")

    result = check_f24_axis_a_not_saturated(load_dataset(BILLING))

    assert result.code == "F24"
    assert not result.passed
    assert "1.0000" in result.detail
    assert "测不到区分能力" in result.detail


def test_f24_data_side_check_works_without_results(tmp_path: Path) -> None:
    """数据侧检查（随机基线）不依赖结果文件。

    F24 分两段：数据侧（随机基线 < 1.0）永远执行；
    结果侧（实测 SEH@1 不得满分）只在结果文件存在时执行。
    这保证合格性检查不依赖系统分数（协议 §1.1）。
    """
    if not SAMPLE.exists():
        pytest.skip("样例数据集缺失")

    dataset = load_dataset(SAMPLE)
    # 用 ceiling=0 让随机基线这一侧必然失败，证明它被执行了
    result = check_f24_axis_a_not_saturated(dataset, ceiling=0.0)

    assert not result.passed
    assert "随机基线" in result.detail


def test_billing_axis_a_has_no_ties() -> None:
    """**A 轴**的满分不是判据造成的——这是"真实能力"的前提。

    实测：billing 唯一一条并列在 `billing-c2`（**C 轴**），A 轴 0 条。
    所以 A 轴的 9/9 全部由分数差决定，不是判据。

    这条测试第一版写成了"全数据集 0 条并列"，跑出来是 1 条——
    但它同时暴露了 C 轴有一条并列，那本身也值得记。
    """
    path = ROOT / "results" / "v2-billing-lexical-vector-adjacency.json"
    if not path.exists():
        pytest.skip("billing 结果缺失")

    import json

    payload = json.loads(path.read_text(encoding="utf-8"))
    cases = [
        c for c in payload["per_case"]
        if c.get("has_gold") and not c.get("skipped")
    ]

    a_ties = [
        c["case_id"]
        for c in cases
        if c["case_id"].startswith("billing-a") and int(c.get("tie_at_top1") or 0)
    ]
    assert a_ties == [], f"A 轴出现并列：{a_ties}，满分可能来自判据"


def test_billing_only_tie_is_on_axis_c() -> None:
    """billing 唯一的并列在 C 轴，不在 A 轴。

    记录它，因为"并列在哪条轴"决定它影响哪个指标。
    """
    path = ROOT / "results" / "v2-billing-lexical-vector-adjacency.json"
    if not path.exists():
        pytest.skip("billing 结果缺失")

    import json

    payload = json.loads(path.read_text(encoding="utf-8"))
    tied = [
        c["case_id"]
        for c in payload["per_case"]
        if int(c.get("tie_at_top1") or 0)
    ]

    assert tied == ["billing-c2"], tied


def test_billing_condition_contribution_is_larger_than_ledger() -> None:
    """billing 的条件贡献 +0.7778 > ledger 的 +0.6000。

    这与"billing 的 A 轴几乎全靠 condition"一致，
    也解释了为什么它容易满分：抹掉 condition 后掉到 0.2222。
    """
    import json

    ledger = ROOT / "results" / "v2-sample-condition-ablation.json"
    billing = ROOT / "results" / "v2-billing-condition-ablation.json"
    if not ledger.exists() or not billing.exists():
        pytest.skip("消融结果缺失")

    led = json.loads(ledger.read_text(encoding="utf-8"))
    bil = json.loads(billing.read_text(encoding="utf-8"))

    assert bil["drop"] == pytest.approx(0.7778, abs=1e-3)
    assert led["drop"] == pytest.approx(0.6, abs=1e-3)
    assert bil["drop"] > led["drop"]
