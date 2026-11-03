"""v2 样例的三层实测表必须能从结果文件复算。

**为什么分三层而不是"修 harness 前后"**：0.667 → 1.000 是**补上 embedder**
带来的，不是 harness 修复带来的。两个原因在时间上挨着，在因果上无关。
混在一起写，就是一次"结论对但归因错"。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
RESULTS = ROOT / "results"
REPORT = ROOT / "docs" / "reports" / "v2-sample-validation.md"

LAYERS = {
    "v2-sample-lexical.json": ("①", 0.6667),
    "v2-ledger-lexical.json": ("③ lexical", 0.6667),
    "v2-ledger-lexical-vector.json": ("③ lex+vec", 1.0000),
    "v2-ledger-lexical-vector-adjacency.json": ("③ 3paths", 0.9167),
}


def _load(name: str) -> dict[str, object]:
    path = RESULTS / name
    if not path.exists():
        pytest.skip(f"{name} 不存在")
    return json.loads(path.read_text(encoding="utf-8"))


def test_report_exists() -> None:
    assert REPORT.exists()


def test_report_presents_three_layers() -> None:
    """报告必须有三个阶段，且写明只有第三层可用。

    三层是**装置状态**的记录（①修 harness 前 / ②未传 embedder / ③装置完整），
    与五组配置分解是两回事：前者记"装置接没接上"，后者记"每条路径贡献多少"。
    """
    text = REPORT.read_text(encoding="utf-8")

    assert "装置状态决定一切" in text
    assert "① 修 harness 前" in text
    assert "② 修 harness 后，未传 embedder" in text
    assert "③ 传 embedder 后" in text
    assert "只有 ③ 是可用数据" in text


def test_report_has_five_config_decomposition() -> None:
    """五组配置的分解表必须存在，且每个指标都带分母。"""
    text = REPORT.read_text(encoding="utf-8")

    assert "五组配置的完整分解" in text
    assert "每个数字都带分母" in text
    # 五组的名字都要出现
    for config in ("`lexical`", "`vector`", "`lex+vec`", "`vec+adj`", "`3paths`"):
        assert config in text
    # A 轴与整池的分母必须分别标注
    assert "A 轴 `SEH@1`" in text
    assert "n=10" in text
    assert "池 12 条" in text


def test_report_distinguishes_the_two_ones() -> None:
    """两个 `SEH@5 = 1.000` 必须标明各自的**分母**。

    这是唯一能让读者分辨"空操作"与"真实成绩"的东西——
    段落标题做不到，数字本身也做不到。
    """
    text = REPORT.read_text(encoding="utf-8")
    section = text.split("两个 `SEH@5 = 1.000` 的含义完全不同")[1].split("\n## ")[0]

    assert "融合输入 1 条" in section
    assert "池 12 条" in section
    assert "空操作" in section
    assert "真实成绩" in section


def test_report_documents_q4_three_layer_chain() -> None:
    """q4 的三层失败链必须三个原因都写，不能只写邻接。"""
    text = REPORT.read_text(encoding="utf-8")
    section = text.split("q4 的三层失败链")[1].split("\n## ")[0]

    assert "向量" in section and "重排" in section and "邻接" in section
    # 三个缺陷编号都要出现
    assert "18" in section and "19" in section and "16" in section
    # 四特征值要在
    assert "auth" in section
    assert "−0.1025" in section or "-0.1025" in section


def test_report_states_gate_pass_count() -> None:
    """门禁状态必须写明通过数，且说明 F18 的失败是正确的失败。"""
    text = REPORT.read_text(encoding="utf-8")

    assert "21/27" in text
    assert "F18 的失败是正确的失败" in text
    assert "F19a" in text and "F19b" in text


def test_gate_count_matches_actual_runs() -> None:
    """**报告记录的是历史值**（2026-10-26 生成，tag 时产物）。

    所以本条不再断言"报告数字 == 当前运行结果"——那会在装置变更时假红，
    而红的理由不是"报告错了"，是"报告故意记录历史"。

    正确判据：

    1. 报告里必须写明它记录的时点（`生成时间`）
    2. 当前实际通过数必须有地方记录（HANDOFF §0）
    3. 两者的关系（为什么不同）必须被写出

    实测差异：报告 21/27，当前 19/27——差在 `F20`/`F24` 转为"不适用"。
    """
    from evals.datasets.retrieval_v2 import load_dataset
    from evals.tools.check_v2_dataset import run_all

    sample = ROOT / "data" / "retrieval-v2" / "sample"
    if not sample.exists():
        pytest.skip("样例数据集缺失")

    text = REPORT.read_text(encoding="utf-8")

    # 1. 报告必须标时点
    assert "生成时间" in text, "报告未标明它记录的是哪个时点的状态"

    # 2. 报告里的历史值必须还在（历史不可改写）
    assert "21/27" in text, "报告里的历史值 21/27 被改动了——那是历史快照"

    # 3. 当前值 - 历史值 == 判据依赖装置的两条
    results = run_all(load_dataset(sample))
    passed = sum(1 for r in results if r.passed)
    not_applicable = {r.code for r in results if not r.applicable}

    assert not_applicable == {"F20", "F24"}, (
        f"不适用的是 {sorted(not_applicable)}，应为 {{'F20', 'F24'}}。"
        "差值必须等于这两条——否则报告与实际的差异无法解释。"
    )
    assert passed == 21 - len(not_applicable), (
        f"当前 {passed}/27，历史 21/27，差 {-1 * (passed - 21)}。"
        f"不适用有 {len(not_applicable)} 条——差值应当相等。"
    )

    # 4. 当前值必须写在 HANDOFF（唯一"当前状态"入口）
    handoff = (ROOT / "docs" / "HANDOFF.md").read_text(encoding="utf-8")
    assert f"ledger {passed}/27" in handoff, (
        f"HANDOFF 未写当前值 ledger {passed}/27"
    )

    # 5. 失败项 = 历史失败项 + 新增的"不适用"项
    #
    # **`F20`/`F24` 不是"新发现的失败"**，它们的判据在 v3 下不成立。
    # 把它们混进"失败项"会让下一个人以为装置退化了。
    failed_due_to_criterion = {r.code for r in results if not r.passed and r.applicable}
    failed_because_na = {r.code for r in results if not r.passed and not r.applicable}

    assert failed_due_to_criterion == {"F6", "F13", "F17b", "F18", "F21a", "F21b"}, (
        f"适用门禁的未通过项变了：{failed_due_to_criterion}"
    )
    assert failed_because_na == {"F20", "F24"}, (
        f"不适用的项是 {sorted(failed_because_na)}，应为 {{'F20', 'F24'}}"
    )

def test_conclusion_section_has_no_stale_gate_numbers() -> None:
    """「结论」一节里不能同时出现多个通过数。

    **这是真实发生过的问题**：结论节写着 11/17，而门禁实际早已是 19/22，
    因为行文只更新了某一处。同一份报告里两个数字并存，
    读者无从判断哪个是当前状态。
    """
    import re

    text = REPORT.read_text(encoding="utf-8")
    match = re.search(r"## 结论.*?(?=\n## |\Z)", text, re.S)
    assert match is not None, "报告缺少结论节"
    section = match.group(0)

    stale = ["11/17", "12/16", "13/18", "17/20"]
    found = [n for n in stale if n in section]
    assert not found, f"结论节里有过期通过数：{found}"


def test_layer_three_numbers_match_results() -> None:
    """第三层的三个数字必须与结果文件一致。"""
    for name, (label, expected) in LAYERS.items():
        if label == "①":
            continue
        payload = _load(name)
        assert payload["seh_at_k"] == pytest.approx(expected, abs=0.001), (
            f"{name} 的 SEH@5 是 {payload['seh_at_k']}，报告写 {expected}"
        )


def test_vector_returns_are_present_only_with_embedder() -> None:
    """带 embedder 的结果里 vector 返回条数必须 > 0。

    区分 ③ 与 ②/① 的唯一可观测差异就是这一列。
    """
    with_vec = _load("v2-ledger-lexical-vector.json")
    assert with_vec["path_returns"]["vector"] is not None
    assert with_vec["path_returns"]["vector"] > 0

    without_vec = _load("v2-sample-lexical.json")
    assert without_vec["path_returns"]["vector"] is None


def test_implicit_cases_are_rescued_by_vector() -> None:
    """4 条 implicit 在词面全失败、在 lex+vec 全部命中。

    这是本样例里向量路径唯一的正面证据。
    """
    raw = {
        q["query_id"]: q["cue_type"]
        for q in (
            json.loads(line)
            for line in (ROOT / "data/retrieval-v2/sample/queries.jsonl")
            .read_text(encoding="utf-8")
            .splitlines()
            if line.strip()
        )
    }
    implicit = [cid for cid, cue in raw.items() if cue == "implicit"]
    assert len(implicit) == 4

    lex = {
        c["case_id"]: c["rank_after_rerank"]
        for c in _load("v2-ledger-lexical.json")["per_case"]  # type: ignore[index]
    }
    lexvec = {
        c["case_id"]: c["rank_after_rerank"]
        for c in _load("v2-ledger-lexical-vector.json")["per_case"]  # type: ignore[index]
    }

    for cid in implicit:
        assert lex[cid] is None, f"{cid} 在词面路径上应当失败"
        assert lexvec[cid] is not None, f"{cid} 应当被向量救回"
        assert lexvec[cid] <= 5


def test_adjacency_hurts_on_v2() -> None:
    """邻接在 v2 上有真兄弟，结果仍变差（q4 从 3 掉到 6）。"""
    lexvec = {
        c["case_id"]: c["rank_after_rerank"]
        for c in _load("v2-ledger-lexical-vector.json")["per_case"]  # type: ignore[index]
    }
    three = {
        c["case_id"]: c["rank_after_rerank"]
        for c in _load("v2-ledger-lexical-vector-adjacency.json")["per_case"]  # type: ignore[index]
    }

    assert lexvec["ledger-q4"] == 3
    assert three["ledger-q4"] == 6
    assert three["ledger-q4"] > 5, "应当掉出前 5，这是 SEH@5 从 1.000 掉到 0.917 的原因"
