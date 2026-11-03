"""`F24` 的分母必须是"已评分 A"，不是"全部 A 标注"（tasks 4.1 / 4.3 / 4.4）。

**缺陷**：`check_v2_dataset.py:1022-1027`

```python
dataset_a = {q.query_id for q in dataset.queries if q.axis is _Axis.A}
ranks = {c["case_id"]: c["rank_after_rerank"] for c in cases}
hit = sum(1 for qid in dataset_a if ranks.get(qid) == 1)
ratio = hit / len(dataset_a)
```

`ranks.get(qid)` 对**未评分**（池不足 K 被 skip）的 case 返回 `None`，
`== 1` 为 False —— **算作未命中，但仍留在分母里。**

实测：

| 文件 | A 标注 | 已评分 | hit | F24 口径 | 正确口径 |
|---|---|---|---|---|---|
| `v2-sample-lexical.json` | 10 | **6** | 6 | **0.6000** | **1.0000** |
| `v2-billing-lexical.json` | 9 | **7** | 7 | **0.7778** | **1.0000** |
| `v2-sample-threeway.json` | 10 | 10 | 9 | 0.9000 | 0.9000 |
| `v2-billing-lexical-vector-adjacency.json` | 9 | 9 | 9 | 1.0000 | 1.0000 |

**为什么必须用单路文件测**：`F24` 只 `glob` 三路文件，而三路的已评分数
恰好等于 A 标注总数——**所以 F24 永远发现不了自己的低报。**

**A 轴必须从数据集的 `axis` 字段读，不能从 case_id 前缀猜**：
实测 `sample` 的 A 轴是 `ledger-q1..q10`、C 轴是 `ledger-q11/q12`——
`-q` 前缀**不能**区分 A/C。按前缀判会把 2 条 C 轴算进 A 轴。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
RESULTS = ROOT / "results"
DATA = ROOT / "data" / "retrieval-v2"


def _axis_a_ids(subject: str) -> set[str]:
    """从**数据集**读 A 轴 query id（唯一权威来源）。"""
    from evals.datasets.retrieval_v2 import Axis, load_dataset

    ds = load_dataset(DATA / subject)
    return {q.query_id for q in ds.queries if q.axis is Axis.A}


def _seh1_scored(payload: dict, a_ids: set[str]) -> tuple[float, int, int]:
    """正确口径：分母 = 已评分的 A 轴 case。"""
    cases = payload.get("per_case") or []
    ranks = {c["case_id"]: c["rank_after_rerank"] for c in cases}
    scored = [qid for qid in a_ids if ranks.get(qid) is not None]
    hit = sum(1 for qid in scored if ranks[qid] == 1)
    return (hit / len(scored) if scored else 0.0), hit, len(scored)


def _seh1_all_a(payload: dict, a_ids: set[str]) -> tuple[float, int, int]:
    """F24 当前口径：分母 = 全部 A 标注（未评分算未命中）。"""
    cases = payload.get("per_case") or []
    ranks = {c["case_id"]: c["rank_after_rerank"] for c in cases}
    hit = sum(1 for qid in a_ids if ranks.get(qid) == 1)
    return (hit / len(a_ids) if a_ids else 0.0), hit, len(a_ids)


def test_a_axis_ids_come_from_dataset_not_prefix() -> None:
    """**前提**：A 轴 id 不能从 case_id 前缀推断。

    实测 `sample` 的 A 轴是 `ledger-q1..q10`，C 轴是 `ledger-q11/q12`——
    两者都以 `-q` 开头。按前缀判会把 C 轴算进 A 轴，那会让分母多 2。
    """
    a_ids = _axis_a_ids("sample")

    assert "ledger-q1" in a_ids
    assert "ledger-q11" not in a_ids, "C 轴被算进了 A 轴——前缀判据不可靠"
    assert len(a_ids) == 10


def test_single_path_seh1_is_not_underreported() -> None:
    """**核心**：单路文件 `v2-sample-lexical.json` 的正确口径 == 1.0000。

    当前 F24 口径给出 **0.6000**（6/10），因为 4 条未评分的 case 被算成未命中。
    正确值是 **6/6 = 1.0000**。

    **这条是唯一能抓低报的断言**：F24 只读三路文件，而三路分母恰好正确。
    """
    p = RESULTS / "v2-sample-lexical.json"
    if not p.exists():
        pytest.skip("样例结果缺失")

    payload = json.loads(p.read_text(encoding="utf-8"))
    a_ids = _axis_a_ids("sample")

    wrong_ratio, wrong_hit, wrong_n = _seh1_all_a(payload, a_ids)
    right_ratio, hit, scored = _seh1_scored(payload, a_ids)

    # 先确认缺陷存在（否则这条测试什么也没证明）
    assert wrong_n > scored, (
        f"A 标注 {wrong_n} 条，已评分 {scored} 条——两者相等时看不出缺陷。"
        "若它们相等，这条测试无法证明低报。"
    )

    assert right_ratio == pytest.approx(1.0), (
        f"单路文件正确口径 = {right_ratio:.4f}（{hit}/{scored}），应为 1.0000。"
    )
    assert wrong_ratio == pytest.approx(hit / wrong_n), (
        f"F24 当前口径 = {wrong_ratio:.4f}（{wrong_hit}/{wrong_n}）"
    )
    assert wrong_ratio < right_ratio, (
        "当前口径没有低报——那说明缺陷不存在，本变更的前提要重核"
    )


def test_single_path_billing_seh1_is_not_underreported() -> None:
    """同样的问题在 `billing` 单路上：0.7778 -> 1.0000。"""
    p = RESULTS / "v2-billing-lexical.json"
    if not p.exists():
        pytest.skip("billing 结果缺失")

    payload = json.loads(p.read_text(encoding="utf-8"))
    a_ids = _axis_a_ids("billing")

    wrong_ratio, _, wrong_n = _seh1_all_a(payload, a_ids)
    right_ratio, hit, scored = _seh1_scored(payload, a_ids)

    assert wrong_n > scored
    assert right_ratio == pytest.approx(1.0), (
        f"billing 单路正确口径 = {right_ratio:.4f}（{hit}/{scored}），应为 1.0000"
    )
    assert wrong_ratio < right_ratio


@pytest.mark.parametrize(
    ("subject", "name", "expected"),
    [
        ("sample", "v2-sample-threeway.json", 0.9),
        ("billing", "v2-billing-lexical-vector-adjacency.json", 1.0),
    ],
)
def test_threeway_numbers_unchanged(subject: str, name: str, expected: float) -> None:
    """**回归**：三路文件的数字必须不变（分母恰好等于已评分）。

    这三路的已评分数 == A 标注总数，所以改分母不影响它们。
    若这条红，说明修改误伤了正确的情形。
    """
    p = RESULTS / name
    if not p.exists():
        pytest.skip(f"{name} 缺失")

    payload = json.loads(p.read_text(encoding="utf-8"))
    a_ids = _axis_a_ids(subject)

    wrong_ratio, _, wrong_n = _seh1_all_a(payload, a_ids)
    right_ratio, _hit, scored = _seh1_scored(payload, a_ids)

    # 前提：分母恰好相等
    assert wrong_n == scored, (
        f"{name}: A 标注 {wrong_n} 条，已评分 {scored} 条——"
        "两者不等时，这条回归测试的前提不成立"
    )
    assert right_ratio == pytest.approx(expected, abs=1e-9)
    assert wrong_ratio == pytest.approx(expected, abs=1e-9), "修前后应相同"


def test_empty_denominator_does_not_produce_nan() -> None:
    """全部 A 轴 case 都被跳过时，不能产生 NaN。"""
    a_ids = {"x-q1", "x-q2"}
    payload = {
        "per_case": [
            {"case_id": "x-q1", "rank_after_rerank": None},
            {"case_id": "x-q2", "rank_after_rerank": None},
        ]
    }

    ratio, hit, scored = _seh1_scored(payload, a_ids)
    assert scored == 0
    assert hit == 0
    assert ratio == 0.0, f"空分母得到 {ratio!r}，应为 0.0"
