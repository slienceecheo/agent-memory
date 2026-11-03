"""门禁的适用域（tasks 2.3 / 2.5 / 3.1）。

**核心区分不是"读的文件新不新"，而是"判据是否依赖装置"。**

| 门禁 | 判据 | 依赖装置？ | 处置 |
|---|---|---|---|
| `L6b` | 池内向量都写入（范数非零） | ❌ | **照跑** |
| `L8` | dedup 收到的分数有方差 | ❌ | **照跑** |
| `L6c` | 三路召回都返回非空 | ❌ | **照跑** |
| `F19b` | implicit 的 gold 被召回 | ❌（召回不依赖排序） | **照跑** |
| `F20` | condition 对 A 轴有贡献 | **✅ 判据随装置消失** | 不适用 |
| `F24` | A 轴 SEH@1 不满分 | **✅ 阈值语义随装置反转** | 不适用 |

**为什么这个区分更根本**：签名只是识别手段，"判据依赖什么"才是该不该跑的理由。
把 `L6c` 判成"不适用"，等于永久关掉一条在 v3 下仍然有效的门禁——
它测的是"三路召回都返回非空"，与 condition 加权无关。

## 两条判据为何依赖装置

**`F20`**：测"去掉 condition 后 A 轴 SEH@1 掉多少"。
v3 里 condition 不参与加权，掉幅**恒为 0**（实测 with/without 逐条名次完全相同）。
判据本身不成立，不是"数字小"。

**`F24`**：测"A 轴 SEH@1 不得满分"。同一个阈值在两种装置下意义相反：

| 配置 | A 轴 SEH@1 | 判据 | 真实含义 |
|---|---|---|---|
| v2 三路 | 1.0000 | **红**（饱和） | 装置健康，指标饱和 |
| v3 单路 | 0.8333 | **绿** | **排序能力下降** |

## 装置签名：两种文件格式，两套结构判据

| 格式 | 判据 | 为什么是结构事实 |
|---|---|---|
| 有 `per_case` | 有 `features` -> v3 | v2 的代码不写这个键 |
| 消融聚合 | 两轴逐条 rank 相同 -> v3 | condition 不参与加权，消融不改变名次 |

**不用 `apparatus` 常量字段**：常量可以说谎。若有人回退代码或抄旧脚本，
产出的文件仍会写 `apparatus: "v3"`——那就是一行常量。
而"消融不改变名次"是跑出来的结果。
"""

from __future__ import annotations

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
RESULTS = ROOT / "results"
DATA = ROOT / "data" / "retrieval-v2"

# 判据**依赖**装置 -> 在 v3 下不适用
APPARATUS_DEPENDENT = ("F20", "F24")

# 判据**不依赖**装置 -> 照跑
APPARATUS_INDEPENDENT = ("L6b", "L8", "L6c", "F19b")


def _run_all(subject: str) -> list:
    from evals.datasets.retrieval_v2 import load_dataset
    from evals.tools.check_v2_dataset import run_all

    return run_all(load_dataset(DATA / subject))


# ---------- 分类正确性 ----------


@pytest.mark.parametrize("subject", ["sample", "billing"])
def test_only_apparatus_dependent_gates_are_not_applicable(subject: str) -> None:
    """**只有判据依赖装置的两条不适用**，其余照跑。

    这是本变更最核心的判据——上一版把 6 条全判"不适用"，
    等于永久关掉 `L6c`/`L6b`/`L8`/`F19b` 四条在 v3 下仍有效的门禁。
    """
    results = _run_all(subject)
    by_code = {r.code: r for r in results}

    for code in APPARATUS_DEPENDENT:
        assert not by_code[code].applicable, (
            f"{code} 的判据依赖装置，v3 下应不适用"
        )

    for code in APPARATUS_INDEPENDENT:
        assert by_code[code].applicable, (
            f"{code} 的判据不依赖装置，v3 下应照跑。"
            "把它判成'不适用'等于永久关掉一条有效门禁。"
        )


@pytest.mark.parametrize("subject", ["sample", "billing"])
def test_independent_gates_still_produce_verdicts(subject: str) -> None:
    """不依赖装置的门禁必须给出**真实结论**（通过或失败），不是不适用。"""
    results = _run_all(subject)
    by_code = {r.code: r for r in results}

    for code in APPARATUS_INDEPENDENT:
        detail = by_code[code].detail
        assert "不适用" not in detail, f"{code}: {detail[:60]}"
        assert detail.strip(), f"{code}: detail 为空"


# ---------- 不适用的语义 ----------


@pytest.mark.parametrize("subject", ["sample", "billing"])
def test_not_applicable_is_not_passed(subject: str) -> None:
    """**不适用不是通过**——`passed` 必须为 False。"""
    for r in _run_all(subject):
        if not r.applicable:
            assert not r.passed, (
                f"{r.code}: applicable=False 但 passed=True。'不适用'不是'通过'。"
            )


@pytest.mark.parametrize("subject", ["sample", "billing"])
def test_not_applicable_explains_why(subject: str) -> None:
    """不适用必须写明**为什么判据不成立**，不是只写"跨装置"。"""
    for r in _run_all(subject):
        if r.applicable:
            continue
        assert "不适用" in r.detail
        assert "v3" in r.detail, f"{r.code}: 未说明是当前装置的原因"


def test_contradiction_between_signature_and_content_is_caught() -> None:
    """签名判据必须是**结构事实**，不能靠常量自证。

    构造两份消融文件：
    - 一份 rank 变了（v2 行为）-> 判 v2
    - 一份 rank 没变（v3 行为）-> 判 v3

    若判据改成读 `apparatus: "v3"` 常量，第一份会被误判成 v3——
    而它内容是 v2 的。
    """
    from evals.tools.check_v2_dataset import apparatus_signature

    changed = {
        "with_condition": {"q1": 1, "q2": 2},
        "without_condition": {"q1": 2, "q2": 1},
        "apparatus": "v3",  # 常量说谎
    }
    unchanged = {
        "with_condition": {"q1": 1, "q2": 2},
        "without_condition": {"q1": 1, "q2": 2},
        "apparatus": "v2",  # 常量也说谎
    }

    assert apparatus_signature(changed) == "v2", (
        "rank 变了说明 condition 参与加权，是 v2 行为。"
        "常量 apparatus='v3' 不应影响判断。"
    )
    assert apparatus_signature(unchanged) == "v3", (
        "rank 没变说明 condition 不参与加权，是 v3 行为。"
    )


# ---------- 数字变化必须被锁住 ----------


def test_pass_counts_after_binding() -> None:
    """**修后的通过数必须被锁住**。

    实测：

    | subject | 修前 | 修后 | 差异 |
    |---|---|---|---|
    | `sample` | 21/27 | **19/27** | -2（F20、F24） |
    | `billing` | 24/27 | **23/27** | -1（F20 原通过，F24 原就失败） |

    **`billing` 只减 1 的原因**：F24 在 billing 上原本就被"满分"判为失败，
    变成"不适用"后仍不是通过——通过数不变，但语义从"失败"变成"不适用"。
    """
    sample = _run_all("sample")
    billing = _run_all("billing")

    assert sum(1 for r in sample if r.passed) == 19, (
        f"sample 通过数 {sum(1 for r in sample if r.passed)}/27，应为 19"
    )
    assert sum(1 for r in billing if r.passed) == 23, (
        f"billing 通过数 {sum(1 for r in billing if r.passed)}/27，应为 23"
    )
