"""result-side 门禁的"适用域"登记（不是"缺陷"）。

**为什么不是"缺陷"**：这 7 条门禁（L6a / L6b / L6c / L8 / F19b / F20 / F24）读的是
`results/` 里**冻结的历史产物**，而不是当前装置的重跑结果：

| 门禁 | 读的文件 | 指纹 |
|---|---|---|
| L6a / L6b / L6c | `a3-lexical-vector-adjacency.json` | `899e2b6-dirty` |
| L8 | `a3-with-dedup.json` | `899e2b6-dirty` |
| F19b / F20 | `*-condition-ablation.json` | `47e4785-dirty` |
| F24 | `*-lexical-vector-adjacency.json` | `47e4785-dirty` |

而当前代码是 `0fbc3d2-dirty`。**没有一条读过当前装置的产物。**

这不是错——历史产物必须能被历史门禁检验。错的是**读者会以为**这些门禁在测当前装置。

## 手工维护的登记会漂移，而且已经漂移过三次

| 门禁 | 旧登记 | 代码实际读 |
|---|---|---|
| `L6a` | 未登记 | `a3-lexical-vector-adjacency.json` |
| `L6b` | `a3-with-dedup.json` | `a3-lexical-vector-adjacency.json`（`THREE_PATH_RUN`） |
| `F24` | `v2-*-lexical-vector-adjacency.json` | `*-lexical-vector-adjacency.json` |

**第三条最要命**：旧 pattern 带 `v2-` 前缀，而 `result_files()` 已经改成扫
`ZONE_NAMES`。于是"有人重跑这些文件时这条登记自动失效"的机制
**对 v3 产物不触发**——登记表看着在守，实际守的是旧名字。

所以本文件不再靠"再手写一遍"：`test_registry_matches_implementation` 用 AST
从 `check_v2_dataset.py` **派生**每条门禁实际读什么，再与登记逐条比对。
登记写错、代码改了登记没跟上，两者都会红。

## 两种发现方式，决定能否看到 `results/v3/`

| 发现方式 | 门禁 | 能看到 `results/v3/` |
|---|---|---|
| `_load_run()` / 直接拼路径（写死文件名） | L6a / L6b / L6c / L8 | ❌ |
| `result_files()`（扫顶层 + `ZONE_NAMES`） | F19b / F20 / F24 | ✅ |

**这不是遗漏，是适用域**：前 4 条的判据（三路被调用 / 向量写入 / 返回非空 /
分数有方差）不依赖排序装置，读 v2 产物得到结论是合理的。
但这件事**必须被登记**，否则"造完 v3 数据谁来验"的答案会被读成 7 条而不是 3 条。

**为什么用 `code_fingerprint()` 比对而不是硬编码版本号**：
硬编码会在有人改代码后失效，而"文件是否是当前装置产的"这个判据
必须跟着代码走。
"""

from __future__ import annotations

import ast
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RESULTS = ROOT / "results"

# **写死路径**的 4 条：`_load_run(name)` 拼 `ROOT/"results"/name`，
# 或直接拼 `ROOT/"results"/"<name>"`。**不扫子目录**，所以看不到 `results/v3/`。
FIXED_PATH_GATES: dict[str, tuple[str, ...]] = {
    "L6a": ("a3-lexical-vector-adjacency.json",),
    "L6b": ("a3-lexical-vector-adjacency.json",),
    "L6c": ("a3-lexical-vector-adjacency.json",),
    "L8": ("a3-with-dedup.json",),
}

# **走 `result_files()`** 的 3 条：扫 `results/` 顶层 + `ZONE_NAMES`。
# pattern **不带版本前缀**——前缀是装置的事，由 `apparatus_signature` 判断。
DISCOVERED_GATES: dict[str, tuple[str, ...]] = {
    "F19b": ("*-condition-ablation.json",),
    "F20": ("*-condition-ablation.json",),
    "F24": ("*-lexical-vector-adjacency.json",),
}

RESULT_SIDE_GATES: dict[str, tuple[str, ...]] = {
    **FIXED_PATH_GATES,
    **DISCOVERED_GATES,
}


def _current_fingerprint() -> tuple[object, object]:
    from evals.run_retrieval import code_fingerprint

    fp = code_fingerprint()
    return fp.get("code_version"), fp.get("code_diff_hash")


