"""v3 数据造出来后，三条门禁的**预期值**与"红了意味着什么"必须先定。

## 为什么需要这个文件

现在有 3 条门禁会验 v3 产物（`F19b` / `F20` / `F24`），而它们红的含义**不同**：

| 门禁 | 红的含义 | 该去查什么 |
|---|---|---|
| `F19b` | **数据问题**：某条 implicit 的 gold 真的没被召回 | 召回路径 / 查询措辞 |
| `F20` | **装置问题**：condition 又回到加权里了 | 排序代码（BREAKING 被回退） |
| `F24` | **数据难度问题**：太难或太简单 | 数据本身 |

如果这个区分不先写下来，造完数据后看到红色会分不清"装置坏了"和"数据不好"。

## 一个实测出来的更正

"前两条是结构必然"是个**错的分类**。实测：

```
构造：v3 签名（两轴逐条 rank 相同）+ 把 ledger-q3 的 rank 设为 None
F19b: applicable=True passed=False
      "1 条 implicit 从未被召回：['ledger-q3']"
```

`F19b` 判的是"召回是否真的成功"，而**召回不依赖排序装置**——
这是它被归为"照跑"的理由，也是它**不可能**是"结构必然"的理由。
它的通过与否完全由数据决定。

`F20` 才是结构必然，但**有前提**：

```
构造 A：v3 签名 + drop=0     -> passed=True
构造 B：v3 签名 + drop=0.5   -> passed=False（"掉幅 +0.5000 不为 0"）
```

它的"必然"来自 `ablate()` 在 v3 下两次跑出相同 ranks，
而**不是**来自"签名是 v3 所以判据自动通过"。手写一个矛盾的 drop 会被抓住。

## 所以真实分类是三档，不是两档

| 门禁 | 依赖什么 | 红了说明 |
|---|---|---|
| `F19b` | **数据**（召回） | 数据问题 |
| `F20` | **装置**（condition 是否加权） | 装置问题 |
| `F24` | **数据难度**（派生 within 的 SEH@1） | 数据问题（难度） |
"""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data" / "retrieval-v2"


def _ds(subject: str = "sample"):
    from evals.datasets.retrieval_v2 import load_dataset

    return load_dataset(DATA / subject)


def _v3_ablation(subject: str = "sample", *, drop: float = 0.0, victim: str | None = None):
    """v3 签名的消融产物：两轴逐条 rank 相同 -> 签名判 v3。"""
    ds = _ds(subject)
    ranks = {q.query_id: 1 for q in ds.queries}
    if victim is not None:
        ranks[victim] = None
    return {
        "with_condition": ranks,
        "without_condition": dict(ranks),
        "drop": drop,
        "threshold": 0.30,
        "axis_a_seh1_with": 1.0,
        "axis_a_seh1_without": 1.0 - drop,
    }


def _write(root: Path, name: str, payload: dict) -> None:
    p = root / "results" / "v3" / name
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


# ---------- F19b：依赖数据，不是结构必然 ----------


def test_f19b_is_data_dependent_not_structural(tmp_path: Path, monkeypatch) -> None:
    """**`F19b` 的通过由数据决定**，不是"v3 签名所以必然通过"。

    构造：v3 签名（两轴 rank 相同）**且**某条 implicit 的 rank 为 None。

    | 假设 | 预期 |
    |---|---|
    | "结构必然" | 通过 |
    | **"依赖数据"** | **红**（"从未被召回"） |

    实测是后者。所以 `F19b` 红了要**去查数据**，不是去查装置。
    """
    import evals.tools.check_v2_dataset as module

    ds = _ds()
    implicit = [q.query_id for q in ds.queries if q.cue_type.value == "implicit"]
    assert implicit, "前提不成立：sample 没有 implicit 查询"

    victim = implicit[0]

    # 先确认基线（未被破坏时）通过
    monkeypatch.setattr(module, "ROOT", tmp_path)
    _write(tmp_path, "v3-sample-condition-ablation.json", _v3_ablation())
    baseline = module.check_f19b_implicit_gold_recalled(ds)
    assert baseline.passed, f"前提不成立：正常产物下 F19b 应通过，实际 {baseline.detail}"

    # 破坏一条：把它的 rank 设为 None
    _write(
        tmp_path,
        "v3-sample-condition-ablation.json",
        _v3_ablation(victim=victim),
    )
    broken = module.check_f19b_implicit_gold_recalled(ds)

    assert not broken.passed, (
        f"把 {victim} 的 rank 设为 None 后 F19b 仍然通过——"
        "那说明它的判据不是'召回是否成功'"
    )
    assert victim in broken.detail, (
        f"detail 应点名哪条没被召回：{broken.detail}"
    )


def test_f19b_does_not_judge_apparatus(tmp_path: Path, monkeypatch) -> None:
    """**`F19b` 不判适用域**：v2 产物也要照跑，因为召回不依赖排序装置。

    这条与 `test_f19b_is_data_dependent_not_structural` 配对：
    前者说"它依赖数据"，这条说"它不依赖装置"。
    """
    import evals.tools.check_v2_dataset as module

    monkeypatch.setattr(module, "ROOT", tmp_path)
    # v2 签名：两轴 rank 不同
    ds = _ds()
    ranks_with = {q.query_id: 1 for q in ds.queries}
    ranks_without = {q.query_id: (1 if i % 2 == 0 else 2) for i, q in enumerate(ds.queries)}
    payload = {
        "with_condition": ranks_with,
        "without_condition": ranks_without,
        "drop": 0.6,
        "threshold": 0.30,
        "axis_a_seh1_with": 1.0,
        "axis_a_seh1_without": 0.4,
    }
    assert module.apparatus_signature(payload) == "v2"

    _write(tmp_path, "v2-sample-condition-ablation.json", payload)
    check = module.check_f19b_implicit_gold_recalled(ds)

    assert check.applicable, (
        f"F19b 把 v2 产物判成了不适用：{check.detail}。"
        "召回不依赖排序装置，它该照跑。"
    )


