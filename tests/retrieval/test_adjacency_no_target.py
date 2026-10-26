"""缺陷 16：邻接路径在 dev 上没有合法召回目标。

邻接的语义是"返回该逻辑键下的其他条件分支，服务 BRANCH 场景"。
但 dev 的 6 条 BRANCH 里，真兄弟在池中的条数是 **0/6**。

两层原因：

1. BRANCH 的兄弟只作为该行的 `candidate_value` 存在——那是 C3 写入路径
   要判定的"新声明"，**从未被当作一条存储里的记忆**
2. 唯一存在于 `all_specs` 的那条（`dev-branch-04` 的兄弟，来自 **test split**）
   在 `others` 里下标是 33，被 `others[:20]` 截掉了

因此邻接在 dev 上召回的全是非兄弟条目。**这不是邻接算法错，
是评测池里没有它该召回的条目。**

修法属 v2：A 轴每个 subject 有 3–4 条分支都作为记忆存在于池里，
邻接才有真兄弟。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from evals.run_retrieval import select_pool_distractors

from memory.retrieval.pool_modes import PoolMode

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data" / "conflict-set"
SPLITS = ("dev", "test", "independent")


def _rows(split: str) -> list[dict[str, object]]:
    path = DATA / f"{split}.jsonl"
    if not path.exists():
        pytest.fail(f"数据集缺失：{path}")
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _gold_specs() -> list[tuple[str, dict[str, object]]]:
    specs: list[tuple[str, dict[str, object]]] = []
    for split in SPLITS:
        for row in _rows(split):
            if row.get("gold"):
                specs.append((split, row["gold"]))  # type: ignore[arg-type]
    return specs


def _key(spec: dict[str, object]) -> tuple[str, str, str, str]:
    return (
        str(spec["subject"]),
        str(spec["relation"]),
        str(spec.get("condition")),
        str(spec["value"]),
    )


@pytest.mark.locked_defect
def test_adjacency_has_no_legal_target_on_dev() -> None:
    """缺陷 16：dev 的 6 条 BRANCH，真兄弟在池中的条数是 0/6。

    **断言缺陷存在**。v2 数据造好后（A 轴每 subject 3–4 条分支都在池里），
    本条应转红——那时翻面成正向断言并更新 C4 报告缺陷 16。
    """
    all_specs = [spec for _, spec in _gold_specs()]
    spec_keys = {_key(spec) for spec in all_specs}

    branch_rows = [r for r in _rows("dev") if "branch" in str(r.get("id")) and r.get("gold")]
    assert len(branch_rows) == 6, f"dev 的 BRANCH 条数变了：{len(branch_rows)}"

    in_specs = 0
    in_pool = 0
    for row in branch_rows:
        gold = row["gold"]
        sibling = (
            str(row["subject"]),
            str(row["relation"]),
            str(row.get("condition")),
            str(row.get("candidate_value")),
        )
        if sibling in spec_keys:
            in_specs += 1

        picked = select_pool_distractors(
            gold, all_specs, mode=PoolMode.UNRELATED, limit=20
        )
        if any(_key(sp) == sibling for sp in picked):
            in_pool += 1

    assert in_pool == 0, (
        f"有 {in_pool}/6 条 BRANCH 的真兄弟进了池。"
        "若数据或采样变了，请重新评估缺陷 16 并翻面本测试。"
    )
    # 另一条证据：唯一存在于 all_specs 的那条兄弟，被 others[:20] 截掉了
    assert in_specs <= 1, f"真兄弟存在于 all_specs 的条数：{in_specs}"


@pytest.mark.locked_defect
def test_adjacency_siblings_exist_but_are_truncated_away() -> None:
    """缺陷 16 的第二层原因：唯一存在于 `all_specs` 的兄弟被 `others[:20]` 截掉。

    与上一条互补：上面说"池里没有兄弟"，这条说"为什么有一个也没进来"。

    `dev-branch-04` 的兄弟（`test_command/local/sqlite`）确实存在于
    **test split** 的 gold 里，但在 `others` 中下标是 33，超出 `[:20]`。
    """
    all_specs = [spec for _, spec in _gold_specs()]

    row = next(r for r in _rows("dev") if r.get("id") == "dev-branch-04")
    gold = row["gold"]
    sibling = (
        str(row["subject"]),
        str(row["relation"]),
        str(row.get("condition")),
        str(row.get("candidate_value")),
    )

    gold_key = _key(gold)
    others = [spec for spec in all_specs if _key(spec) != gold_key]
    index = next((i for i, spec in enumerate(others) if _key(spec) == sibling), None)

    assert index is not None, "兄弟不在 all_specs 里了，数据可能变了"
    assert index >= 20, (
        f"兄弟在 others 里的下标是 {index}，已落在 [:20] 内——"
        "若采样方式改了，请重新评估缺陷 16"
    )
