"""所有 v2 结果文件必须同指纹——包括消融结果。

**为什么需要**：这一路出现过两次"数字对不上却查不出原因"，
两次都是结果文件缺元数据：

| # | 现象 | 靠什么查清 |
|---|---|---|
| 1 | `{1:33}` vs `{1:29,2:4}` | `git log` + `run_count` |
| 2 | 11 份结果文件混三次代码状态 | `code_diff_hash` |

而**消融文件此前完全没有元数据**——连 `run_count` 都没有。
它的产出（`0.3000` / `0.6000` / `0.2222` / `0.7778`）被四条结论里的三条引用：

- 结论 2（A 轴 = base + condition）用 `0.3000` / `0.9000`
- 结论 4（authority 临界点）间接依赖
- F20 门禁用 `0.6000` 与阈值 `0.3` 比较

所以"0.3000 是哪个版本测的"必须可复算，否则"推翻旧解读"这件事本身无法被验证。

**历史文件例外**：`v2-sample-lexical.json` 与 `v2-sample-lexical-text.json`
是样例期的旧产物（`8b1b600-dirty`），保留作为历史证据，不参与统一。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
RESULTS = ROOT / "results"

# 必须统一指纹的当前有效结果
CURRENT = [
    "v2-ledger-lexical.json",
    "v2-ledger-vector.json",
    "v2-ledger-lexical-vector.json",
    "v2-ledger-vector-adjacency.json",
    "v2-ledger-lexical-vector-adjacency.json",
    "v2-sample-threeway.json",
    "v2-billing-lexical.json",
    "v2-billing-vector.json",
    "v2-billing-lexical-vector.json",
    "v2-billing-vector-adjacency.json",
    "v2-billing-lexical-vector-adjacency.json",
    "v2-sample-condition-ablation.json",
    "v2-billing-condition-ablation.json",
]

# 历史证据，不参与统一
HISTORICAL = [
    "v2-sample-lexical.json",
    "v2-sample-lexical-text.json",
]


def _load(name: str) -> dict[str, object]:
    path = RESULTS / name
    if not path.exists():
        pytest.skip(f"{name} 缺失")
    return json.loads(path.read_text(encoding="utf-8"))


def test_all_current_results_share_one_fingerprint() -> None:
    """**13 份当前结果必须同指纹**（11 份评测 + 2 份消融）。"""
    versions: set[str] = set()
    hashes: set[str] = set()

    for name in CURRENT:
        payload = _load(name)
        versions.add(str(payload.get("code_version")))
        hashes.add(str(payload.get("code_diff_hash")))

    assert len(versions) == 1, f"code_version 不统一：{versions}"
    assert len(hashes) == 1, f"code_diff_hash 不统一：{hashes}"
    assert None not in versions, "有文件没有 code_version"
    assert "None" not in hashes, "有文件没有 code_diff_hash"


def test_ablation_files_have_fingerprints() -> None:
    """消融文件必须有指纹与 `run_count`。

    这条测试此前会红——两份消融的 `code_version` 是 `None`。
    它是"补指纹"这个改动的验收标准。
    """
    for name in (
        "v2-sample-condition-ablation.json",
        "v2-billing-condition-ablation.json",
    ):
        payload = _load(name)
        assert payload.get("code_version"), f"{name} 缺 code_version"
        assert payload.get("code_diff_hash"), f"{name} 缺 code_diff_hash"
        assert payload.get("run_count"), f"{name} 缺 run_count"


def test_ablation_fingerprint_matches_result_files() -> None:
    """消融与评测必须用**同一个**指纹函数，所以值应当相同。

    两个工具各写各的指纹，就等于没有统一身份。
    """
    ablation = _load("v2-sample-condition-ablation.json")
    result = _load("v2-sample-threeway.json")

    assert ablation["code_version"] == result["code_version"]
    assert ablation["code_diff_hash"] == result["code_diff_hash"]


def test_historical_files_are_excluded_and_documented() -> None:
    """历史文件保留原指纹，且必须能从文件名看出是历史。

    `v2-sample-*` 是样例期产物。它们**不该**被重跑成新指纹，
    否则"补字段前后数字未变"就失去了对照物。
    """
    for name in HISTORICAL:
        payload = _load(name)
        assert payload.get("code_version") is not None
        # 不与当前版本相同
        current = _load("v2-sample-threeway.json")
        assert payload["code_version"] != current["code_version"], (
            f"{name} 被重跑成了当前版本，历史对照丢失"
        )


def test_supersedes_points_at_something_different() -> None:
    """`supersedes` 若存在，不得与当前指纹完全相同。

    完全相同的 `supersedes` 意味着"我覆盖了我自己"，没有信息量。
    """
    for name in CURRENT:
        payload = _load(name)
        old = payload.get("supersedes")
        if not isinstance(old, dict):
            continue
        same = (
            old.get("code_version") == payload.get("code_version")
            and old.get("code_diff_hash") == payload.get("code_diff_hash")
        )
        assert not same, f"{name} 的 supersedes 与当前完全相同"


def test_ablation_drop_values_are_stable() -> None:
    """补指纹不得改变任何数字。

    ledger  `drop = 0.6000`
    billing `drop = 0.7778`
    """
    led = _load("v2-sample-condition-ablation.json")
    bil = _load("v2-billing-condition-ablation.json")

    assert led["drop"] == pytest.approx(0.6, abs=1e-6)
    assert bil["drop"] == pytest.approx(0.7778, abs=1e-3)
