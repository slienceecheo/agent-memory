"""报告条件词表的真实覆盖率。

`structured=False` 的比例是这个词表的**诚实度量**：
它越高，说明 `condition_match` 特征在真实数据上越接近中性 0.5，
也就越没有区分度。

    uv run python -m evals.tools.report_condition_coverage
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from evals.datasets.independent_set import INDEPENDENT_FILE
from memory.retrieval.condition import parse_condition

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data" / "conflict-set"
FILES = ("dev.jsonl", "test.jsonl", INDEPENDENT_FILE)


def _rows(path: Path) -> list[dict[str, object]]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="evals.tools.report_condition_coverage")
    parser.add_argument("--dir", type=Path, default=DATA)
    args = parser.parse_args(argv)

    grand_total = 0
    grand_with_condition = 0
    grand_structured = 0

    for name in FILES:
        path = args.dir / name
        if not path.exists():
            continue
        rows = _rows(path)
        with_condition = 0
        structured = 0
        unknown: list[str] = []

        for row in rows:
            for field in ("condition", "existing_condition"):
                raw = row.get(field)
                if raw in (None, ""):
                    continue
                with_condition += 1
                parsed = parse_condition(str(raw))
                if parsed.structured:
                    structured += 1
                else:
                    unknown.append(str(raw))

        total = len(rows)
        grand_total += total
        grand_with_condition += with_condition
        grand_structured += structured

        ratio = structured / with_condition if with_condition else 0.0
        print(
            f"{name:<20} cases={total:<3} 有条件={with_condition:<3} "
            f"structured={structured:<3} 覆盖率={ratio:.0%}"
        )
        for item in sorted(set(unknown)):
            print(f"    未结构化: {item!r}")

    ratio = grand_structured / grand_with_condition if grand_with_condition else 0.0
    print(
        f"\n合计 cases={grand_total} 有条件={grand_with_condition} "
        f"structured={grand_structured} 覆盖率={ratio:.0%}"
    )
    if ratio < 0.8:
        print(
            "警告：覆盖率低于 80%，condition_match 在多数候选上会退化为中性 0.5，"
            "该特征的区分能力有限。",
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
