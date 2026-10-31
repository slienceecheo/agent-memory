"""缺陷 22：spec 要求配对 bootstrap 区间，而检索评测从未产出过。

**spec 原文**（`openspec/specs/evaluation-harness/spec.md` 第 184–188 行）：

    ### Requirement: 检索质量的度量

    系统 SHALL 为检索任务提供 SEH@K、SRS 与四类失败归因，并 MUST 同时给出
    样本数与配对 bootstrap 区间。...

**实测**：

```
grep -n "bootstrap|interval|proportion_ci|paired" evals/run_retrieval.py
（空）
```

结果文件的顶层键里也没有任何区间字段：

```
['attribution', 'cases', 'code_diff_hash', ..., 'seh_at_k', 'srs', ...]
```

**所以这不是"v2 报告忘了写"，是"run_retrieval 从来不计算区间"。**

---

这条要求从 `retrieval-and-rerank` 归档时（`45f787d`，10-25）就存在，
而它要求的东西从未被实现。

**为什么这条比 C4 缺陷 7 更难发现**：

| | 缺陷 7 | 缺陷 22 |
|---|---|---|
| 偏差形态 | 单测说"三路已建成"，入口只接一路 | spec 的 MUST 说"要给区间"，实现没有 |
| 有无可检验差异 | 有（"只有一路"可 grep） | **无（没有任何测试断言"结果必须有区间"）** |
| 发现方式 | 人工对照代码 | **只能对照 spec 文本** |

**核心问题：spec 里的 MUST 没有对应的测试，所以它可以一直是假的。**

---

**修复后这条会红**。修复方式是 `run_retrieval` 调用
`memory.eval.bootstrap.proportion_ci` 并在结果里写 `seh_at_k_ci` / `srs_ci`。
届时翻面成"结果必须含区间字段"的正向断言。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SPEC = ROOT / "openspec" / "specs" / "evaluation-harness" / "spec.md"
RUNNER = ROOT / "evals" / "run_retrieval.py"
RESULTS = ROOT / "results"


@pytest.mark.locked_defect
def test_spec_still_requires_intervals() -> None:
    """前提：spec 仍要求"配对 bootstrap 区间"。

    若这条红，说明 spec 改了——那时本文件的其余断言要重新评估
    （可能是把要求降级了，也可能是把 Wilson 加为允许方法）。
    """
    assert SPEC.exists(), "spec 缺失"
    text = SPEC.read_text(encoding="utf-8")

    assert "配对 bootstrap 区间" in text, "spec 不再要求配对 bootstrap 区间"
    assert "MUST" in text


@pytest.mark.locked_defect
def test_runner_does_not_compute_intervals() -> None:
    """**缺陷 22 本体**：`run_retrieval` 不计算任何区间。

    修复后这条会红——届时改成"必须 import bootstrap 并写出区间字段"。
    """
    assert RUNNER.exists(), "run_retrieval 缺失"
    source = RUNNER.read_text(encoding="utf-8")

    markers = ("bootstrap", "proportion_ci", "paired_difference_ci", "interval")
    found = [m for m in markers if m in source]

    assert not found, (
        f"run_retrieval 里出现了 {found}——缺陷 22 可能已修复。"
        "请翻面成正向断言并更新缺陷清单"
    )


@pytest.mark.locked_defect
def test_results_have_no_interval_fields() -> None:
    """结果文件里没有任何区间字段。

    与上一条互补：前者查"算不算"，这条查"写不写"。
    """
    sample = RESULTS / "v2-sample-threeway.json"
    if not sample.exists():
        pytest.skip("结果文件缺失")

    payload = json.loads(sample.read_text(encoding="utf-8"))
    keys = set(payload.keys())

    interval_keys = {k for k in keys if "ci" in k.lower() or "interval" in k.lower()}
    assert not interval_keys, (
        f"结果文件里出现了区间字段 {interval_keys}——缺陷 22 可能已修复"
    )


@pytest.mark.locked_defect
def test_no_test_asserts_intervals_exist() -> None:
    """**根因**：没有任何测试断言"结果必须含区间"。

    所以 spec 的 MUST 可以一直是假的。修复时应当补这条断言。

    **排除本文件自身**：它含有那些字符串（用来检查别人有没有），
    不排除的话会把自己当成违规——又一次自指陷阱。
    """
    self_path = Path(__file__).resolve()
    violations: list[str] = []
    for path in (ROOT / "tests").rglob("*.py"):
        if path.resolve() == self_path:
            continue
        text = path.read_text(encoding="utf-8")
        if "seh_at_k_ci" in text or "srs_ci" in text:
            violations.append(str(path.relative_to(ROOT)))

    assert not violations, (
        f"已有测试断言区间字段：{violations}——缺陷 22 可能已修复"
    )


def test_handoff_and_report_record_the_gap() -> None:
    """HANDOFF 与 v2 报告都必须写明"本报告未满足 spec 第 187 行"。

    不补区间（那要重跑、违反 §1.2），但必须写明缺口。
    """
    handoff = ROOT / "docs" / "HANDOFF.md"
    report = ROOT / "docs" / "reports" / "v2-what-it-measures.md"

    assert handoff.exists() and report.exists()
    for path in (handoff, report):
        text = path.read_text(encoding="utf-8")
        assert "区间" in text, f"{path.name} 未记录区间缺口"
        assert "187" in text or "184" in text or "配对 bootstrap" in text, (
            f"{path.name} 未引用 spec 的具体行"
        )
