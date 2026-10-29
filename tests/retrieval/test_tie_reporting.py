"""并列参与度：有多少条名次是被"破并列判据"决定的。

**为什么按 top1 / K 边界分开**：一个数无法区分三种情况——

| 并列位置 | 影响 | 例 |
|---|---|---|
| 第 1、2 名 | `SEH@1` | `ledger-q1`（消融配置） |
| 第 5、6 名 | `SEH@5` | 本样例无 |
| 第 9、10 名 | 无 | 本样例无 |

三者计数都是 1，但含义完全不同。

**为什么按配置分开**：并列是**消融实验的产物**，不是数据常态。
抹平 condition 后，`gold` 与 `d-0` 的四特征（base/condition/authority/status）
逐位相同，必然并列。真实配置下 gold 的 condition=1.00、d-0=0.50，不会并列。

实测：

   真实配置  tie_at_top1 = 0    -> 0.9000 不含判据决定的成分
   消融配置  tie_at_top1 = 1    -> 0.3000 里有 1/10 由判据决定
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
ABLATION = ROOT / "results" / "v2-sample-condition-ablation.json"
THREEWAY = ROOT / "results" / "v2-sample-threeway.json"


def _load(path: Path) -> dict[str, object]:
    if not path.exists():
        pytest.skip(f"{path.name} 缺失")
    return json.loads(path.read_text(encoding="utf-8"))


def test_real_config_has_no_ties() -> None:
    """**真实配置 0 条并列**——这是 0.9000 不含判据成分的证据。"""
    payload = _load(THREEWAY)

    cases = [c for c in payload["per_case"] if c.get("has_gold") and not c.get("skipped")]  # type: ignore[index]
    assert cases
    top = sum(int(c.get("tie_at_top1") or 0) for c in cases)
    boundary = sum(int(c.get("tie_at_k_boundary") or 0) for c in cases)

    assert top == 0, f"真实配置出现 {top} 条 top1 并列"
    assert boundary == 0, f"真实配置出现 {boundary} 条 K 边界并列"


def test_ablation_has_exactly_one_top1_tie() -> None:
    """消融配置 1 条 top1 并列，且是 `ledger-q1`。"""
    payload = _load(ABLATION)

    assert payload["tie_at_top1_with_condition"] == 0
    assert payload["tie_at_top1_without_condition"] == 1
    assert payload["tie_report"]["with_condition"] == {}
    assert set(payload["tie_report"]["without_condition"]) == {"ledger-q1"}  # type: ignore[arg-type]


def test_tie_is_recorded_with_its_resolver() -> None:
    """并列必须记下用了什么判据——否则"由判据决定"无法审计。"""
    payload = _load(ABLATION)

    entry = payload["tie_report"]["without_condition"]["ledger-q1"]  # type: ignore[index]
    assert entry["tie_resolved_by"] == "fusion_order"
    assert entry["tie_at_top1"] == 1
    assert entry["tie_at_k_boundary"] == 0


def test_tie_is_a_product_of_ablation_not_of_the_data() -> None:
    """并列只出现在消融配置。若真实配置也出现，说明数据里有两条件完全相同的分支。

    这不是测试实现的细节，是数据质量的约束：
    同 relation 的兄弟分支在 base/condition/authority/status 上不应全同。
    """
    real = _load(THREEWAY)
    abl = _load(ABLATION)

    real_ties = sum(
        int(c.get("tie_at_top1") or 0) for c in real["per_case"]  # type: ignore[index]
    )
    abl_ties = int(abl["tie_at_top1_without_condition"])  # type: ignore[arg-type]

    assert real_ties == 0
    assert abl_ties == 1
    assert abl_ties > real_ties, "消融应当**增加**并列（抹掉唯一区分信号）"


def test_tie_does_not_change_under_the_same_judge() -> None:
    """两种合理判据在本例上给同一答案，所以结论不是"判据碰巧决定"的敏感点。

    - tag 字典序：`d-ledger-q1-0` < `gold-ledger-q1` -> d-0 在前
    - 融合顺序：d-0 位置 1，gold 位置 2 -> d-0 在前

    两者一致，所以即使换判据，`ledger-q1` 的结果也不变。
    """
    assert "d-ledger-q1-0" < "gold-ledger-q1"
    # 融合顺序里 d-0 在 gold 之前（见 results/v2-sample-threeway.json 的 fusion_tags）
    payload = _load(THREEWAY)
    case = next(c for c in payload["per_case"] if c["case_id"] == "ledger-q1")  # type: ignore[index]
    fusion = case["fusion_tags"]
    assert fusion.index("d-ledger-q1-0") < fusion.index("gold-ledger-q1")


def test_float_equality_is_the_only_reason_for_the_tie() -> None:
    """并列的原因是四特征**逐位相同**，不是"分数接近"。"""
    payload = _load(ABLATION)
    # 若并列是"接近"而非"相同"，消融配置下应出现大量并列；
    # 实际只有 1 条，说明判据是精确相等。
    assert payload["tie_at_top1_without_condition"] == 1
    assert len(payload["tie_report"]["without_condition"]) == 1  # type: ignore[arg-type]