# ---------- F20：结构必然，但有前提 ----------


def test_f20_v3_zero_drop_is_structural(tmp_path: Path, monkeypatch) -> None:
    """**`F20` 在 v3 下期望掉幅为 0**——这是结构结论，不是"判据失效"。

    构造：v3 签名（两轴一致）+ drop=0 -> 必须通过。
    """
    import evals.tools.check_v2_dataset as module

    monkeypatch.setattr(module, "ROOT", tmp_path)
    _write(tmp_path, "v3-sample-condition-ablation.json", _v3_ablation())
    check = module.check_f20_condition_contributes(_ds())

    assert check.applicable and check.passed, check.detail
    assert "+0.0000" in check.detail, f"应报掉幅 0：{check.detail}"


def test_f20_catches_contradictory_drop(tmp_path: Path, monkeypatch) -> None:
    """**"结构必然"不等于"签名是 v3 就自动通过"**——判据读的是 `drop`。

    构造：v3 签名 + `drop=0.5`（矛盾的组合）。

    若 F20 只看签名，它会通过；实际它读 drop，所以红。
    **这条防的是"把 structural 读成 tautology"。**
    """
    import evals.tools.check_v2_dataset as module

    monkeypatch.setattr(module, "ROOT", tmp_path)
    _write(
        tmp_path,
        "v3-sample-condition-ablation.json",
        _v3_ablation(drop=0.5),
    )
    check = module.check_f20_condition_contributes(_ds())

    assert check.applicable, "这是 v3 产物，不该判不适用"
    assert not check.passed, (
        "v3 签名配 drop=0.5 竟然通过——"
        "说明 F20 只看签名不看 drop，'必然为 0' 就变成了恒真断言"
    )
    assert "0.5000" in check.detail, check.detail


def test_f20_red_means_apparatus_regression() -> None:
    """`F20` 红的归因必须写清：**装置问题**，不是数据问题。

    这条断言的是源码里那句归因文案——
    否则造完数据看到红色，人会去改数据。
    """
    import evals.tools.check_v2_dataset as module

    src = Path(module.__file__).read_text(encoding="utf-8")
    # 找到 v3 分支里"不为 0"的 detail
    idx = src.find("不为 0")
    assert idx >= 0, "源码里找不到'不为 0'的归因文案"
    window = src[idx : idx + 200]
    assert "condition 又参与了加权" in window, (
        f"F20 红时的归因文案没有指向装置：{window[:120]}"
    )


# ---------- F24：由数据难度决定 ----------


def test_f24_red_means_data_difficulty() -> None:
    """`F24` 红的归因必须指向**数据**，不是装置。

    两个方向的红，文案不同：

    | 方向 | 含义 |
    |---|---|
    | `<= baseline` | 排序比随机差 |
    | `>= ceiling` | 数据太容易 |
    """
    import evals.tools.check_v2_dataset as module

    src = Path(module.__file__).read_text(encoding="utf-8")
    for phrase in ("太容易", "基线"):
        assert phrase in src, f"F24 的归因文案缺少「{phrase}」"


# ---------- 三档分类本身 ----------


#: 三条门禁红的归因。**这是本文件要锁住的东西**：
#: 不是"它们都会红"，而是"红了各自意味着什么"。
RED_ATTRIBUTION = {
    "F19b": "data",  # 召回失败
    "F20": "apparatus",  # condition 又参与加权
    "F24": "data",  # 难度不合适
}


def test_red_attribution_covers_exactly_the_v3_aware_gates() -> None:
    """归因表必须恰好覆盖"能看到 v3 的门禁"，不多不少。

    **为什么与 `test_v3_aware_gates_are_exactly_three` 分开**：
    那条断言"哪些门禁看得到 v3"（发现方式），
    这条断言"它们红了各自意味着什么"（归因）。

    两条都依赖同一个集合，但验的是不同的事——
    分开写之后，改一处不会让另一处静默失效。
    """
    from tests.retrieval.test_result_side_gates import DISCOVERED_GATES, _derive_reads

    derived = _derive_reads()
    visible = {code for code, (_, disc) in derived.items() if disc}

    assert set(RED_ATTRIBUTION) == visible, (
        f"归因表覆盖 {sorted(RED_ATTRIBUTION)}，"
        f"而能看到 v3 的门禁是 {sorted(visible)}。\n"
        "三者必须一致：能验 v3 产物的门禁，都该写清红了意味着什么。"
    )
    assert set(RED_ATTRIBUTION) == set(DISCOVERED_GATES)


def test_only_f20_is_attributed_to_apparatus() -> None:
    """**只有 `F20` 红指向装置**——这是实测出来的分类，不是猜测。

    实测反例（"前两条都是结构必然"这个假设）：
    把某条 implicit 的 rank 设为 None，`F19b` 立刻红。
    所以 `F19b` 依赖数据，不是结构必然。

    如果将来有人把 `F19b` 也标成 `apparatus`，
    造完数据看到它红会去改排序代码——而真正该改的是数据。
    """
    apparatus = {g for g, a in RED_ATTRIBUTION.items() if a == "apparatus"}
    assert apparatus == {"F20"}, (
        f"归因到装置的门禁是 {sorted(apparatus)}，期望只有 F20。\n"
        "F19b 判召回（数据），F24 判难度（数据）。"
    )
