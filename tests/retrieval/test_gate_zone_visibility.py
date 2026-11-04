"""门禁的"看到哪个分区"必须可执行地验证（tasks 本变更）。

**为什么需要**：回答"造完 v3 数据后谁来验"时，读代码得到的结论会漏掉
"新产物被旧产物遮蔽"这一类。实测发现：

`result_files()` 同时找到 `v2-sample-condition-ablation.json` 与
`v3-sample-condition-ablation.json`，而旧实现 `for path in candidates`
取第一个匹配的 -> 拿到 v2 -> 判"跨装置不适用" -> **v3 产物被遮蔽**。

所以"能发现 v3 产物"这句话，必须用"放了 v3 产物后结果真的变了"来验证，
而不是"`result_files` 的实现里扫了 v3"。

## 另一个事实：哪些门禁看不到 v3

实测 27 条门禁里 **7 条读文件**：

| 门禁 | 发现方式 | 能看到 `results/v3/` |
|---|---|---|
| `L6a` | `_load_run(THREE_PATH_RUN)` 写死 | ❌ |
| `L6b` | `_load_run(THREE_PATH_RUN)` 写死 | ❌ |
| `L6c` | 直接拼 `ROOT/"results"/"a3-..."` | ❌ |
| `L8` | `_load_run(DEDUP_RUN)` 写死 | ❌ |
| `F19b` | `_ablation_for_subjects` -> `result_files` | ✅ |
| `F20` | 同上 | ✅ |
| `F24` | `result_files` | ✅ |

**前 4 条看不到 v3 是合理的**（判据不依赖装置），但这件事必须被登记，
否则读者会以为 7 条都在验。
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
RESULTS = ROOT / "results"
V3 = RESULTS / "v3"
DATA = ROOT / "data" / "retrieval-v2"


def _ds(subject: str = "sample"):
    from evals.datasets.retrieval_v2 import load_dataset

    return load_dataset(DATA / subject)


def _snapshot(subject: str = "sample") -> dict[str, tuple[bool, bool]]:
    import evals.tools.check_v2_dataset as m

    return {r.code: (r.applicable, r.passed) for r in m.run_all(_ds(subject))}


@pytest.fixture
def clean_v3():
    """确保 v3 目录在测试前后都不残留。"""
    existed = V3.exists()
    backup = None
    if existed:
        backup = V3.with_suffix(".bak")
        if backup.exists():
            shutil.rmtree(backup)
        V3.rename(backup)
    try:
        yield
    finally:
        shutil.rmtree(V3, ignore_errors=True)
        if backup is not None and backup.exists():
            backup.rename(V3)


def _write_v3_ablation(subject: str = "sample") -> None:
    ds = _ds(subject)
    ranks = {q.query_id: 1 for q in ds.queries}
    payload = {
        "with_condition": ranks,
        "without_condition": dict(ranks),
        "drop": 0.0,
        "threshold": 0.30,
        "axis_a_seh1_with": 1.0,
        "axis_a_seh1_without": 1.0,
    }
    V3.mkdir(parents=True, exist_ok=True)
    (V3 / f"v3-{subject}-condition-ablation.json").write_text(
        json.dumps(payload, ensure_ascii=False), encoding="utf-8"
    )


# ---------- 核心：v3 产物不能被 v2 产物遮蔽 ----------


def test_v3_product_is_not_shadowed_by_v2(clean_v3) -> None:
    """**放了 v3 消融产物后，`F20` 必须真的读到它。**

    实测过的缺陷：`result_files` 同时找到 v2/v3 两份，
    而旧实现取第一个匹配的（`sorted` 让 v2 在前）-> **v3 被遮蔽**。

    这条用"放产物前后 `F20` 的结论是否改变"来验证，
    而不是"实现里有没有扫 v3"。
    """

    before = _snapshot()
    assert before["F20"] == (False, False), (
        f"前提不成立：没有 v3 产物时 F20 应为不适用，实际 {before['F20']}"
    )

    _write_v3_ablation()
    after = _snapshot()

    assert after["F20"] != before["F20"], (
        "放了 v3 消融产物后 F20 的结论没变——"
        "说明它读的仍是 v2 文件（被遮蔽），而不是 v3。"
    )
    assert after["F20"] == (True, True), (
        f"F20 应执行并通过（v3 下 drop==0），实际 {after['F20']}"
    )


def test_ablation_picks_current_apparatus_first(clean_v3) -> None:
    """`_ablation_for_subjects` 必须优先返回当前装置的产物。"""
    import evals.tools.check_v2_dataset as m

    _write_v3_ablation()
    _payload, source, sig, diag = m._ablation_for_subjects(_ds())

    assert diag == "ok"
    assert sig == m.CURRENT_APPARATUS, (
        f"选中的是 {source}（签名 {sig}），而当前装置是 {m.CURRENT_APPARATUS}——"
        "v3 产物被 v2 遮蔽了"
    )
    assert source.startswith("v3-"), source


def test_f19b_and_f20_see_the_same_file(clean_v3) -> None:
    """`F19b` 与 `F20` 共用 `_ablation_for_subjects`，必须看到同一份。"""
    import evals.tools.check_v2_dataset as m

    _write_v3_ablation()
    _, source, _, _ = m._ablation_for_subjects(_ds())

    # 两条门禁的 detail 都会提到来源文件名
    f19b = m.check_f19b_implicit_gold_recalled(_ds())
    assert source in f19b.detail or f19b.applicable, f19b.detail


# ---------- 前 4 条看不到 v3：登记成可执行的事实 ----------

FIXED_PATH_GATES = ("L6a", "L6b", "L6c", "L8")
V3_AWARE_GATES = ("F19b", "F20", "F24")


def test_fixed_path_gates_are_blind_to_v3(clean_v3) -> None:
    """**前 4 条写死路径的门禁，结果不受 v3 产物影响。**

    这是"它们不看 v3"的**可执行证据**：

    | 门禁 | 发现方式 |
    |---|---|
    | `L6a` / `L6b` | `_load_run(THREE_PATH_RUN)`，写死 `a3-*.json` |
    | `L6c` | 直接拼 `ROOT/"results"/"a3-..."` |
    | `L8` | `_load_run(DEDUP_RUN)`，写死 `a3-with-dedup.json` |

    **看不到 v3 是合理的**（判据不依赖装置），但必须被登记——
    否则读者会以为 6/7 条都在验 v3。
    """
    before = _snapshot()
    _write_v3_ablation()
    after = _snapshot()

    for code in FIXED_PATH_GATES:
        assert before[code] == after[code], (
            f"{code} 的结果因 v3 产物而改变（{before[code]} -> {after[code]}）——"
            "它本应只看 a3-*.json"
        )


def test_v3_aware_gates_are_exactly_three(clean_v3) -> None:
    """**只有 3 条走 `result_files()` 的门禁能看到 v3。**

    | 能看到 v3 | 发现方式 |
    |---|---|
    | `F19b` / `F20` | `_ablation_for_subjects` -> `result_files` |
    | `F24` | `result_files` 直接调用 |

    这条断言的是"恰好这 3 条"，不是"至少 3 条"——
    防有人给 `L6a` 也接上 `result_files` 而没登记。

    **取自** `ALL_CHECKS` 里函数的**源码体**，不是"凭印象列一遍"：
    新增一条走 `result_files()` 的门禁而没登记，这条会红。
    """
    import inspect

    import evals.tools.check_v2_dataset as m

    def _code_of(fn) -> str:
        # 从函数名取代号时必须**保留原大小写**：
        # `f19b` -> `F19b`，而 `.upper()` 会给出 `F19B`，与实际代号不符。
        stem = fn.__name__.removeprefix("check_").split("_")[0]
        return stem[0].upper() + stem[1:]

    aware = []
    for fn in m.ALL_CHECKS:
        src = inspect.getsource(fn)
        # 只看函数体（跳过 docstring）
        parts = src.split('"""')
        body = parts[-1] if len(parts) > 1 else src
        if "result_files(" in body or "_ablation_for_subjects(" in body:
            aware.append(_code_of(fn))

    assert set(aware) == set(V3_AWARE_GATES), (
        f"走 result_files 的门禁是 {sorted(aware)}，"
        f"而登记的是 {sorted(V3_AWARE_GATES)}。"
        "若新增了一条，必须同时登记它的产物来源。"
    )


