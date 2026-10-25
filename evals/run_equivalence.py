"""用真实模型评估语义等价判断（分类别报告）。

**为什么要分类别**：审查实测，一个恒输出"互补"的分类器在 9 对上能拿 6/9，
恰好等于原阈值。所以必须分别要求 MERGE 类与 NOOP 类各自达标。

产出写入 `results/equivalence-classification.json`，
测试只读该文件，不依赖网络。
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from evals.datasets.independent_set import INDEPENDENT_FILE  # noqa: F401  (保持导入路径一致)
from memory.config import PROJECT_ROOT, Settings
from memory.llm.cache import ResponseCache
from memory.llm.client import LLMClient
from memory.retrieval.equivalence import EquivalenceJudge

FIXTURE = PROJECT_ROOT / "data" / "equivalence-pairs.json"
OUT = PROJECT_ROOT / "results" / "equivalence-classification.json"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="evals.run_equivalence")
    parser.add_argument("--fixture", type=Path, default=FIXTURE)
    parser.add_argument("--out", type=Path, default=OUT)
    args = parser.parse_args(argv)

    payload = json.loads(args.fixture.read_text(encoding="utf-8"))
    pairs = payload["pairs"]

    settings = Settings.load()
    settings.cache_dir.mkdir(parents=True, exist_ok=True)
    llm = LLMClient(
        settings=settings,
        response_cache=ResponseCache(settings.cache_dir / "responses.db"),
        max_retries=1,
        backoff_seconds=0.0,
    )
    judge = EquivalenceJudge(llm=llm)

    rows = []
    for pair in pairs:
        result = judge.judge(pair["left"], pair["right"])
        rows.append(
            {
                **pair,
                "predicted": result.equivalence.value,
                "correct": result.equivalence.value == pair["label"],
                "failed": result.failed,
            }
        )

    # 全部或大面积失败时，说明是环境问题（网关不可用/解析全败），
    # 而不是"模型判断都错"。此时必须报错退出，不能给出一个 0.10 的假分数。
    if rows and judge.failure_count >= max(1, int(len(rows) * 0.5)):
        print(
            f"错误：{judge.failure_count}/{len(rows)} 次判断失败，"
            "疑似网关不可用或输出无法解析。不产出分数。\n"
            "排查：确认 NO_PROXY 含 127.0.0.1，且本地网关在运行。",
        )
        return 2

    by_label: dict[str, dict[str, int]] = {}
    for row in rows:
        bucket = by_label.setdefault(row["label"], {"total": 0, "correct": 0})
        bucket["total"] += 1
        bucket["correct"] += int(row["correct"])

    accuracy = sum(item["correct"] for item in rows) / len(rows) if rows else 0.0
    output = {
        "n": len(rows),
        "accuracy": accuracy,
        "by_label": by_label,
        "llm_calls": judge.calls,
        "failures": judge.failure_count,
        "cache_size": judge.cache_size,
        "rows": rows,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")

    print(
        f"n={len(rows)} accuracy={accuracy:.2f} "
        f"calls={judge.calls} failures={judge.failure_count}"
    )
    for label, stats in sorted(by_label.items()):
        print(f"  {label:<14} {stats['correct']}/{stats['total']}")
    for row in rows:
        if not row["correct"]:
            print(
                f"  WRONG {row['case_id']}: expected={row['label']} "
                f"predicted={row['predicted']}  {row['left']!r} ↔ {row['right']!r}"
            )
    print(f"-> {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
