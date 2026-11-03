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


def test_f24_passes_on_ledger(monkeypatch) -> None:
    """v2 装置下：ledger 的 A 轴 SEH@1 = 0.9000，有区分空间。

    **必须把装置设回 v2**：当前代码是 v3，F24 在 v3 下不适用
    （阈值语义随装置反转）。本条测的是 **v2 装置下 F24 的判据**，
    所以显式声明装置版本，而不是依赖全局默认。
    """
    if not SAMPLE.exists():
        pytest.skip("样例数据集缺失")

    import evals.tools.check_v2_dataset as module

    monkeypatch.setattr(module, "CURRENT_APPARATUS", "v2")

    result = check_f24_axis_a_not_saturated(load_dataset(SAMPLE))

    assert result.code == "F24"
    assert result.applicable, "v2 装置下 F24 应适用"
    assert result.passed, result.detail
    assert "0.3000" in result.detail


def test_f24_fails_on_billing(monkeypatch) -> None:
    """v2 装置下：**billing 的 A 轴 SEH@1 = 1.0000 —— 这是正确的失败。**

    它不是装置问题：0 条并列，gold 与第二名差距 0.085–0.253。
    所以失败的含义是"这份数据测不到区分能力"，不是"门禁写错了"。
    """
    if not BILLING.exists():
        pytest.skip("billing 数据集缺失")

    import evals.tools.check_v2_dataset as module

    monkeypatch.setattr(module, "CURRENT_APPARATUS", "v2")

    result = check_f24_axis_a_not_saturated(load_dataset(BILLING))

    assert result.code == "F24"
    assert result.applicable
    assert not result.passed
    assert "1.0000" in result.detail
    assert "测不到区分能力" in result.detail


def test_f24_data_side_check_works_without_results(
    tmp_path: Path, monkeypatch
) -> None:
    """数据侧检查（随机基线）不依赖结果文件。

    F24 分两段：数据侧（随机基线 < 1.0）永远执行；
    结果侧（实测 SEH@1 不得满分）只在结果文件存在时执行。
    这保证合格性检查不依赖系统分数（协议 §1.1）。

    **把装置设回 v2**：v3 下 F24 整体不适用，就测不到数据侧了。
    """
    if not SAMPLE.exists():
        pytest.skip("样例数据集缺失")

    import evals.tools.check_v2_dataset as module

    monkeypatch.setattr(module, "CURRENT_APPARATUS", "v2")

    dataset = load_dataset(SAMPLE)
    # 用 ceiling=0 让随机基线这一侧必然失败，证明它被执行了
    result = check_f24_axis_a_not_saturated(dataset, ceiling=0.0)

    assert result.applicable
    assert not result.passed
    assert "数据侧失败" in result.detail


def test_f24_detail_shows_both_stages(monkeypatch) -> None:
    """v2 装置下：**detail 必须分别写出数据侧与结果侧的结论。**

    否则读者无法判断"如果没跑评测，这条会是什么"。

    实测：`billing` 现在红，只因为结果文件存在。
    删掉 `v2-billing-lexical-vector-adjacency.json`，F24 会变绿（只跑数据侧）。
    **这个依赖必须可见。**
    """
    if not SAMPLE.exists():
        pytest.skip("样例数据集缺失")

    import evals.tools.check_v2_dataset as module

    monkeypatch.setattr(module, "CURRENT_APPARATUS", "v2")

    ledger = check_f24_axis_a_not_saturated(load_dataset(SAMPLE))
    assert ledger.applicable
    assert "[数据侧通过]" in ledger.detail
    assert "[结果侧" in ledger.detail

    if BILLING.exists():
        billing = check_f24_axis_a_not_saturated(load_dataset(BILLING))
        # 数据侧通过、结果侧失败——两段结论不同，必须都看得见
        assert "[数据侧通过]" in billing.detail
        assert "[结果侧失败]" in billing.detail
        assert not billing.passed