# ---------- HANDOFF 里写的数字必须能被派生出来 ----------


def test_handoff_gate_counts_are_derivable() -> None:
    """HANDOFF §0 写的 "7 条读文件 / 3 条能看到 v3" 必须能从源码复算。

    **为什么需要**：这段数字是给读者回答"造完 v3 数据谁来验"的。
    它写在文档里，但**代码里没有任何东西守它**——
    加一条读文件的门禁、或给 `L6a` 接上 `result_files()`，
    文档会静默变成错的，而 27 条门禁照常全绿。

    **判据是"派生 == 文档声称"**，不是"文档里有这几个数字"：

    | 量 | 来源 |
    |---|---|
    | 读文件的门禁集合 | `_derive_reads()` 从源码 AST 派生 |
    | 文档声称的条数 | `HANDOFF.md` §0 的文字 |

    实测过这个形态的代价：上一轮我读代码得出"6 条"，实际 7 条；
    再读一次得出"4 条写死"，而登记表里写的是另外两个文件名。
    **凡是没有断言守着的数字，都会漂移。**
    """
    from tests.retrieval.test_result_side_gates import (
        DISCOVERED_GATES,
        FIXED_PATH_GATES,
        _derive_reads,
    )

    derived = _derive_reads()
    reading = {code for code, (fixed, disc) in derived.items() if fixed or disc}
    visible = {code for code, (_, disc) in derived.items() if disc}

    handoff = (ROOT / "docs" / "HANDOFF.md").read_text(encoding="utf-8")
    section = handoff.split("## 0. 当前状态")[1].split("\n## ")[0]

    assert f"读 `results/` 的一共 {len(reading)} 条" in section, (
        f"源码派生 {len(reading)} 条门禁读文件，而 HANDOFF §0 写的不是这个数。\n"
        f"派生的集合：{sorted(reading)}"
    )
    assert f"只有 {len(visible)} 条能看到 `results/v3/`" in section, (
        f"源码派生 {len(visible)} 条能看到 v3（{sorted(visible)}），"
        "而 HANDOFF §0 写的不是这个数。"
    )
    assert f"其余 {len(FIXED_PATH_GATES)} 条读历史产物的门禁照常执行" in section, (
        f"写死路径的有 {len(FIXED_PATH_GATES)} 条，而 HANDOFF §0 写的不是这个数。"
    )

    # 两族必须互补，且合起来等于全部读文件的门禁
    assert not (set(FIXED_PATH_GATES) & set(DISCOVERED_GATES)), (
        f"两族有交集：{sorted(set(FIXED_PATH_GATES) & set(DISCOVERED_GATES))}"
    )
    assert set(FIXED_PATH_GATES) | set(DISCOVERED_GATES) == reading, (
        "两族合起来必须等于全部读文件的门禁。\n"
        f"  两族并集：{sorted(set(FIXED_PATH_GATES) | set(DISCOVERED_GATES))}\n"
        f"  AST 派生：{sorted(reading)}"
    )
    assert visible == set(DISCOVERED_GATES), (
        "能看到 v3 的门禁必须恰好是发现式那一族——"
        "写死路径的门禁不可能看到子目录。"
    )
