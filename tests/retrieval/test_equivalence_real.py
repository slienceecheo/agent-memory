"""语义等价判断的实测评估（离线 fixture + 缓存结果）。

**为什么读 fixture 而不是直接调模型**：默认门禁不能依赖网络。
结果的生成过程见 `evals/run_equivalence.py`。

**必须分类别断言**：审查实测，一个恒输出"互补"的分类器在 9 对上能拿 6/9，
恰好等于原来的单一阈值。所以 MERGE 类与 NOOP 类要分别要求。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / "data" / "equivalence-pairs.json"
RESULT = ROOT / "results" / "equivalence-classification.json"


def _result() -> dict[str, object]:
    if not RESULT.exists():
        pytest.skip("等价判断结果不存在；先跑 `python -m evals.run_equivalence`")
    return json.loads(RESULT.read_text(encoding="utf-8"))


def test_fixture_covers_both_classes() -> None:
    """fixture 必须同时含等义与互补，否则分类别报告无从谈起。"""
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    labels = {pair["label"] for pair in payload["pairs"]}

    assert labels == {"equivalent", "complementary"}


def test_fixture_pairs_come_from_independent_set() -> None:
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))

    assert all(pair["case_id"].startswith("ind-") for pair in payload["pairs"])


def test_no_failures_in_result() -> None:
    """若失败数高，说明是环境问题而不是模型判断，
    这种情况下分数没有意义（`run_equivalence` 已在半数失败时报错退出）。
    """
    result = _result()

    assert result["failures"] == 0, (
        f"{result['failures']} 次判断失败，结果不可用"
    )


def test_complementary_class_meets_threshold() -> None:
    """MERGE 类（互补）必须 ≥5/6。"""
    result = _result()
    stats = result["by_label"]["complementary"]

    assert stats["correct"] >= 5, (
        f"互补类只有 {stats['correct']}/{stats['total']}"
    )


def test_equivalent_class_is_reported_honestly() -> None:
    """NOOP 类（等义）**当前未达标**（2/4）。

    这条断言锁定的是**事实**而不是期望：模型倾向于把"等义"判成"互补"
    （`每周日凌晨` vs `每周日零点`、`下周六去怀柔团建` vs `下周六去怀柔玩`）。

    阈值要求 3/4。若将来切换提示词或模型后达标，把这里的 2 改成 3，
    并在报告里更新——而不是把阈值悄悄调低。
    """
    result = _result()
    stats = result["by_label"]["equivalent"]

    assert stats["total"] == 4
    assert stats["correct"] == 2, (
        f"等义类结果变了：{stats['correct']}/{stats['total']}。"
        "若已修复到 3/4，请更新本断言并在报告中说明改了什么。"
    )


def test_overall_accuracy_is_locked() -> None:
    """总体准确率锁定在 0.80（8/10）。"""
    result = _result()

    assert result["accuracy"] == pytest.approx(0.8, abs=1e-6)


def test_misclassified_cases_are_the_two_equivalent_ones() -> None:
    """具体错在哪两条也被锁定，避免"修好了 A 弄坏了 B"不被发现。"""
    result = _result()
    wrong = {row["case_id"] for row in result["rows"] if not row["correct"]}

    assert wrong == {"ind-11", "ind-18"}


def test_both_wrong_cases_are_equivalent_judged_as_complementary() -> None:
    """错误的**方向**也要锁定：是把等义判成互补，不是判成无关。

    这个方向很重要：判成"无关"会漏掉合并机会；判成"互补"只是保守地
    保留了两条。后者更安全。
    """
    result = _result()
    wrong_rows = [row for row in result["rows"] if not row["correct"]]

    for row in wrong_rows:
        assert row["expected_decision"] == "NOOP"
        assert row["predicted"] == "complementary"