def test_f24_is_not_applicable_on_v3() -> None:
    """**当前装置是 v3 时，F24 必须不适用**——这是本变更的产出。

    它与上面三条（v2 装置下的行为）是互斥的两面：
    判据本身没变，变的是"在当前装置下它是否成立"。
    """
    if not SAMPLE.exists():
        pytest.skip("样例数据集缺失")

    from evals.tools.check_v2_dataset import CURRENT_APPARATUS

    assert CURRENT_APPARATUS == "v3", (
        f"当前装置是 {CURRENT_APPARATUS!r}，不是 v3——"
        "本条断言的场景不成立"
    )

    result = check_f24_axis_a_not_saturated(load_dataset(SAMPLE))
    assert not result.applicable
    assert not result.passed
    assert "v3" in result.detail


def test_f24_marks_result_side_as_not_run_when_no_file(tmp_path: Path) -> None:
    """没有结果文件时，**不能算通过**。

    **这条改动了一个旧断言**：旧版最后一行是 `assert result.passed`，
    理由当时是"没跑结果侧不等于失败"。

    **那个理由混淆了两件事**：
    - "数据侧通过、结果侧没跑" 与 "两侧都通过"，旧实现都得到 `passed=True`
    - 于是"门禁没跑"伪装成"执行过"

    实测过：v3 产物按 spec 放进 `results/v3/` 时，旧实现因 glob 写死顶层
    而读不到，于是 `passed=True`——**数据造好了，门禁却报告通过**。

    现在的判据：`applicable=False` + `passed=False`，并写明"这代还没有数据"。
    """
    if not SAMPLE.exists():
        pytest.skip("样例数据集缺失")

    import evals.tools.check_v2_dataset as mod

    empty = tmp_path / "results"
    empty.mkdir()
    dataset = load_dataset(SAMPLE)

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(mod, "ROOT", tmp_path)
        result = mod.check_f24_axis_a_not_saturated(dataset)

    assert "[数据侧通过]" in result.detail
    assert "结果目录里没有任何三路产物" in result.detail
    assert "还没有数据" in result.detail

    # **不能算通过**
    assert not result.passed, (
        f"没有结果文件却 passed=True：{result.detail}。"
        "'门禁没跑'与'执行过并通过'必须分开。"
    )
    # 也不是"失败"——"这代没数据"是"不适用"
    assert not result.applicable


def test_f24_ran_but_no_scorable_case_is_not_passed(
    tmp_path: Path, monkeypatch
) -> None:
    """有文件、匹配本数据集，但 A 轴一条都没评分 -> 仍不算通过。

    这是第三态：`matched_subject=True` 但 `result_side_ran=False`。
    """
    import json

    import evals.tools.check_v2_dataset as mod
    from evals.datasets.retrieval_v2 import Axis

    dataset = load_dataset(SAMPLE)
    a_ids = {q.query_id for q in dataset.queries if q.axis is Axis.A}

    payload = {
        "per_case": [
            {
                "case_id": qid,
                "has_gold": True,
                "features": {"base": 1.0, "authority": 1.0, "status": 1.0},
                "condition_score": None,
                "rank_after_rerank": None,  # 全部未评分
            }
            for qid in a_ids
        ],
        "code_version": "9999999-dirty",
        "code_diff_hash": "a" * 64,
    }
    results = tmp_path / "results"
    results.mkdir()
    (results / "v3-sample-lexical-vector-adjacency.json").write_text(
        json.dumps(payload, ensure_ascii=False), encoding="utf-8"
    )

    monkeypatch.setattr(mod, "ROOT", tmp_path)
    check = mod.check_f24_axis_a_not_saturated(dataset)

    assert check.applicable, "这不是跨装置，也不是无数据"
    assert not check.passed, f"全部 A 轴未评分却 passed=True：{check.detail}"
    assert "未跑" in check.detail


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
