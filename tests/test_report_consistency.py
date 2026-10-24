"""报告与结果 JSON 的一致性检查。

存在的意义：报告是手写的，JSON 是程序产出的。两者不一致时，
报告就是错的——而错误的数字比没有数字更糟。

这不是一个"能跑就行"的脚本，是 CI 门禁的一部分。
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / "results"
REPORT = ROOT / "docs" / "reports" / "c1-baselines.md"

BASELINES = ("no-memory", "naive-rag", "full-context")


def _load(name: str) -> dict[str, object]:
    path = RESULTS / f"{name}-6k-sh.json"
    if not path.exists():
        pytest.skip(f"结果文件缺失：{path}")
    return json.loads(path.read_text(encoding="utf-8"))


def _accuracy(payload: dict[str, object]) -> float:
    samples = payload["samples"]
    assert isinstance(samples, list)
    answered = [s for s in samples if s.get("error") is None]
    return sum(1 for s in answered if s.get("correct")) / len(answered)


def _is_multi_answer(prediction: str) -> bool:
    """粗略判定"同时给出多个候选值"。

    与报告里手工统计的口径一致：出现 and/or 连接词，或带逗号的复合短语。
    """
    if not prediction:
        return False
    if re.search(r"\b(and|or)\b", prediction, re.IGNORECASE):
        return True
    stripped = prediction.strip().rstrip(".")
    return "," in stripped and len(stripped) > 25


def test_report_numbers_match_result_json() -> None:
    """报告里手写的百分比若与 JSON 不符，说明报告没跟着重跑更新。"""
    if not REPORT.exists():
        pytest.skip("报告尚未生成")

    report = REPORT.read_text(encoding="utf-8")

    for name in BASELINES:
        payload = _load(name)
        accuracy = _accuracy(payload) * 100
        # 报告里每个基线那一行必须出现对应的百分比（保留一位小数）
        needle = f"{accuracy:.1f}%"
        assert needle in report, (
            f"报告中找不到 {name} 的准确率 {needle}；"
            f"JSON 实际值 {accuracy:.4f}%。报告需要重跑更新。"
        )


def test_sample_count_matches() -> None:
    """n 写错会让置信区间完全失真。"""
    for name in BASELINES:
        payload = _load(name)
        assert len(payload["samples"]) == 100, f"{name} 的样本数不是 100"


def test_multi_answer_share_matches_report_claim() -> None:
    """报告声称 naive-rag 的 87% 里 65 个百分点来自多答案；这里核对。"""
    payload = _load("naive-rag")
    samples = payload["samples"]
    correct = [s for s in samples if s.get("correct")]
    correct_multi = [s for s in correct if _is_multi_answer(s.get("prediction", ""))]
    assert len(correct_multi) == 65, (
        f"多答案命中数实际为 {len(correct_multi)}，报告写的是 65"
    )


def test_correct_single_answer_count_matches_report() -> None:
    """报告写"只给单一答案且答对"是 22 题；这是拆解表的另一半。"""
    payload = _load("naive-rag")
    samples = payload["samples"]
    correct_single = [
        s
        for s in samples
        if s.get("correct") and not _is_multi_answer(s.get("prediction", ""))
    ]
    assert len(correct_single) == 22, (
        f"单答案命中数实际为 {len(correct_single)}，报告写的是 22"
    )


def test_single_answer_accuracy_matches_report() -> None:
    """只给单一答案时的准确率是报告的核心论点，必须可复算。"""
    payload = _load("naive-rag")
    single = [s for s in payload["samples"] if not _is_multi_answer(s.get("prediction", ""))]
    assert len(single) == 35, f"单答案样本数实际为 {len(single)}，报告写的是 35"
    accuracy = sum(1 for s in single if s.get("correct")) / len(single)
    assert round(accuracy * 100, 1) == 62.9, f"单答案准确率实际为 {accuracy:.4f}"
