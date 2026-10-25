"""C4 报告与结果 JSON 的一致性检查。

报告里的每个数字都必须能从 JSON 复算。此外锁定三个**不能漂移**的论断：

1. 三种池难度里只有最低的那种可评估
2. 五组权重分数完全相同（说明任务无区分度）
3. 等义类只有 2/4（未达标）
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
RESULTS = ROOT / "results"
REPORT = ROOT / "docs" / "reports" / "c4-retrieval.md"


def _load(name: str) -> dict[str, object]:
    path = RESULTS / name
    if not path.exists():
        pytest.skip(f"结果文件缺失：{name}")
    return json.loads(path.read_text(encoding="utf-8"))


def test_report_exists() -> None:
    assert REPORT.exists()


@pytest.mark.parametrize("split", ["dev", "test", "independent"])
def test_low_difficulty_pool_is_full_marks(split: str) -> None:
    """低难度池的 SEH 是 1.000。若变化说明池构造或召回被改动。"""
    payload = _load(f"retrieval-{split}-uniform-nodedup-poolunrelated.json")

    assert payload["seh_at_k"] == pytest.approx(1.0)
    assert payload["pool_mode"] == "unrelated"


def test_medium_and_high_difficulty_are_unevaluable() -> None:
    """这是报告第 2 节的核心结论：中高难度一条都评估不了。"""
    payload = _load("retrieval-independent-uniform-nodedup-poolsame_relation.json")

    assert payload["with_gold"] == 0
    assert payload["skipped_small_pool"] > 0


def test_all_five_weights_score_identically() -> None:
    """五组权重分数相同——说明低难度任务没有区分度可被权重影响。"""
    scores = []
    for name in (
        "uniform",
        "base_heavy",
        "cond_heavy",
        "auth_heavy",
        "status_only",
    ):
        payload = _load(f"retrieval-independent-{name}-nodedup-poolunrelated.json")
        scores.append(payload["seh_at_k"])

    assert len(set(scores)) == 1


def test_equivalence_by_label_matches_report() -> None:
    payload = _load("equivalence-classification.json")
    by_label = payload["by_label"]

    assert by_label["complementary"] == {"total": 6, "correct": 6}
    assert by_label["equivalent"] == {"total": 4, "correct": 2}


def test_equivalence_overall_accuracy() -> None:
    payload = _load("equivalence-classification.json")

    assert payload["accuracy"] == pytest.approx(0.8)


def test_report_states_the_limitation() -> None:
    """报告必须明确写出"满分不代表检索能力"，否则会被误读。"""
    text = REPORT.read_text(encoding="utf-8")

    assert "不能证明检索能力" in text
    assert "无关记忆" in text
    assert "28 个只出现 1 次" in text


def test_report_does_not_claim_retrieval_improvement() -> None:
    """报告不得宣称检索能力提升——当前数据不支持这个结论。"""
    text = REPORT.read_text(encoding="utf-8")

    assert "不宣称检索能力" in text or "不宣称检索能力提升" in text


def test_run_count_is_recorded() -> None:
    """运行次数必须可查，使"test 只跑一次"这类纪律可验证。"""
    path = RESULTS / "retrieval-run-count.json"
    if not path.exists():
        pytest.skip("运行计数文件不存在")

    counts = json.loads(path.read_text(encoding="utf-8"))
    assert counts
    assert all(isinstance(value, int) and value > 0 for value in counts.values())


def test_test_split_was_run_only_once() -> None:
    """`test` 是报告集，只应跑一次。

    实际守住了这一条。若有人为了看效果反复跑 test，这里会失败——
    那意味着报告里的数字可以被反复挑选，失去预注册的意义。
    """
    path = RESULTS / "retrieval-run-count.json"
    if not path.exists():
        pytest.skip("运行计数文件不存在")

    counts = json.loads(path.read_text(encoding="utf-8"))
    test_runs = {k: v for k, v in counts.items() if k.startswith("retrieval-test-")}

    assert test_runs
    assert all(value == 1 for value in test_runs.values()), (
        f"test 集被运行了多次：{test_runs}"
    )


def test_report_discloses_the_independent_split_deviation() -> None:
    """`independent` 被跑了多次并据此改了评测框架，这条必须留在报告里。

    这不是可以省略的细节：它是一次真实的方法泄露，
    即使对分数没有影响，也必须可追溯。
    """
    text = REPORT.read_text(encoding="utf-8")

    assert "实验纪律" in text
    assert "偏差" in text
    assert "independent" in text
