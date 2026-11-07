"""HANDOFF §0.0 的 v3 数字必须与实测一致（tasks 2.4c / 5.4）。

**为什么这些断言要读回文档**：此前三次"测试只写期望值字面量"的先例
（`locked_defect` 计数、算术复算、五类分布），文档改坏了测试仍然绿。
而 HANDOFF §0.0 是造 v3 数据前唯一会被人读的一节——**它错，数据就错**。

所以每条断言都是"文档里的数字" vs "从数据/实现算出来的数字"，
不是"文档里有这句话"。
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
HANDOFF = ROOT / "docs" / "HANDOFF.md"
DATA = ROOT / "data" / "retrieval-v2"


def _text() -> str:
    if not HANDOFF.exists():
        pytest.skip("HANDOFF 缺失")
    return HANDOFF.read_text(encoding="utf-8")


def _facts(subject: str) -> dict[str, list[int]]:
    """从数据集复算两轴的 `n_competitors`，**按派生轴分组**。

    **不能按标注分组**：`billing` 的 3 条 C 标注在池结构上都是 within，
    按标注分组会得 `merged`（A={2}、C={2}），而正确结论是 `single_axis`
    （不存在 cross 轴）。两者报告轴数都是 1，**数字相同、语义相反**。
    """
    from evals.run_retrieval import derive_axis

    mems = {
        m["memory_id"]: m
        for m in (
            json.loads(x)
            for x in (DATA / subject / "memories.jsonl")
            .read_text(encoding="utf-8")
            .splitlines()
            if x.strip()
        )
    }
    # `derive_axis_policy` 的入参键名是 A / C（历史原因），
    # 但这里传的是**派生**分组的结果，不是标注。
    by_axis: dict[str, list[int]] = {"A": [], "C": []}
    for q in (
        json.loads(x)
        for x in (DATA / subject / "queries.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
        if x.strip()
    ):
        gold = mems[q["gold_memory_id"]]
        pool = [m for k, m in mems.items() if k != q["gold_memory_id"]]
        n = sum(1 for m in pool if m.get("relation") == gold.get("relation"))
        axis = derive_axis(pool=pool, gold=gold)
        key = "A" if axis == "relation_within" else "C"
        by_axis[key].append(n)
    return by_axis


def test_handoff_states_v3_has_three_sort_features() -> None:
    """HANDOFF 必须写明排序特征是 3 个，且 `condition` 退出加权。"""
    text = _text()
    import dataclasses

    from memory.retrieval.rerank import RerankWeights

    fields = [f.name for f in dataclasses.fields(RerankWeights)]
    assert fields == ["base", "authority", "cosine"], fields

    assert "排序特征 = 3" in text, "HANDOFF 未写'排序特征 = 3'"
    assert "condition 退出加权" in text
    # 不能还留着"有效特征 A=3 / C=2"这种旧说法
    assert "A=3 / C=2" not in text, "HANDOFF 里还有旧的'有效特征 A=3 / C=2'"


def test_handoff_preregistered_count_matches_reality() -> None:
    """HANDOFF 里写的预注册组数必须等于 `PREREGISTERED_WEIGHTS` 的长度。

    **这一行漂移过，而且没有断言守着**（实测 git 历史）：

    | 提交 | 该行 | 现实 |
    |---|---|---|
    | `e8ca4f7~1`（加 cosine 前） | 四组 | uniform/base_heavy/auth_heavy/status_only |
    | `e8ca4f7`（加 cosine 后） | 三组 | uniform/mixed/cosine_only |
    | `drop-mixed-weight-alias` 之后 | 两组 | uniform/cosine_only |

    `e8ca4f7` 那次是**手动同步**的——若漏改，没有任何测试会红。

    **判据从 `len(PREREGISTERED_WEIGHTS)` 算，不从文档反推**：
    从文档反推等于用同一个数验证它自己。

    **比较的是"数值"，不是"字符串"**：文档用中文数字（"两组"），
    而初版断言写的是 `f"{n} 组"`（阿拉伯数字），于是它在文档**正确的**时候红了。
    那正是"匹配形态而非匹配值"——与它要防的问题同一类。
    现在把文档里的数字解析成 int 再比。

    **组名不由本条守**：组名由
    `test_preregistered_naming.py::test_preregistered_names_describe_questions` 守。
    本条只守"数字与长度一致"。
    """
    import re

    text = _text()
    from memory.retrieval.rerank import PREREGISTERED_WEIGHTS

    n = len(PREREGISTERED_WEIGHTS)

    # 文档用中文数字；解析成 int 再比，不比字面
    # **字符类必须含 `两`**：初版写的是 `[一二三四五六七八九十]`，
    # 而文档用的是"两组"不是"二组"——于是正则在文档**正确的**时候匹配不上。
    # 这又是一次"匹配形态而非匹配值"。
    cn = {
        1: "一", 2: "两", 3: "三", 4: "四", 5: "五",
        6: "六", 7: "七", 8: "八", 9: "九", 10: "十",
    }
    cn_rev = {v: k for k, v in cn.items()}
    cn_rev["二"] = 2  # 兼容"二组"写法
    pattern = r"`PREREGISTERED_WEIGHTS`\s*(\d+|[一二两三四五六七八九十])\s*组"
    m = re.search(pattern, text)

    assert m is not None, (
        "HANDOFF 里找不到 '`PREREGISTERED_WEIGHTS` N 组' 这句话。\n"
        f"实际有 {n} 组：{sorted(PREREGISTERED_WEIGHTS)}"
    )

    token = m.group(1)
    written = int(token) if token.isdigit() else cn_rev[token]

    assert written == n, (
        f"HANDOFF 写的是 {token} 组（{written}），而实际有 {n} 组："
        f"{sorted(PREREGISTERED_WEIGHTS)}。\n"
        "这一行曾漂移而无人发现，所以现在有断言守着。"
    )


def test_handoff_billing_policy_is_single_axis() -> None:
    """HANDOFF 写的 `billing` policy 必须与实测一致（`single_axis`，不是 `merged`）。"""
    text = _text()
    from evals.run_retrieval import derive_axis_policy

    facts = _facts("billing")
    policy = derive_axis_policy(facts)
    assert policy == "single_axis", f"实测 billing 应为 single_axis，得 {policy}"

    assert "`billing` = **single_axis**" in text, (
        "HANDOFF 未写 '`billing` = **single_axis**'。"
        "写成 merged 会把'没有第二轴'说成'两轴合并'。"
    )

def test_handoff_ledger_policy_is_two_axes() -> None:
    """HANDOFF 写的 `ledger` policy 必须与实测一致（`two_axes`）。"""
    text = _text()
    from evals.run_retrieval import derive_axis_policy

    assert derive_axis_policy(_facts("sample")) == "two_axes"
    assert "`ledger` = two_axes" in text


def test_handoff_axis_label_mismatch_counts() -> None:
    """HANDOFF 的"标注与派生不一致 3/12"必须能从数据复算。

    `ledger` 0/12、`billing` 3/12。这条把两个数都验一遍——
    只验 `billing` 时，"全部不一致"的错误实现也能过。
    """
    text = _text()
    from evals.run_retrieval import derive_axis

    counts = {}
    for subject in ("sample", "billing"):
        mems = {
            m["memory_id"]: m
            for m in (
                json.loads(x)
                for x in (DATA / subject / "memories.jsonl")
                .read_text(encoding="utf-8")
                .splitlines()
                if x.strip()
            )
        }
        mism = 0
        total = 0
        for q in (
            json.loads(x)
            for x in (DATA / subject / "queries.jsonl")
            .read_text(encoding="utf-8")
            .splitlines()
            if x.strip()
        ):
            total += 1
            gold = mems[q["gold_memory_id"]]
            pool = [m for k, m in mems.items() if k != q["gold_memory_id"]]
            derived = derive_axis(pool=pool, gold=gold)
            labeled = (
                "relation_within" if q["axis"] == "A" else "relation_cross"
            )
            if derived != labeled:
                mism += 1
        counts[subject] = (mism, total)

    assert counts["sample"] == (0, 12), counts
    assert counts["billing"] == (3, 12), counts

    # 文档里 `**3/12**` 加粗、`0/12` 未加粗。**按实际写法断言**，
    # 但两个数字都必须出现——只验一个时"全部不一致"的错误实现也能过。
    assert "**3/12**" in text, "HANDOFF 未写加粗的 3/12"
    assert "0/12" in text, "HANDOFF 未写 ledger 的 0/12"


def test_handoff_f21a_constraint_is_stated() -> None:
    """HANDOFF 必须写明 F21a 与 cross 轴的冲突，且方向是"改造"不是"新增"。"""
    text = _text()

    assert "F21a" in text
    assert re.search(r"relation 数 ∈ \[2, 3\]", text), "未写 F21a 的区间"
    assert "新增第 4 个单值 relation" in text
    assert "F21a 由绿变红" in text
    assert "把 3 个多分支中的 1 个改成单值" in text


def test_handoff_v3_results_zone() -> None:
    """HANDOFF 必须写明 v3 产物在 `results/v3/`，且顶层永远 48 个。"""
    text = _text()
    assert "`results/v3/`" in text
    assert "永远 48 个" in text

    results = ROOT / "results"
    top = [p for p in results.glob("*.json") if p.parent == results]
    assert len(top) == 48, f"顶层实际 {len(top)} 个，HANDOFF 写 48"
