"""result-side 门禁的"适用域"登记（不是"缺陷"）。

**为什么不是"缺陷"**：这 6 条门禁（L6b / L8 / L6c / F19b / F20 / F24）读的是
`results/` 里**冻结的历史产物**，而不是当前装置的重跑结果：

| 门禁 | 读的文件 | 指纹 |
|---|---|---|
| L6b / L8 | `a3-with-dedup.json` | `899e2b6-dirty` |
| L6c | `a3-lexical-vector-adjacency.json` | `899e2b6-dirty` |
| F19b / F20 | `v2-*-condition-ablation.json` | `47e4785-dirty` |
| F24 | `v2-*-lexical-vector-adjacency.json` | `47e4785-dirty` |

而当前代码是 `0fbc3d2-dirty`。**没有一条读过当前装置的产物。**

这不是错——历史产物必须能被历史门禁检验。错的是**读者会以为**这 6 条在测当前装置。

**所以本文件做两件事**：

1. 把这个"适用域"写成可执行的断言（不是文档）
2. 让它**在有人重跑那些文件时自动失效**——那时这条登记必须被重核

**为什么用 `code_fingerprint()` 比对而不是硬编码版本号**：
硬编码会在有人改代码后失效，而"文件是否是当前装置产的"这个判据
必须跟着代码走。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
RESULTS = ROOT / "results"

# 6 条 result-side 门禁 -> 它们读的文件模式。
# **与 check_v2_dataset.py 的实际读法一一对应**，不是凭印象列的。
RESULT_SIDE_GATES: dict[str, tuple[str, ...]] = {
    "L6b": ("a3-with-dedup.json",),
    "L8": ("a3-with-dedup.json",),
    "L6c": ("a3-lexical-vector-adjacency.json",),
    "F19b": ("v2-*-condition-ablation.json",),
    "F20": ("v2-*-condition-ablation.json",),
    "F24": ("v2-*-lexical-vector-adjacency.json",),
}


def _current_fingerprint() -> tuple[object, object]:
    from evals.run_retrieval import code_fingerprint

    fp = code_fingerprint()
    return fp.get("code_version"), fp.get("code_diff_hash")


def test_result_side_gates_read_only_stale_artifacts() -> None:
    """6 条 result-side 门禁读的都是**旧装置**产物——这不是缺陷，是适用域。

    **判据**：它们读的每个结果文件的 `(code_version, code_diff_hash)` 都不等于
    当前代码的指纹。

    **这条会在有人重跑那些文件时红**——那时 F20/F24 的"不适用"登记要重核，
    而不是继续沿用"门禁在测当前装置"这个假设。
    """
    current = _current_fingerprint()
    same_as_current: list[str] = []
    missing: list[str] = []

    for gate, patterns in RESULT_SIDE_GATES.items():
        found = False
        for pattern in patterns:
            for path in sorted(RESULTS.glob(pattern)):
                found = True
                data = json.loads(path.read_text(encoding="utf-8"))
                fp = (data.get("code_version"), data.get("code_diff_hash"))
                if fp == current:
                    same_as_current.append(f"{gate} -> {path.name}")
        if not found:
            missing.append(f"{gate} -> {patterns}")

    assert not missing, (
        f"这些门禁读的文件一个都不存在：{missing}。"
        "文件被删/改名时，这条登记必须重核，而不是静默通过。"
    )
    assert not same_as_current, (
        f"这些门禁读的文件已经是**当前装置**的产物：{same_as_current}。\n"
        "本文件登记的前提（'result-side 门禁只读历史产物'）已失效——\n"
        "重核 F20/F24 在 v3 下的适用性，而不是继续沿用旧结论。"
    )


def test_result_side_gate_count_is_six() -> None:
    """**必须是 6 条**，不是 5 条。

    只登记 F20 会给读者"只有一个门禁有这问题"的错误印象。
    F24 是同一机制的更危险形态（它会**反向变绿**：A 轴 SEH@1 不饱和
    恰恰可能说明排序没生效，而门禁报 passed）。
    """
    assert len(RESULT_SIDE_GATES) == 6, sorted(RESULT_SIDE_GATES)

    # 与源码实际定义的 check 对应，防"清单漏一条"
    source = (ROOT / "evals" / "tools" / "check_v2_dataset.py").read_text(
        encoding="utf-8"
    )
    for gate in RESULT_SIDE_GATES:
        needle = '"' + gate + '"'
        assert needle in source, f"{gate} 在 check_v2_dataset.py 里不存在"


def test_v3_is_blind_to_condition_ablation() -> None:
    """**v3 下 condition 消融对名次的影响为 0**——这是设计结果，不是缺陷。

    这条锁住的是：`evaluate` 的 `condition` 参数在 v3 下**完全不影响排序**。
    所以 F20 的"掉幅"在 v3 上必然为 0，而 F20 读的是 v2 的 0.600——
    **两者测的不是同一件事**。

    判据用真实重跑，不是读 v2 文件。
    """
    from evals.datasets.retrieval_v2 import load_dataset
    from evals.datasets.v2_adapter import rows as adapt_rows
    from evals.run_retrieval import evaluate

    from memory.retrieval.pool_modes import PoolMode

    data = ROOT / "data" / "retrieval-v2" / "billing"
    if not data.exists():
        pytest.skip("billing 数据集缺失")

    rows = adapt_rows(load_dataset(data))
    specs = [r["gold"] for r in rows if r["gold"]]

    def run(ablate: bool) -> dict[str, object]:
        prepared = [dict(r, condition=None) for r in rows] if ablate else rows
        return evaluate(
            prepared,
            all_specs=specs,
            weights_name="uniform",
            enable_dedup=False,
            judge=None,
            k=5,
            pool_mode=PoolMode.UNRELATED,
            paths=("lexical",),
        )

    with_c = run(ablate=False)
    without_c = run(ablate=True)

    ranks_w = {c["case_id"]: c["rank_after_rerank"] for c in with_c["per_case"]}
    ranks_wo = {c["case_id"]: c["rank_after_rerank"] for c in without_c["per_case"]}

    diff = [k for k in ranks_w if ranks_w[k] != ranks_wo.get(k)]
    assert diff == [], (
        f"v3 下 condition 消融改变了名次：{diff}。\n"
        "condition 已退出加权，消融不该有任何影响——"
        "若这条红，说明 condition 又回到了排序里。"
    )