def test_result_side_gates_read_only_stale_artifacts() -> None:
    """7 条 result-side 门禁读的都是**旧装置**产物——这不是缺陷，是适用域。

    **判据**：它们读的每个结果文件的 `(code_version, code_diff_hash)` 都不等于
    当前代码的指纹。

    **发现方式必须与生产代码一致**：写死路径的按顶层 glob，
    走 `result_files()` 的用生产的 `result_files()`（会扫 `results/v3/`）。

    这很重要：`F24` 的旧登记写成 `v2-*`，于是 v3 产物放进去时
    **这条断言不会红**，而"有人重跑就自动失效"的机制就断了。

    **这条会在有人重跑那些文件时红**——那时 F20/F24 的适用域要重核，
    而不是继续沿用"门禁在测当前装置"这个假设。
    """
    from evals.tools.check_v2_dataset import result_files

    current = _current_fingerprint()
    same_as_current: list[str] = []
    missing: list[str] = []

    for gate, patterns in FIXED_PATH_GATES.items():
        for pattern in patterns:
            found = sorted(RESULTS.glob(pattern))
            if not found:
                missing.append(f"{gate} -> {pattern}")
            for path in found:
                data = json.loads(path.read_text(encoding="utf-8"))
                if (data.get("code_version"), data.get("code_diff_hash")) == current:
                    same_as_current.append(f"{gate} -> {path.name}")

    for gate, patterns in DISCOVERED_GATES.items():
        for pattern in patterns:
            found = result_files(pattern)
            if not found:
                missing.append(f"{gate} -> {pattern}")
            for path in found:
                data = json.loads(path.read_text(encoding="utf-8"))
                if (data.get("code_version"), data.get("code_diff_hash")) == current:
                    same_as_current.append(f"{gate} -> {path.name}")

    assert not missing, (
        f"这些门禁读的文件一个都不存在：{missing}。"
        "文件被删/改名时，这条登记必须重核，而不是静默通过。"
    )
    assert not same_as_current, (
        f"这些门禁读的文件已经是**当前装置**的产物：{same_as_current}。\n"
        "本文件登记的前提（'result-side 门禁只读历史产物'）已失效——\n"
        "重核 F20/F24 在当前装置下的适用性，而不是继续沿用旧结论。"
    )


def test_result_side_gate_count_is_seven() -> None:
    """**必须是 7 条**，不是 6 条。

    曾经漏了 `L6a`：它读 `THREE_PATH_RUN`，与 `L6b` 同一个文件，
    看上去像"已经统计过了"，于是"谁在读文件"少算一条。

    只登记 F20 会给读者"只有一个门禁有这问题"的错误印象。
    F24 是同一机制的更危险形态（它会**反向变绿**：A 轴 SEH@1 不饱和
    恰恰可能说明排序没生效，而门禁报 passed）。
    """
    assert len(RESULT_SIDE_GATES) == 7, sorted(RESULT_SIDE_GATES)
    assert len(FIXED_PATH_GATES) == 4, sorted(FIXED_PATH_GATES)
    assert len(DISCOVERED_GATES) == 3, sorted(DISCOVERED_GATES)


# ---------- 登记表必须与源码逐条一致 ----------


def _flatten_div(node: ast.expr) -> list[ast.expr]:
    """把 `A / B / C` 摊平成 `[A, B, C]`。"""
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div):
        return [*_flatten_div(node.left), node.right]
    return [node]


