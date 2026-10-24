"""把已确认的标签迁移到重建后的场景集。

重建场景集会重置所有标签为 proposed。本脚本按 id 把旧文件里
`confirmed` 的条目恢复回去（只恢复 `expected` / `labeler` / `confirmed_at`
三个字段，其余以新文件为准）。

用法：
    uv run python -m evals.tools.preserve_labels <旧文件> <新文件>

为什么需要它：修场景内容不该丢掉已经花时间确认过的标签。
但反过来，如果只做"整文件覆盖"，就会把修好的内容覆盖回去——
所以必须按 id 精确迁移，且只迁移标签字段。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path


def _load(path: Path) -> dict[str, dict[str, object]]:
    rows: dict[str, dict[str, object]] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        rows[str(row["id"])] = row
    return rows


def preserve(old: Path, new: Path) -> tuple[int, int, list[str]]:
    """把 old 中已确认的标签迁移到 new。

    返回 (迁移条数, 保持 proposed 条数, 只在 old 里存在的 id 列表)。
    """
    old_rows = _load(old)
    new_rows = _load(new)

    migrated = 0
    kept_proposed = 0
    orphaned: list[str] = []

    for case_id, new_row in new_rows.items():
        old_row = old_rows.get(case_id)
        if old_row is None:
            kept_proposed += 1
            continue
        if old_row.get("label_status") != "confirmed":
            kept_proposed += 1
            continue
        new_row["expected"] = old_row["expected"]
        new_row["label_status"] = "confirmed"
        if old_row.get("labeler"):
            new_row["labeler"] = old_row["labeler"]
        if old_row.get("confirmed_at"):
            new_row["confirmed_at"] = old_row["confirmed_at"]
        migrated += 1

    for case_id in old_rows:
        if case_id not in new_rows:
            orphaned.append(case_id)

    lines = [json.dumps(new_rows[key], ensure_ascii=False) for key in sorted(new_rows)]
    new.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return migrated, kept_proposed, orphaned


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    if len(args) != 2:
        print("用法：python -m evals.tools.preserve_labels <旧文件> <新文件>", file=sys.stderr)
        return 2
    old, new = Path(args[0]), Path(args[1])
    migrated, kept, orphaned = preserve(old, new)
    print(f"{new.name}: 迁移 {migrated} 条已确认标签，{kept} 条保持 proposed")
    if orphaned:
        print(f"  旧文件中已不存在的 id：{', '.join(orphaned)}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
