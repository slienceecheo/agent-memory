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

import json
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


# ---------- 1.4 签名必须真的接进判断 ----------


def _fake_ablation(dataset_ids: set[str], *, v3: bool) -> dict:
    """构造消融结果：v3 签名 = 两轴 rank 相同；v2 = 不同。"""
    if v3:
        ranks = {qid: 1 for qid in dataset_ids}
        return {
            "with_condition": ranks,
            "without_condition": dict(ranks),
            "drop": 0.0,
            "threshold": 0.30,
            "axis_a_seh1_with": 1.0,
            "axis_a_seh1_without": 1.0,
        }
    return {
        "with_condition": {qid: 1 for qid in dataset_ids},
        "without_condition": {qid: 2 for qid in dataset_ids},
        "drop": 0.6,
        "threshold": 0.30,
        "axis_a_seh1_with": 0.9,
        "axis_a_seh1_without": 0.3,
    }


def test_f20_actually_reads_the_signature(tmp_path: Path, monkeypatch) -> None:
    """**`F20` 必须真的比较签名，不能只看 `CURRENT_APPARATUS` 常量。**

    **这条防的形态**：`apparatus_signature` 写完了，但没有任何使用点。
    实测过：`CURRENT_APPARATUS == "v3"` 在常量恒为 "v3" 时永远为真，
    于是"不适用"变成无条件结论——**v3 数据造出来后 F20 仍永久不适用**。

    | 文件签名 | 当前装置 | 应有行为 |
    |---|---|---|
    | v3 | v3 | **执行**并断言掉幅 0 |
    | v2 | v3 | 不适用 |
    """
    from evals.datasets.retrieval_v2 import load_dataset
    from evals.tools.check_v2_dataset import (
        CURRENT_APPARATUS,
        apparatus_signature,
        check_f20_condition_contributes,
    )

    data = ROOT / "data" / "retrieval-v2" / "sample"
    if not data.exists():
        pytest.skip("sample 数据集缺失")
    ds = load_dataset(data)
    ids = {q.query_id for q in ds.queries}

    import evals.tools.check_v2_dataset as module

    monkeypatch.setattr(module, "ROOT", tmp_path)

    # 1) v3 签名的文件 -> 必须执行
    v3_payload = _fake_ablation(ids, v3=True)
    assert apparatus_signature(v3_payload) == CURRENT_APPARATUS, (
        "构造前提不成立：这份假文件应被判为当前装置"
    )
    results = tmp_path / "results"
    results.mkdir(exist_ok=True)
    (results / "v2-sample-condition-ablation.json").write_text(
        json.dumps(v3_payload, ensure_ascii=False), encoding="utf-8"
    )

    check = check_f20_condition_contributes(ds)
    assert check.applicable, (
        "同装置的文件却判'不适用'——说明判断只看常量，"
        "`apparatus_signature` 没有接进来。"
    )
    assert check.passed, check.detail
    assert "0.0000" in check.detail, (
        f"v3 下应断言掉幅为 0：{check.detail}"
    )

    # 2) v2 签名的文件 -> 必须不适用
    v2_payload = _fake_ablation(ids, v3=False)
    assert apparatus_signature(v2_payload) == "v2"
    (results / "v2-sample-condition-ablation.json").write_text(
        json.dumps(v2_payload, ensure_ascii=False), encoding="utf-8"
    )

    check = check_f20_condition_contributes(ds)
    assert not check.applicable, "跨装置的文件却执行了——签名比较失效"


def test_f20_rejects_nonzero_drop_on_v3(tmp_path: Path, monkeypatch) -> None:
    """v3 下掉幅不为 0 必须红——那说明 condition 又参与了加权。

    **这条是 v3 的 F20 判据**：不是"不适用"，是"掉幅必须为 0"。
    把 F20 永久关闭等于放弃这条断言。
    """
    from evals.datasets.retrieval_v2 import load_dataset
    from evals.tools.check_v2_dataset import check_f20_condition_contributes

    data = ROOT / "data" / "retrieval-v2" / "sample"
    if not data.exists():
        pytest.skip("sample 数据集缺失")
    ds = load_dataset(data)
    ids = {q.query_id for q in ds.queries}

    import evals.tools.check_v2_dataset as module

    monkeypatch.setattr(module, "ROOT", tmp_path)

    # v3 签名（rank 全部相同）但 drop 写成 0.6——矛盾文件
    payload = _fake_ablation(ids, v3=True)
    payload["drop"] = 0.6

    results = tmp_path / "results"
    results.mkdir(exist_ok=True)
    (results / "v2-sample-condition-ablation.json").write_text(
        json.dumps(payload, ensure_ascii=False), encoding="utf-8"
    )

    check = check_f20_condition_contributes(ds)
    assert check.applicable
    assert not check.passed, (
        "v3 下 drop=0.6 却通过了——v3 的 F20 判据没有生效。"
        "condition 若又参与加权，这条必须红。"
    )
    assert "不为 0" in check.detail


# ---------- 1.3 验收 5：自检 ----------

def test_current_apparatus_is_v3() -> None:
    """**验收 5（自检）**：当前代码产出的结果必须被判为 `v3`。

    **这条必须比较"常量 vs 现实"，不能只断言常量值。**

    同义反复的写法是 `assert CURRENT_APPARATUS == "v3"`——它只能证明
    "有人把常量写对了"，证明不了"常量与现实一致"。
    若有人改了 `evaluate()` 的字段名（例如 `features` -> `feature_scores`）
    但忘了改常量，旧写法仍会绿，而所有跨装置判断都会失效。

    正确判据：`CURRENT_APPARATUS == apparatus_signature(当前代码的产物)`。
    """
    from evals.datasets.retrieval_v2 import load_dataset
    from evals.datasets.v2_adapter import rows as adapt_rows
    from evals.run_retrieval import evaluate
    from evals.tools.check_v2_dataset import CURRENT_APPARATUS, apparatus_signature

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

    produced = apparatus_signature({"per_case": result["per_case"]})

    assert produced == CURRENT_APPARATUS, (
        f"常量说当前装置是 {CURRENT_APPARATUS!r}，"
        f"但 evaluate() 产出的签名是 {produced!r}——常量与现实脱节，"
        "所有基于签名的跨装置判断都会失效。"
    )
    assert produced == "v3", f"当前代码产出被判为 {produced!r}，应为 'v3'"

    # 且 per_case 里确实有 features 键（不是靠别的字段推理出来的）
    assert any("features" in c for c in result["per_case"]), (
        "per_case 里没有 features 键——签名函数不可能判对"
    )
