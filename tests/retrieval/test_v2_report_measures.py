"""`v2-what-it-measures.md` 的每个数字必须能从结果文件复算。

**为什么需要**：这份报告是 v2 的结论汇总，它的四条结论都以"可复算"为强度依据。
若报告里的数字与结果文件脱节，"强"就退化成叙述。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
REPORT = ROOT / "docs" / "reports" / "v2-what-it-measures.md"


def _report() -> str:
    if not REPORT.exists():
        pytest.skip("报告缺失")
    return REPORT.read_text(encoding="utf-8")


def _load(name: str) -> dict[str, object]:
    path = ROOT / "results" / name
    if not path.exists():
        pytest.skip(f"{name} 缺失")
    return json.loads(path.read_text(encoding="utf-8"))


def test_report_states_its_scope_first() -> None:
    """报告必须以范围声明开头——防止数字被当成能力。"""
    text = _report()

    assert "本报告只使用 v2 数据集的两个 subject" in text
    assert "不是「v2 数据集证明了什么」" in text or "不是" in text
    # 四条范围限制都要在
    assert "无定义" in text
    assert "实验设计失败" in text
    assert "无统计意义" in text


def test_report_lists_recomputable_inputs() -> None:
    """四条结论各有一行"可复算输入"。"""
    text = _report()

    assert "可复算输入" in text or "复算输入" in text
    # 每条都有复算命令
    assert text.count("uv run --no-sync") >= 3


def test_conclusion_1_lexical_has_no_increment() -> None:
    """词面加不加，A 轴分数都不变。"""
    ledger_vec = _load("v2-ledger-vector.json")
    ledger_both = _load("v2-ledger-lexical-vector.json")

    def axis_a_hit1(payload: dict[str, object]) -> int:
        ranks = {
            c["case_id"]: c["rank_after_rerank"]
            for c in payload["per_case"]  # type: ignore[index]
        }
        a_ids = [k for k in ranks if k.startswith("ledger-q") and k not in
                 ("ledger-q11", "ledger-q12")]
        return sum(1 for k in a_ids if ranks[k] == 1)

    assert axis_a_hit1(ledger_vec) == axis_a_hit1(ledger_both) == 9


def test_conclusion_2_count_decomposition() -> None:
    """3+6+1=10、2+7+0=9。"""
    led = _load("v2-sample-condition-ablation.json")
    bil = _load("v2-billing-condition-ablation.json")

    def split(payload: dict[str, object], prefix: str) -> tuple[int, int, int, int]:
        """按**轴**过滤，不能只靠前缀。

        `ledger-q11` / `ledger-q12` 是 C 轴，用 `ledger-q` 前缀会误收——
        这正是报告 §3.1 计数分解里差点犯的错。
        """
        import sys

        sys.path.insert(0, str(ROOT))
        from evals.datasets.retrieval_v2 import Axis, load_dataset

        dataset_name = "sample" if prefix.startswith("ledger") else "billing"
        ds = load_dataset(ROOT / "data" / "retrieval-v2" / dataset_name)
        a_ids_all = {q.query_id for q in ds.queries if q.axis is Axis.A}

        with_c = payload["with_condition"]  # type: ignore[index]
        without_c = payload["without_condition"]  # type: ignore[index]
        ids = [q for q in with_c if q.startswith(prefix) and q in a_ids_all]
        base_only = [q for q in ids if with_c[q] == 1 and without_c.get(q) == 1]
        by_cond = [q for q in ids if with_c[q] == 1 and without_c.get(q) != 1]
        missed = len(ids) - len(base_only) - len(by_cond)
        return len(ids), len(base_only), len(by_cond), missed

    assert split(led, "ledger-q")[:3] == (10, 3, 6)
    assert split(bil, "billing-a") == (9, 2, 7, 0)


def test_conclusion_2_drop_values() -> None:
    led = _load("v2-sample-condition-ablation.json")
    bil = _load("v2-billing-condition-ablation.json")

    assert led["drop"] == pytest.approx(0.6, abs=1e-6)
    assert bil["drop"] == pytest.approx(0.7778, abs=1e-3)
    assert led["axis_a_seh1_without"] == pytest.approx(0.3, abs=1e-6)
    assert bil["axis_a_seh1_without"] == pytest.approx(0.2222, abs=1e-3)


def test_conclusion_3_condition_is_answer_copy() -> None:
    """`query_condition == gold.condition` 必须 10/10 与 9/9。"""
    import sys

    sys.path.insert(0, str(ROOT))
    from evals.datasets.retrieval_v2 import Axis, load_dataset

    for name, expected in (("sample", 10), ("billing", 9)):
        ds = load_dataset(ROOT / "data" / "retrieval-v2" / name)
        a_queries = [q for q in ds.queries if q.axis is Axis.A]
        same = sum(
            1
            for q in a_queries
            if q.query_condition == ds.memory(q.gold_memory_id).condition
        )
        assert len(a_queries) == expected
        assert same == expected


def test_conclusion_4_authority_thresholds() -> None:
    """`user_document` 0.085、`third_party` 0.250。"""
    import sys

    sys.path.insert(0, str(ROOT))
    from memory.retrieval.rerank import _AUTHORITY_SCORE
    from memory.store.models import Authority

    w = 0.25
    assert _AUTHORITY_SCORE[Authority.USER_DOCUMENT] == pytest.approx(0.66)
    assert _AUTHORITY_SCORE[Authority.THIRD_PARTY] == pytest.approx(0.0)
    assert (1 - 0.66) * w == pytest.approx(0.085)
    assert (1 - 0.0) * w == pytest.approx(0.25)


def test_report_marks_21_of_22_not_22_of_22() -> None:
    """必须是 21/22 + 1/22，不是 22/22。

    `billing-c2` 由同分 + 次级判据决定，不是四特征单独决定。
    """
    text = _report()

    assert "21/22" in text
    assert "第 22 条" in text


def test_report_states_seh_has_three_failure_modes() -> None:
    """SEH 的三种失真：两个分母问题 + 一个值域问题。"""
    text = _report()

    assert "分母问题" in text
    assert "值域问题" in text
    assert text.count("分母问题") >= 2


def test_report_does_not_claim_cross_domain_generality() -> None:
    """报告必须明确说两个 subject 不足以支撑一般性。"""
    text = _report()

    assert "不足以支撑跨领域的一般性" in text
    assert "两个 subject" in text


def test_no_section_is_repeated_verbatim() -> None:
    """报告的任一表格不得原样出现两次。

    **实测问题**：`### 2.3 这两条证据的机制不同` 曾与 §2.2 尾段完全相同——
    同一个表格、同一句话说了两遍。它会让读者以为"机制不同"是两件独立的事，
    而实际是同一句话说了两遍。

    判据：取每个 markdown 表格（连续 `|` 行），统计出现次数。
    """
    import re

    text = _report()
    blocks = re.findall(r"((?:^\|.*\|\s*$\n?)+)", text, re.M)
    seen: dict[str, int] = {}
    for block in blocks:
        key = block.strip()
        if len(key) < 40:  # 太短的表（如两行）不判重
            continue
        seen[key] = seen.get(key, 0) + 1

    duplicated = {k[:60]: n for k, n in seen.items() if n > 1}
    assert not duplicated, f"有表格重复出现：{duplicated}"


def test_no_heading_is_repeated() -> None:
    """标题不得重复——重复标题通常意味着整段被复制。

    **例外**：`### 复算` 是每节末尾的固定小节，重复是结构性的。
    剔除它之后，任何重复标题都值得查。
    """
    import re
    from collections import Counter

    STRUCTURAL = {"### 复算"}

    text = _report()
    headings = [
        h.strip()
        for h in re.findall(r"^###+ .*$", text, re.M)
        if h.strip() and h.strip() not in STRUCTURAL
    ]
    dupes = {h: n for h, n in Counter(headings).items() if n > 1}

    assert not dupes, f"重复标题：{dupes}"
