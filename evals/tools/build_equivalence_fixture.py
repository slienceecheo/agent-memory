"""为语义等价判断生成离线 fixture。

C3 独立集暴露的 9 条语义错误（6 条 MERGE = 互补，3 条 NOOP = 等义）是
评估等价判断的天然样本。但直接调模型会让测试依赖网络与成本，
所以先生成一次结果并缓存成 fixture，测试只读 fixture。

pairs 的来源：C3 独立集中 `existing_value` 与 `candidate_value` 构成的
真实配对，标签由 `expected` 推导：
- NOOP     → equivalent
- MERGE    → complementary
- 其余     → 不纳入（它们不是"同一事实的两种表述"）

    uv run python -m evals.tools.build_equivalence_fixture
"""

from __future__ import annotations

import json
from pathlib import Path

from evals.datasets.independent_set import INDEPENDENT_FILE

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data" / "conflict-set"
FIXTURE = ROOT / "data" / "equivalence-pairs.json"

# expected → 语义等价标签
_LABEL_MAP = {
    "NOOP": "equivalent",
    "MERGE": "complementary",
}


def collect_pairs() -> list[dict[str, str]]:
    path = DATA / INDEPENDENT_FILE
    rows = [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]

    pairs: list[dict[str, str]] = []
    for row in rows:
        label = _LABEL_MAP.get(str(row["expected"]))
        if label is None:
            continue
        existing = row.get("existing_value")
        if not existing:
            continue
        pairs.append(
            {
                "case_id": str(row["id"]),
                "left": str(existing),
                "right": str(row["candidate_value"]),
                "label": label,
                "expected_decision": str(row["expected"]),
                "confidence": str(row.get("confidence") or "确定"),
            }
        )
    return pairs


def main() -> int:
    pairs = collect_pairs()
    payload = {
        "source": INDEPENDENT_FILE,
        "note": "由 C3 独立集推导；标签来自 expected（NOOP→equivalent, MERGE→complementary）",
        "count": len(pairs),
        "pairs": pairs,
    }
    FIXTURE.parent.mkdir(parents=True, exist_ok=True)
    FIXTURE.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"{FIXTURE.name}: {len(pairs)} 对")
    for pair in pairs:
        print(f"  {pair['case_id']:<16} {pair['label']:<14} {pair['left']!r} ↔ {pair['right']!r}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
