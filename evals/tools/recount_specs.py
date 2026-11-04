"""复算 HANDOFF §0.6/§0.7 的统计，输出可直接粘贴的数字，并暴露 `compute()` 供测试读取。

**为什么需要这个脚本**：这已是第十次因归档而手改一批统计数字
（142 → 149 → 173 → 177 → 180 → 190 → 196 → 197 → 201 → 198）。
每次要重算 5 个量、同步 HANDOFF 与 7 条测试断言，漏一处就变红。

**为什么要有 `compute()`**：脚本算对了但回填漏了，能连续发生四次，
是因为**脚本和断言之间没有连接**——测试断言的是硬编码字符串。
`compute()` 让测试读同一个数据源。

## 两类数字，必须分开

| 类型 | 例子 | 能否自动化 |
|---|---|---|
| **A. 纯计算** | `282`、`198`、四类细分、合计 | ✅ 完全自动 |
| **B. 分子人工 + 分母计算** | `1/198 = 0.5%`、`3/282 = 1.1%` | ⚠️ **只能自动分母** |
| **C. 纯文案** | "本节有两个 1.2%" | ❌ 保留字面 |

**B 类的分子是人工结论**，不是算出来的：

| 分子 | 含义 | 为什么不能算 |
|---|---|---|
| `1` | "符号存在"= 1 条（`substring_exact_match`） | 与 `has_fn` 巧合相等，但定义不同 |
| `0` | "行为符合"= 0 条 | 人工判定"没有任何测试验证行为" |
| `3` | "人工映射表"= 3 行 | 数 HANDOFF 的表格行 -> 测试依赖文档 -> 循环 |
| `3` | "Scenario 分母"= 3 个有映射测试 | 人工登记 |
| `1` | "MUST 分母"= 1 条 | 同"符号存在" |

**所以 `compute()` 把它们作为显式常量暴露出来**，而不是藏在 f-string 里。
读者一眼能看出"这个 1 是人工填的"。

**用法**：`uv run --no-sync python evals/tools/recount_specs.py`
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
SPECS = ROOT / "openspec" / "specs"

# 规范词：英文 MUST/SHALL 与中文
NORM = re.compile(r"\b(MUST|SHALL)\b")
NORM_ANY = re.compile(r"\b(MUST|SHALL|SHOULD)\b|必须|应当|不得|禁止")
VERB_PATTERN = re.compile(r"(实现|调用|导出|定义)\s*`([a-z_][a-z0-9_]*)`")

# ---------- B 类：分子是人工结论，不是算出来的 ----------
#
# **不要试图让这些变"可计算"**：
# - `MANUAL_MAPPED_SCENARIOS` 要数 HANDOFF 的表格行，那让测试依赖文档（循环）
# - `MANUAL_MAPPING_ROWS` 同
# - `SYMBOL_EXISTS_ROWS` 与 `has_fn` 巧合相等，但定义是"能在 src 里 exists"
#
# 它们**只随人工复核变化**，不随 spec 变化。
MANUAL_SYMBOL_EXISTS_ROWS = 1  # substring_exact_match
MANUAL_BEHAVIOR_VERIFIED_ROWS = 0  # 没有任何测试验证"行为"
MANUAL_MAPPING_ROWS = 3  # HANDOFF §0.6 那张表的行数
MANUAL_MAPPED_SCENARIOS = 3  # 有映射测试的 scenario 数


def compute(root: Path | None = None) -> dict[str, Any]:
    """算全部统计，返回结构化数据。

    **`root` 是参数而不是模块常量**：测试要在临时目录上验证它，
    而 `ROOT` 在 import 时就固定了（这个坑在本项目踩过不止一次）。
    """
    base = root if root is not None else ROOT
    specs = base / "openspec" / "specs"

    per_cap: dict[str, dict[str, int]] = {}
    total_sc = 0
    total_must = 0
    total_sc_bare = 0

    for path in sorted(specs.rglob("spec.md")):
        text = path.read_text(encoding="utf-8")
        name = path.parent.name
        sc_blocks = re.split(r"^#### Scenario:", text, flags=re.M)[1:]
        must_lines = sum(1 for ln in text.splitlines() if NORM.search(ln))
        per_cap[name] = {
            "requirements": len(re.findall(r"^### Requirement:", text, re.M)),
            "scenarios": len(sc_blocks),
            "must_lines": must_lines,
            "bare_scenarios": sum(1 for b in sc_blocks if not NORM_ANY.search(b)),
        }
        total_sc += len(sc_blocks)
        total_must += must_lines
        total_sc_bare += per_cap[name]["bare_scenarios"]

    # 四类细分（A 类：全自动）
    no_tick = has_fn = has_const = tick_not_literal = 0
    for path in specs.rglob("spec.md"):
        for line in path.read_text(encoding="utf-8").splitlines():
            s = line.strip()
            if not NORM.search(s):
                continue
            syms = re.findall(r"`([^`]+)`", s)
            if not syms:
                no_tick += 1
                continue
            if VERB_PATTERN.search(s):
                has_fn += 1
                continue
            literals = [
                x
                for x in syms
                if re.search(r"[-./0-9]", x) and not re.search(r"[(\[={]", x)
            ]
            if literals:
                has_const += 1
            else:
                tick_not_literal += 1

    def pct(n: int, d: int) -> float:
        return n / d * 100 if d else 0.0

    return {
        # A 类：可计算
        "per_capability": per_cap,
        "scenarios": total_sc,
        "must_lines": total_must,
        "bare_scenarios": total_sc_bare,
        "requirements": sum(d["requirements"] for d in per_cap.values()),
        "capabilities": len(per_cap),
        "backticked": total_must - no_tick,
        "four_way": {
            "no_backtick": {"n": no_tick, "pct": pct(no_tick, total_must)},
            "has_fn": {"n": has_fn, "pct": pct(has_fn, total_must)},
            "has_const": {"n": has_const, "pct": pct(has_const, total_must)},
            "tick_not_literal": {
                "n": tick_not_literal,
                "pct": pct(tick_not_literal, total_must),
            },
            "total": total_must,
        },
        "bare_scenarios_pct": pct(total_sc_bare, total_sc),
        # B 类：分子人工（显式常量），分母计算
        "three_layer": {
            "symbol_exists": {
                "numerator": MANUAL_SYMBOL_EXISTS_ROWS,
                "denominator": total_must,
                "pct": pct(MANUAL_SYMBOL_EXISTS_ROWS, total_must),
            },
            "behavior_verified": {
                "numerator": MANUAL_BEHAVIOR_VERIFIED_ROWS,
                "denominator": total_must,
                "pct": pct(MANUAL_BEHAVIOR_VERIFIED_ROWS, total_must),
            },
            "manual_mapping": {
                "numerator": MANUAL_MAPPING_ROWS,
                "denominator": total_must,
                "pct": pct(MANUAL_MAPPING_ROWS, total_must),
            },
        },
        "coverage": {
            "scenario": {
                "numerator": MANUAL_MAPPED_SCENARIOS,
                "denominator": total_sc,
                "pct": pct(MANUAL_MAPPED_SCENARIOS, total_sc),
            },
            "must": {
                "numerator": MANUAL_SYMBOL_EXISTS_ROWS,
                "denominator": total_must,
                "pct": pct(MANUAL_SYMBOL_EXISTS_ROWS, total_must),
            },
        },
    }


def main() -> int:
    s = compute()
    per_cap = s["per_capability"]
    total_sc = s["scenarios"]
    total_must = s["must_lines"]

    print("=" * 60)
    print("HANDOFF §0.6/§0.7 的统计（可直接粘贴）")
    print("=" * 60)
    print()
    print("## Scenario 表")
    print("| 能力 | Scenario 数 |")
    print("|---|---|")
    for name, d in per_cap.items():
        print(f"| `{name}` | {d['scenarios']} |")
    print(f"| **合计** | **{total_sc}** |")
    print()
    print("## MUST/SHALL 行表")
    print("| 能力 | 含 MUST/SHALL 的行 |")
    print("|---|---|")
    for name, d in per_cap.items():
        print(f"| `{name}` | {d['must_lines']} |")
    print(f"| **合计** | **{total_must}** |")
    print()
    print("## 四类细分（A 类：全自动）")
    print("| 分类 | 行数 | 占比 |")
    print("|---|---|---|")
    labels = {
        "no_backtick": "无反引号",
        "has_fn": "有函数名",
        "has_const": "有字符串常量",
        "tick_not_literal": "有反引号但非字面量",
    }
    for key, label in labels.items():
        d = s["four_way"][key]
        print(f"| {label} | {d['n']} | {d['pct']:.1f}% |")
    print(f"| 合计 | {total_must} | |")
    print()
    print(f"含反引号的行: {s['backticked']}")
    print()
    print("## 三层表（B 类：分子人工，分母计算）")
    tl = s["three_layer"]
    print(
        f"| 符号存在 | {tl['symbol_exists']['numerator']}/{total_must}"
        f" = {tl['symbol_exists']['pct']:.1f}% |"
    )
    print(
        f"| 行为符合 | {tl['behavior_verified']['numerator']}/{total_must}"
        f" = {tl['behavior_verified']['pct']:.1f}% |"
    )
    print(
        f"| 人工映射表 | {tl['manual_mapping']['numerator']}/{total_must}"
        f" = {tl['manual_mapping']['pct']:.1f}% |"
    )
    print()
    print("## 覆盖率（两个不同分母，勿混；分子人工）")
    cov = s["coverage"]
    print(
        f"| Scenario 分母 | {cov['scenario']['numerator']}/{total_sc}"
        f" = {cov['scenario']['pct']:.1f}% |"
    )
    print(
        f"| MUST 分母 | {cov['must']['numerator']}/{total_must}"
        f" = {cov['must']['pct']:.1f}% |"
    )
    print()
    print("## 无规范词的 scenario")
    print(
        f"合计: {s['bare_scenarios']}/{total_sc}"
        f" = {s['bare_scenarios_pct']:.0f}%"
    )
    print()
    print("## 能力数 / 要求数")
    print(f"能力 {s['capabilities']} 个 / 要求 {s['requirements']} 条")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
