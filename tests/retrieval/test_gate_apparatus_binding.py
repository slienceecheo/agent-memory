"""门禁的适用域（tasks 1.1 / 1.3 / 2.x）。

**为什么需要**：6 条 result-side 门禁读的是历史产物，而报告把它们的 `passed`
计入"当前装置 21/27"。实测 6 条读的文件指纹分别是 `899e2b6-dirty` 与
`47e4785-dirty`，当前代码是 `fbc3d2-dirty`——**没有一条读过当前装置的产物。**

这不是"门禁错了"，是**适用域没被表达**。一个 v2 装置的门禁在 v3 装置下
当然还能算出 v2 的数字，但那个数字不回答"当前装置怎么样"。

**最危险的是 F24 会反向变绿**：

| 配置 | A 轴 SEH@1 | F24 判据(< 0.9999) | 真实含义 |
|---|---|---|---|
| v2 三路（冻结） | 1.0000 | **红**（满分=测不到区分） | 装置健康，指标饱和 |
| v3 单路（实测） | 0.8333 | **绿** | **排序能力下降**，不是"不饱和" |

同一个门禁，两种装置下绿/红的意义相反。
"""

from __future__ import annotations

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
RESULTS = ROOT / "results"


# ---------- 1.1 签名只读 features 的存在性 ----------


def test_apparatus_signature_reads_features_presence() -> None:
    """有 `features` -> v3；无 -> v2。**只看键的存在性。**"""
    from evals.tools.check_v2_dataset import apparatus_signature

    v3 = {"per_case": [{"case_id": "a", "features": {"base": 1.0}}]}
    v2 = {"per_case": [{"case_id": "a"}]}

    assert apparatus_signature(v3) == "v3"
    assert apparatus_signature(v2) == "v2"


def test_apparatus_signature_ignores_weights_name() -> None:
    """`weights` 的字符串名区分不了装置——两代都可能叫 `uniform`。

    实测：v2 产物的 `weights` 是 `"uniform"`（字符串名），不是元组。
    所以"四权重 vs 三权重"在文件里**看不出来**，只有 `features` 是结构差异。
    """
    from evals.tools.check_v2_dataset import apparatus_signature

    same_name_v2 = {"weights": "uniform", "per_case": [{"case_id": "a"}]}
    same_name_v3 = {
        "weights": "uniform",
        "per_case": [{"case_id": "a", "features": {"base": 1.0}}],
    }

    assert apparatus_signature(same_name_v2) == "v2"
    assert apparatus_signature(same_name_v3) == "v3"


def test_apparatus_signature_ignores_code_version() -> None:
    """`code_version` 是 commit 号，每次提交都变，不能用来判装置。

    若用它，v3 有多个 commit 的结果时会被判成不同装置。
    """
    from evals.tools.check_v2_dataset import apparatus_signature

    a = {
        "code_version": "1111111-dirty",
        "code_diff_hash": "a" * 64,
        "per_case": [{"case_id": "a", "features": {"base": 1.0}}],
    }
    b = {
        "code_version": "9999999-dirty",
        "code_diff_hash": "b" * 64,
        "per_case": [{"case_id": "a", "features": {"base": 1.0}}],
    }

    assert apparatus_signature(a) == apparatus_signature(b) == "v3"


def test_apparatus_signature_handles_empty_per_case() -> None:
    """没有 `per_case` 时不能崩，也不能默认成某一代。"""
    from evals.tools.check_v2_dataset import apparatus_signature

    assert apparatus_signature({"per_case": []}) == "unknown"
    assert apparatus_signature({}) == "unknown"


# ---------- 1.3 验收 5：自检 ----------


def test_current_apparatus_is_v3() -> None:
    """**验收 5（自检）**：当前代码产出的结果必须被判为 `v3`。

    若这条红，说明签名函数把当前装置也判成"不适用"——
    那会让 6 条门禁全部静默变成"不适用"，而报告显示"已处置"。

    **用真实 `evaluate()` 产出一份 `per_case`**，不手写 dict：
    手写的 dict 只能证明签名函数会读 `features`，
    不能证明**当前代码真的会写出 `features`**。
    """
    from evals.datasets.retrieval_v2 import load_dataset
    from evals.datasets.v2_adapter import rows as adapt_rows
    from evals.run_retrieval import evaluate
    from evals.tools.check_v2_dataset import apparatus_signature

    from memory.retrieval.pool_modes import PoolMode

    data = ROOT / "data" / "retrieval-v2" / "billing"
    if not data.exists():
        pytest.skip("billing 数据集缺失")

    rows = adapt_rows(load_dataset(data))
    specs = [r["gold"] for r in rows if r["gold"]]
    result = evaluate(
        rows,
        all_specs=specs,
        weights_name="uniform",
        enable_dedup=False,
        judge=None,
        k=5,
        pool_mode=PoolMode.UNRELATED,
        paths=("lexical",),
    )

    payload = {"per_case": result["per_case"]}
    assert apparatus_signature(payload) == "v3", (
        "当前代码产出的结果被判成了非 v3。"
        "若签名函数或 evaluate 的字段名变了，6 条门禁会全部静默变成'不适用'。"
    )

    # 且 per_case 里确实有 features 键（不是靠 other 字段推理出来的）
    assert any("features" in c for c in result["per_case"]), (
        "per_case 里没有 features 键——签名函数不可能判对"
    )
