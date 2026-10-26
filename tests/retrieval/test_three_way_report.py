"""三路召回报告的每个数字都必须能从 `results/a3-*.json` 复算。

报告的价值取决于"数字可复算"。这条与 C4 报告的
`test_report_consistency.py` 是同一纪律，只是对象不同。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
RESULTS = ROOT / "results"
REPORT = ROOT / "docs" / "reports" / "three-way-recall.md"

CONFIGS = {
    "lexical": "a3-lexical.json",
    "lexical+vector": "a3-lexical-vector.json",
    "3paths": "a3-lexical-vector-adjacency.json",
    "dedup": "a3-with-dedup.json",
}


def _load(name: str) -> dict[str, object]:
    path = RESULTS / name
    if not path.exists():
        pytest.skip(f"{name} 不存在")
    return json.loads(path.read_text(encoding="utf-8"))


def _scored(payload: dict[str, object]) -> list[dict[str, object]]:
    return [
        c
        for c in payload["per_case"]  # type: ignore[index]
        if c.get("has_gold") and not c.get("skipped")  # type: ignore[union-attr]
    ]


def _metrics(payload: dict[str, object]) -> tuple[float, float]:
    cases = _scored(payload)
    hit1 = sum(1 for c in cases if c["rank_after_rerank"] == 1) / len(cases)  # type: ignore[index]
    mrr = (
        sum(1.0 / c["rank_after_rerank"] if c["rank_after_rerank"] else 0.0 for c in cases)  # type: ignore[index]
        / len(cases)
    )
    return hit1, mrr


def test_report_exists() -> None:
    assert REPORT.exists()


@pytest.mark.parametrize(("label", "filename"), sorted(CONFIGS.items()))
def test_report_numbers_match_results(label: str, filename: str) -> None:
    """报告里的 `SEH@1` 与 MRR 必须与结果文件一致。"""
    hit1, mrr = _metrics(_load(filename))
    text = REPORT.read_text(encoding="utf-8")

    assert f"{hit1:.4f}" in text, f"{label} 的 SEH@1={hit1:.4f} 未出现在报告里"
    assert f"{mrr:.4f}" in text, f"{label} 的 MRR={mrr:.4f} 未出现在报告里"


def test_drop_decomposition_sums_to_seh1() -> None:
    """第 1 名分解必须自洽：仍在第 1 + 回到第 1 = 最终第 1。"""
    lex = _scored(_load(CONFIGS["lexical"]))
    three = _scored(_load(CONFIGS["3paths"]))

    lex_rank = {c["case_id"]: c["rank_after_rerank"] for c in lex}  # type: ignore[index]
    three_rank = {c["case_id"]: c["rank_after_rerank"] for c in three}  # type: ignore[index]

    was_first = [k for k in lex_rank if lex_rank[k] == 1]
    still_first = [k for k in was_first if three_rank[k] == 1]
    recovered = [k for k in lex_rank if lex_rank[k] != 1 and three_rank[k] == 1]

    final_first = len(still_first) + len(recovered)
    assert final_first == sum(1 for v in three_rank.values() if v == 1)
    assert len(still_first) == 22
    assert len(recovered) == 0


def test_branch_concentration_two_definitions() -> None:
    """两个集中度定义必须都能复算，且值不同（2.1x 与 3.0x）。"""
    lex = _scored(_load(CONFIGS["lexical"]))
    three = _scored(_load(CONFIGS["3paths"]))

    lex_rank = {c["case_id"]: c["rank_after_rerank"] for c in lex}  # type: ignore[index]
    three_rank = {c["case_id"]: c["rank_after_rerank"] for c in three}  # type: ignore[index]

    branch = [k for k in lex_rank if "branch" in k]
    non_branch = [k for k in lex_rank if "branch" not in k]

    # 定义 A：掉出第 1
    dropped_a = [k for k in lex_rank if lex_rank[k] == 1 and three_rank[k] != 1]
    # 定义 B：名次变差
    dropped_b = [k for k in lex_rank if three_rank[k] > lex_rank[k]]

    a_branch = sum(1 for k in dropped_a if "branch" in k)
    b_branch = sum(1 for k in dropped_b if "branch" in k)

    assert len(dropped_a) == 8
    assert len(dropped_b) == 11
    assert a_branch == 3
    assert b_branch == 6
    assert len(branch) == 6 and len(non_branch) == 27

    ratio_a = (a_branch / len(dropped_a)) / (len(branch) / len(lex_rank))
    ratio_b = (b_branch / len(dropped_b)) / (len(branch) / len(lex_rank))
    assert round(ratio_a, 1) == 2.1
    assert round(ratio_b, 1) == 3.0


def test_report_states_what_cannot_be_concluded() -> None:
    """报告必须先写"不能得出什么"，否则 0.6667 会被读成能力差。"""
    text = REPORT.read_text(encoding="utf-8")

    assert "不能得出的结论" in text
    assert "不是" in text and "能力差" in text
    assert "向量路径有贡献" in text
    assert "邻接路径有害" in text


def test_report_marks_unstable_dedup_cell() -> None:
    """`dev-branch-05` 的 dedup 列跨进程不可复现，必须标注。"""
    text = REPORT.read_text(encoding="utf-8")

    assert "dev-branch-05" in text
    assert "跨进程" in text or "不可复现" in text
    assert "3 / 7 / 6 / 13" in text or "3/7/6/13" in text


def test_report_cites_fingerprint() -> None:
    """报告必须写明四份结果的 fingerprint，否则无法确认同源。"""
    text = REPORT.read_text(encoding="utf-8")

    assert "189db1d9" in text
    hashes = {_load(name).get("code_diff_hash") for name in CONFIGS.values()}
    assert len(hashes) == 1, f"四份指纹不同：{hashes}"


def test_report_states_three_next_steps_with_acceptance() -> None:
    """三条"下一步"必须各带验收判据，且与实测状态对应。

    只写"要做什么"不够——这三条都属于"修了才知道能不能测"的类型，
    下一个人需要能判断"修到什么样才算修好"。
    """
    text = REPORT.read_text(encoding="utf-8")

    # 三条分别对应缺陷 16 / 13 / 向量阈值
    assert "修缺陷 16 才能测邻接" in text
    assert "修缺陷 13 才能测 dedup" in text
    assert "向量路径需要阈值才能谈贡献" in text

    # 每条都要有验收与当前状态
    assert text.count("**验收**") >= 3
    assert text.count("**当前**") >= 3

    # 当前状态必须是可复算的数字，不是形容词
    assert "0/6 真兄弟" in text
    assert "0 对同 key" in text
    assert "14/14" in text


def test_report_next_steps_match_measured_state() -> None:
    """"下一步"里引用的当前状态必须能从结果文件核对。"""
    text = REPORT.read_text(encoding="utf-8")
    three = _load(CONFIGS["3paths"])
    dedup = _load(CONFIGS["dedup"])

    # 邻接：13 条召回
    assert three["path_returns"]["adjacency"] == 13

    # 向量：mean 等于池大小（14 条）
    vector_returns = three["path_returns"]["vector"]
    scored = len(_scored(three))
    assert round(vector_returns / scored, 2) == 14.00

    # dedup：合并 0 条（输入与融合长度一致）
    for case in _scored(dedup):
        fused = case.get("fusion_tags") or []
        dedup_in = case.get("dedup_input_tags") or []
        assert len(dedup_in) == len(fused), "去重输入与融合长度应相同（未合并）"

    assert "13 条召回全部是非兄弟" in text