def _derive_reads() -> dict[str, tuple[frozenset[str], frozenset[str]]]:
    """从源码派生每条门禁读什么：`{代号: (写死路径, result_files 模式)}`。

    **递归跟进模块内的 helper**：`F19b`/`F20` 不直接调 `result_files`，
    而是经 `_ablation_for_subjects`。只看 check 函数体会漏掉它们。

    **只读源码，不执行**：执行会掩盖"某个分支里调了"这类事实。
    """
    from evals.tools import check_v2_dataset as module

    src = (ROOT / "evals" / "tools" / "check_v2_dataset.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    funcs = {n.name: n for n in tree.body if isinstance(n, ast.FunctionDef)}
    readers = {"_load_run", "result_files"}

    fixed: dict[str, set[str]] = {}
    discovered: dict[str, set[str]] = {}

    for fn in module.ALL_CHECKS:
        stem = fn.__name__.removeprefix("check_").split("_")[0]
        code = stem[0].upper() + stem[1:]

        fixed[code] = set()
        discovered[code] = set()

        # 工作列表：先看 check 自己，再看它调用的模块内 helper
        worklist = [fn.__name__]
        seen: set[str] = set()
        while worklist:
            name = worklist.pop()
            if name in seen or name not in funcs:
                continue
            seen.add(name)
            node = funcs[name]

            for call in ast.walk(node):
                if not isinstance(call, ast.Call):
                    continue
                fn_node = call.func
                if not isinstance(fn_node, ast.Name):
                    continue

                # _load_run(CONST) -> 写死文件名
                if fn_node.id == "_load_run" and call.args:
                    arg = call.args[0]
                    if isinstance(arg, ast.Name):
                        fixed[code].add(getattr(module, arg.id))
                    elif isinstance(arg, ast.Constant):
                        fixed[code].add(str(arg.value))
                    continue

                # result_files("pattern")
                if fn_node.id == "result_files" and call.args:
                    arg = call.args[0]
                    if isinstance(arg, ast.Constant):
                        discovered[code].add(str(arg.value))
                    continue

                # 模块内 helper -> 跟进
                if fn_node.id in funcs and fn_node.id not in readers:
                    worklist.append(fn_node.id)

            # 直接拼路径：ROOT / "results" / "<name>"
            for node2 in ast.walk(node):
                if not (isinstance(node2, ast.BinOp) and isinstance(node2.op, ast.Div)):
                    continue
                parts = _flatten_div(node2)
                if len(parts) < 3:
                    continue
                head, second, rest = parts[0], parts[1], parts[2:]
                if not (isinstance(head, ast.Name) and head.id == "ROOT"):
                    continue
                if not (isinstance(second, ast.Constant) and second.value == "results"):
                    continue
                if all(isinstance(p, ast.Constant) for p in rest):
                    fixed[code].add("/".join(str(p.value) for p in rest))  # type: ignore[attr-defined]

    return {
        code: (frozenset(fixed[code]), frozenset(discovered[code]))
        for code in fixed
    }


def test_registry_matches_implementation() -> None:
    """登记表必须等于**从源码派生**的读法，逐条、含空集。

    **为什么不是"检查登记里的每个文件都存在"**：那只能抓到"文件没了"，
    抓不到"登记写的是另一个文件"。实测 `L6b` 登记成 `a3-with-dedup.json`，
    而它实际读 `a3-lexical-vector-adjacency.json`——两个文件都存在，
    所以"存在性"检查全绿。

    **含空集**：派生说某条不读文件，登记里就不能有它。
    否则"登记表"会变成一张只增不减的清单。
    """
    derived = _derive_reads()

    registry_fixed = {gate: frozenset(pat) for gate, pat in FIXED_PATH_GATES.items()}
    registry_discovered = {
        gate: frozenset(pat) for gate, pat in DISCOVERED_GATES.items()
    }

    derived_fixed = {code: pair[0] for code, pair in derived.items() if pair[0]}
    derived_discovered = {code: pair[1] for code, pair in derived.items() if pair[1]}

    assert derived_fixed == registry_fixed, (
        "**写死路径**的登记与源码不符。\n"
        f"  源码派生：{ {k: sorted(v) for k, v in derived_fixed.items()} }\n"
        f"  登记表：  { {k: sorted(v) for k, v in registry_fixed.items()} }\n"
        "改代码或改登记，两边必须同步。"
    )
    assert derived_discovered == registry_discovered, (
        "**`result_files()`** 的登记与源码不符。\n"
        f"  源码派生：{ {k: sorted(v) for k, v in derived_discovered.items()} }\n"
        f"  登记表：  { {k: sorted(v) for k, v in registry_discovered.items()} }\n"
        "这一族决定能否看到 `results/v3/`——写错会让适用域的描述失真。"
    )


def test_v3_is_blind_to_condition_ablation() -> None:
    """**v3 下 condition 消融对名次的影响为 0**——这是设计结果，不是缺陷。

    这条锁住的是：`evaluate` 的 `condition` 参数在 v3 下**完全不影响排序**。
    所以 F20 的"掉幅"在 v3 上必然为 0，而 F20 读的是 v2 的 0.600——
    **两者测的不是同一件事**。

    判据用真实重跑，不是读 v2 文件。
    """
    import pytest
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
