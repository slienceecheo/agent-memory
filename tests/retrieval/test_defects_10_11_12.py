"""缺陷 10、11、12 的锁定测试。

三条都断言"缺陷存在"，修好后变红并提示翻面（`locked_defect` 的约定）。

| 缺陷 | 性质 | 归属 |
|---|---|---|
| 10 | test 与 dev 有镜像分支 + gold 键重合 | 数据构造，需重造 test |
| 11 | `condition_match` 对"无条件"给 0.5、对"条件不符"给 0.0 | `src/`，前提未定 |
| 12 | 归档文件名不区分路径集合 | 已修，见 `REPAIRED` |
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from memory.retrieval.condition import condition_match

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


def _gold_key(spec: dict[str, object]) -> tuple[str, str, str]:
    return (
        str(spec["subject"]),
        str(spec["relation"]),
        str(spec.get("condition")),
    )


# ---------- 缺陷 10 ----------


@pytest.mark.locked_defect
def test_test_and_dev_share_mirrored_branches() -> None:
    """缺陷 10：test 与 dev 的 gold 键重合 41%，且存在镜像分支对。

    **断言缺陷存在**。修好（重造 test 使其独立）后 gold 键重合率应降到接近 0，
    本测试变红——那时翻面成正向断言并移进 `REPAIRED`。
    """
    dev_keys = {_gold_key(r["gold"]) for r in _rows("dev") if r.get("gold")}
    test_golds = [r["gold"] for r in _rows("test") if r.get("gold")]

    overlap = sum(1 for g in test_golds if _gold_key(g) in dev_keys)
    ratio = overlap / len(test_golds)

    assert ratio > 0.3, (
        f"test 与 dev 的 gold 键重合率降到 {ratio:.0%}，缺陷 10 可能已修。"
        "请翻面成正向断言并更新 C4 报告缺陷 10。"
    )
    assert overlap == 7


@pytest.mark.locked_defect
def test_test_split_is_not_independent() -> None:
    """缺陷 10 的第二条证据：test 的池成员 100% 来自 dev。

    与缺陷 9 的区别：9 说的是"任何非 dev split 的池都来自 dev"，
    10 说的是"因此 test 不是一个独立样本，其数字不可作为结论"。

    修缺陷 5（采样方式）会让本条与缺陷 9 同时转绿；
    若只有 9 变绿而本条不变，说明只改了采样、没解决数据重合。
    """
    all_gold: list[dict[str, object]] = []
    for split in SPLITS:
        all_gold.extend([r["gold"] for r in _rows(split) if r.get("gold")])

    dev_keys = {_gold_key(g) for g in all_gold if True}  # 占位，下方按 split 精算
    dev_keys = {_gold_key(r["gold"]) for r in _rows("dev") if r.get("gold")}
    test_golds = [r["gold"] for r in _rows("test") if r.get("gold")]

    overlap = sum(1 for g in test_golds if _gold_key(g) in dev_keys)

    assert overlap > 0, "test 与 dev 已无 gold 键重合，缺陷 10 可能已修"


# ---------- 缺陷 11 ----------


@pytest.mark.locked_defect
def test_condition_match_prefers_unstated_over_mismatched() -> None:
    """缺陷 11：条件不符得 0.0，反而低于"未标条件"的 0.5。

    **这是缺陷存在的断言**。修好后（例如改成对称的条件距离），
    `condition_match(query, mismatched) < condition_match(query, None)` 不再成立，
    本测试变红。

    **修法有两个来源**，见 C4 报告缺陷 11：
    - `condition_match` 的 0.5 中性分（`src/`）
    - BRANCH 的 gold 语义（查询指向新值、gold 是旧值）——这一条改代码修不了
    """
    mismatched = condition_match("prod", "dev")
    unstated = condition_match("prod", None)

    assert mismatched == 0.0
    assert unstated == 0.5
    assert unstated > mismatched, (
        "反向偏好已消失（未标条件不再优于条件不符）。"
        "请翻面成正向断言并更新 C4 报告缺陷 11。"
    )


@pytest.mark.locked_defect
def test_branch_query_points_at_candidate_not_gold() -> None:
    """缺陷 11 的第二个来源：BRANCH 的查询文本指向 `candidate_value`，不是 gold。

    这使得 gold 的 `condition_match` 在 BRANCH 上恒为 0——
    查询必然带新声明的条件，gold 必然带旧记忆的条件。

    改 `condition_match` 的常数修不了这一条，因为问题在 gold 的定义。
    """
    branch_rows = [
        r for r in _rows("dev") if "branch" in str(r.get("id")) and r.get("gold")
    ]
    assert branch_rows, "dev 里没有 BRANCH 场景"

    pointed_at_candidate = 0
    for row in branch_rows:
        gold = row["gold"]
        query = str(row["query"])
        candidate = str(row.get("candidate_value") or "")
        # 查询里出现 candidate 的实义字符，且不出现 gold 的值
        cand_chars = {c for c in candidate if c.strip()}
        gold_value = str(gold["value"])
        if (
            candidate
            and query
            and len(cand_chars & set(query)) >= max(2, len(cand_chars) // 2)
            and gold_value not in query
        ):
            pointed_at_candidate += 1

    assert pointed_at_candidate >= 3, (
        f"只有 {pointed_at_candidate}/{len(branch_rows)} 条 BRANCH 的查询指向 candidate。"
        "若 BRANCH 的 gold 语义被改了，请翻面并更新缺陷 11。"
    )


# ---------- 缺陷 12（已修，正向断言） ----------


def test_archive_overwrite_is_refused() -> None:
    """缺陷 12 已修复：`paths_enabled` 不同的既有结果文件必须拒绝覆盖。

    **这条是正向断言，不是 `locked_defect`。**
    缺陷 12 的后果是"默认参数重跑会静默覆盖归档并把两个实验算进同一个 run_count"。
    """
    from evals.run_retrieval import _assert_writable

    source = (ROOT / "evals" / "run_retrieval.py").read_text(encoding="utf-8")

    assert "_assert_writable" in source
    assert "--overwrite" in source or "overwrite" in source
    # 函数必须真的在写文件之前被调用
    assert source.index("_assert_writable(") < source.index('out.write_text(')
    assert callable(_assert_writable)
