"""报告的三处限定必须存在且与数据一致。

**为什么需要**：这三处限定正是"五条结论看起来很干净"时最容易被丢掉的部分。

| # | 限定 | 丢掉会怎样 |
|---|---|---|
| 1 | 结论 1 的两种成因 | 会被读成"词面路径无效" |
| 2 | 结论 2 的 21/22 + 1/22 | 会被读成"四特征完全解释" |
| 3 | 结论 4 的 n=1 | 会被读成"大量样本支撑的结论" |

第 3 条最容易漏：`0.085` / `0.250` 两个数字很干净，
而支撑它们的样本是 "ledger 1 条 third_party、billing 0 条"。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
REPORT = ROOT / "docs" / "reports" / "v2-what-it-measures.md"


def _report() -> str:
    if not REPORT.exists():
        pytest.skip("报告缺失")
    return REPORT.read_text(encoding="utf-8")


def _load(name: str) -> dict[str, object]:
    path = ROOT / "results" / name
    if not path.exists():
        pytest.skip(f"{name} 缺失")
    return json.loads(path.read_text(encoding="utf-8"))


# ---------- 限定 1：词面"无增量"的两种成因 ----------


def test_report_gives_two_causes_for_axis_a() -> None:
    """结论 1 必须写清 ledger 与 billing 的成因不同。"""
    text = _report()

    assert "两种成因" in text or "成因不同" in text
    assert "词面太弱" in text
    assert "天花板" in text


def test_axis_a_numbers_match_two_different_causes() -> None:
    """数据必须支持"两种成因"这个说法。"""
    sys.path.insert(0, str(ROOT))
    from evals.datasets.retrieval_v2 import Axis, load_dataset

    def axis_a_hit(name: str, prefix: str) -> tuple[int, int]:
        payload = _load(name)
        ranks = {c["case_id"]: c["rank_after_rerank"] for c in payload["per_case"]}  # type: ignore[index]
        ds = load_dataset(ROOT / "data" / "retrieval-v2" / (
            "sample" if prefix == "ledger" else "billing"
        ))
        a_ids = [q.query_id for q in ds.queries if q.axis is Axis.A]
        return sum(1 for q in a_ids if ranks.get(q) == 1), len(a_ids)

    lex_led = axis_a_hit("v2-ledger-lexical.json", "ledger")
    vec_led = axis_a_hit("v2-ledger-vector.json", "ledger")
    both_led = axis_a_hit("v2-ledger-lexical-vector.json", "ledger")

    lex_bil = axis_a_hit("v2-billing-lexical.json", "billing")
    vec_bil = axis_a_hit("v2-billing-vector.json", "billing")
    both_bil = axis_a_hit("v2-billing-lexical-vector.json", "billing")

    # ledger：词面弱（6/10），向量 9/10，融合后 = 向量
    assert lex_led == (6, 10)
    assert vec_led == (9, 10)
    assert both_led == (9, 10)

    # billing：词面中等（7/9），向量满分（9/9），融合后 = 向量
    assert lex_bil == (7, 9)
    assert vec_bil == (9, 9)
    assert both_bil == (9, 9)

    # 两种成因：ledger 的 lex 弱于 vector 且都未满分；billing 的 vector 已满分
    assert both_led == vec_led < (10, 10)
    assert lex_bil != vec_bil and vec_bil == (9, 9)


def test_report_distinguishes_seh1_from_seh5() -> None:
    """报告必须注明 `0.6667` 是整池 `SEH@5`，不是 A 轴 `SEH@1`。

    这两个数字在历史记录里都出现过，混用会得出不同结论。
    """
    text = _report()

    assert "0.6667" in text
    assert "整池" in text or "SEH@5" in text
    # 明确说明不是同一件事
    assert "不是同一件事" in text or "口径" in text


# ---------- 限定 2：21/22 + 1/22 ----------


def test_report_keeps_21_of_22_split() -> None:
    text = _report()

    assert "21/22" in text
    assert "第 22 条" in text
    assert "0.5" in text  # 若同分算 0.5，贡献会变


# ---------- 限定 3：authority 的 n=1 ----------


def test_report_states_n_equals_one_for_third_party() -> None:
    """**最容易漏的一条**：`0.2500` 的临界值只有 1 条观测。"""
    text = _report()

    assert "n=1" in text or "n = 1" in text
    assert "算术上精确" in text
    assert "经验上" in text


def test_third_party_count_is_really_one() -> None:
    """数据必须支持 `n=1` 这个说法。"""
    sys.path.insert(0, str(ROOT))
    from evals.datasets.retrieval_v2 import Axis, load_dataset

    total = 0
    for name in ("sample", "billing"):
        ds = load_dataset(ROOT / "data" / "retrieval-v2" / name)
        for q in ds.queries:
            if q.axis is not Axis.A:
                continue
            gold = ds.memory(q.gold_memory_id)
            if gold.authority.value == "third_party":
                total += 1

    assert total == 1, f"third_party 的 A 轴 gold 实际有 {total} 条"


def test_user_document_count_is_three_and_none_dropped() -> None:
    """`user_document` 有 3 条且全部排第 1——这一档的经验支撑比 third_party 强。"""
    sys.path.insert(0, str(ROOT))
    from evals.datasets.retrieval_v2 import Axis, load_dataset

    ledger = _load("v2-sample-threeway.json")
    billing = _load("v2-billing-lexical-vector-adjacency.json")
    ranks = {
        c["case_id"]: c["rank_after_rerank"]
        for c in ledger["per_case"]  # type: ignore[index]
    }
    ranks.update(
        {
            c["case_id"]: c["rank_after_rerank"]
            for c in billing["per_case"]  # type: ignore[index]
        }
    )

    found: list[tuple[str, int | None]] = []
    for name in ("sample", "billing"):
        ds = load_dataset(ROOT / "data" / "retrieval-v2" / name)
        for q in ds.queries:
            if q.axis is not Axis.A:
                continue
            gold = ds.memory(q.gold_memory_id)
            if gold.authority.value == "user_document":
                found.append((q.query_id, ranks.get(q.query_id)))

    assert len(found) == 3, found
    assert all(rank == 1 for _, rank in found), found
