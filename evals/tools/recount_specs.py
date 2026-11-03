"""复算 HANDOFF §0.6/§0.7 的全部分母，并输出可直接粘贴的数字。

**为什么需要这个脚本**：这已是第四次因归档而手改一批统计数字
（142 -> 149 -> 173 -> 177 -> ?）。每次要重算 5 个量、同步 HANDOFF 与 7 条测试断言，
漏一处就变红。

**用法**：`uv run --no-sync python evals/tools/recount_specs.py`
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SPECS = ROOT / "openspec" / "specs"

# 规范词：英文 MUST/SHALL/SHOULD 与中文 必须/应当/不得/禁止
NORM = re.compile(r"\b(MUST|SHALL)\b")
NORM_ANY = re.compile(r"\b(MUST|SHALL|SHOULD)\b|必须|应当|不得|禁止")
VERB_PATTERN = re.compile(r"(实现|调用|导出|定义)\s*`([a-z_][a-z0-9_]*)`")


def main() -> int:
    per_cap: dict[str, dict[str, int]] = {}
    total_sc = 0
    total_must = 0
    total_sc_bare = 0

    for path in sorted(SPECS.rglob("spec.md")):
        text = path.read_text(encoding="utf-8")
        name = path.parent.name
        sc_blocks = re.split(r"^#### Scenario:", text, flags=re.M)[1:]
        must_lines = sum(
            1 for ln in text.splitlines() if NORM.search(ln)
        )
        per_cap[name] = {
            "requirements": len(re.findall(r"^### Requirement:", text, re.M)),
            "scenarios": len(sc_blocks),
            "must_lines": must_lines,
            "bare_scenarios": sum(1 for b in sc_blocks if not NORM_ANY.search(b)),
        }
        total_sc += len(sc_blocks)
        total_must += must_lines
        total_sc_bare += per_cap[name]["bare_scenarios"]

    # 四类细分
    no_tick = has_fn = has_const = tick_not_literal = 0
    for path in SPECS.rglob("spec.md"):
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
                x for x in syms
                if re.search(r"[-./0-9]", x) and not re.search(r"[(\[={]", x)
            ]
            if literals:
                has_const += 1
            else:
                tick_not_literal += 1

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
    print("## 四类细分")
    print("| 分类 | 行数 | 占比 |")
    print("|---|---|---|")
    for label, n in (
        ("无反引号", no_tick),
        ("有函数名", has_fn),
        ("有字符串常量", has_const),
        ("有反引号但非字面量", tick_not_literal),
    ):
        print(f"| {label} | {n} | {n / total_must * 100:.1f}% |")
    print(f"| 合计 | {total_must} | |")
    print()
    print(f"含反引号的行: {total_must - no_tick}")
    print()
    print("## 三层表")
    print(f"| 符号存在 | 1/{total_must} = {1 / total_must * 100:.1f}% |")
    print(f"| 行为符合 | 0/{total_must} = 0.0% |")
    print(f"| 人工映射表 | 3/{total_must} = {3 / total_must * 100:.1f}% |")
    print()
    print("## 覆盖率（两个不同分母，勿混）")
    print(f"| Scenario 分母 | 3/{total_sc} = {3 / total_sc * 100:.1f}% |")
    print(f"| MUST 分母 | 1/{total_must} = {1 / total_must * 100:.1f}% |")
    print()
    print("## 无规范词的 scenario")
    print(f"合计: {total_sc_bare}/{total_sc} = {total_sc_bare / total_sc * 100:.0f}%")
    print()
    print("## 能力数 / 要求数")
    print(f"能力 {len(per_cap)} 个 / 要求 {sum(d['requirements'] for d in per_cap.values())} 条")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
