"""并列裁决这件事本身必须有测试锁住。

**为什么需要**：`SEH@1` 是二值指标，无法表达"同分"。
而当候选完全同分时，取值取决于次级判据——所以"判据是什么"必须可验证，
不能靠读代码猜。

实测证据：`billing-c2` 上 tag 字典序与融合顺序**恰好一致**，
所以那一例无法区分谁在生效。要证明融合顺序生效，
必须构造两者**相反**的用例。

**同时锁住一件事**：`rerank` 内部不再有并列判据。
它只按分数排（stable sort），并列保持输入顺序。
若有人在那里重新加一个 `item_id` 二级键，`test_ties_keep_input_order` 会红。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def _load(name: str) -> dict[str, object]:
    path = ROOT / "results" / name
    if not path.exists():
        pytest.skip(f"{name} 缺失")
    return json.loads(path.read_text(encoding="utf-8"))


def test_billing_c2_is_the_only_tie_and_it_is_unattributable() -> None:
    """`billing-c2` 是唯一并列，且两种判据给同一答案——无法归因。

    这条测试的价值是**记录不可归因这个事实**，而不是断言某个判据生效。
    """
    payload = _load("v2-billing-lexical-vector-adjacency.json")
    tied = [
        c["case_id"] for c in payload["per_case"] if int(c.get("tie_at_top1") or 0)
    ]

    assert tied == ["billing-c2"], tied

    case = next(c for c in payload["per_case"] if c["case_id"] == "billing-c2")
    fusion = case["fusion_tags"]

    # tag 字典序
    assert "d-billing-c2-3" < "gold-billing-c2"
    # 融合顺序——也指向 d-billing-c2-3 在前
    assert fusion.index("d-billing-c2-3") < fusion.index("gold-billing-c2")

    # 两者一致，所以无法从结果判断谁在裁决
    assert case["rerank_order_tags"][0] == "d-billing-c2-3"


def test_ledger_has_no_ties() -> None:
    """ledger 的 12 条全部无并列——所以它的数字不含判据成分。"""
    payload = _load("v2-sample-threeway.json")
    tied = [
        c["case_id"]
        for c in payload["per_case"]
        if int(c.get("tie_at_top1") or 0) or int(c.get("tie_at_k_boundary") or 0)
    ]

    assert tied == [], tied


def test_axis_c_tie_explains_part_of_its_failure() -> None:
    """**更正一条旧结论**：C 轴 0/3 里的 1 条由同分裁决决定，不是纯能力结果。

    `billing-c2` 的两条候选四特征完全同分。`SEH@1` 无法表达"同分"，
    所以这一条的 0 分来自"同分 + 次级判据"，不是"四特征判错了"。

    而 C 轴只有 3 条，所以 1 条 = 33% 的样本受判据影响。
    """
    payload = _load("v2-billing-lexical-vector-adjacency.json")
    c_cases = [
        c for c in payload["per_case"] if c["case_id"].startswith("billing-c")
    ]

    assert len(c_cases) == 3
    tied = [c for c in c_cases if int(c.get("tie_at_top1") or 0)]
    assert len(tied) == 1
    assert tied[0]["case_id"] == "billing-c2"


def test_rerank_has_no_internal_tiebreak() -> None:
    """`rerank` 的源码里不应再有 `item_id` 二级键。

    它曾经存在，但在实际调用路径里**永远被覆盖**——因为
    `run_retrieval` 拿到结果后会按 `fused_position` 重排。
    留着一个会被覆盖的判据会让读代码的人误以为它在起作用。
    """
    source = (ROOT / "src" / "memory" / "retrieval" / "rerank.py").read_text(
        encoding="utf-8"
    )

    assert "(-item.score, item.item_id)" not in source, (
        "rerank 又加回了 item_id 二级键——它会被调用方覆盖"
    )
    assert "key=lambda item: -item.score" in source


def test_rerank_docstring_states_it_does_not_resolve_ties() -> None:
    """`rerank` 必须写明"不提供并列裁决策略"，否则调用方会误判。"""
    source = (ROOT / "src" / "memory" / "retrieval" / "rerank.py").read_text(
        encoding="utf-8"
    )

    assert "不提供并列裁决策略" in source
    assert "保持输入顺序" in source
