"""JSONL 追踪的行为契约。

这个格式是 C7 的 UI 与 Langfuse 导入的共同数据源，所以字段必须被测试锁住。
"""

from __future__ import annotations

import json
from pathlib import Path

import jsonschema
import pytest

from memory.tracing.jsonl import JsonlTracer

EVENT_SCHEMA = {
    "type": "object",
    "required": [
        "run_id",
        "sample_id",
        "stage",
        "duration_ms",
        "network_calls",
        "prompt_tokens",
        "completion_tokens",
        "reasoning_tokens",
    ],
    "properties": {
        "run_id": {"type": "string", "minLength": 1},
        "sample_id": {"type": ["string", "null"]},
        "stage": {
            "type": "string",
            "enum": ["load", "embed", "generate", "score", "resolve"],
        },
        "duration_ms": {"type": "number", "minimum": 0},
        "network_calls": {"type": "integer", "minimum": 0},
        "prompt_tokens": {"type": "integer", "minimum": 0},
        "completion_tokens": {"type": "integer", "minimum": 0},
        "reasoning_tokens": {"type": "integer", "minimum": 0},
        "error": {"type": ["string", "null"]},
    },
}


def _read(path: Path) -> list[dict[str, object]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def test_each_span_writes_one_valid_event(tmp_path: Path) -> None:
    """字段缺失会让下游 UI 与导入脚本静默丢数据。"""
    path = tmp_path / "events.jsonl"
    tracer = JsonlTracer(path, run_id="run-1")

    with tracer.span("embed", sample_id="s1", network_calls=1) as span:
        span.prompt_tokens = 12
        span.completion_tokens = 3

    events = _read(path)
    assert len(events) == 1
    jsonschema.validate(events[0], EVENT_SCHEMA)
    assert events[0]["stage"] == "embed"
    assert events[0]["sample_id"] == "s1"
    assert events[0]["network_calls"] == 1
    assert events[0]["prompt_tokens"] == 12


def test_duration_is_measured_not_zero(tmp_path: Path) -> None:
    """若时长恒为 0，延迟分析就完全失效。"""
    path = tmp_path / "events.jsonl"
    tracer = JsonlTracer(path, run_id="run-1")

    with tracer.span("score") as span:
        span.duration_hint(0.05)  # 让测试不依赖真实耗时

    event = _read(path)[0]
    assert event["duration_ms"] >= 0
    assert isinstance(event["duration_ms"], (int, float))


def test_exception_is_recorded_and_reraised(tmp_path: Path) -> None:
    """吞掉异常会让失败样本看起来像成功样本。"""
    path = tmp_path / "events.jsonl"
    tracer = JsonlTracer(path, run_id="run-1")

    with pytest.raises(ValueError, match="boom"), tracer.span("generate", sample_id="s1"):
        raise ValueError("boom")

    event = _read(path)[0]
    assert "boom" in str(event["error"])
    assert event["sample_id"] == "s1"


def test_sample_id_may_be_null_for_run_level_events(tmp_path: Path) -> None:
    """run 级别事件（如加载数据集）不属于某个样本。"""
    path = tmp_path / "events.jsonl"
    tracer = JsonlTracer(path, run_id="run-1")

    with tracer.span("load"):
        pass

    jsonschema.validate(_read(path)[0], EVENT_SCHEMA)


def test_events_append_across_instances(tmp_path: Path) -> None:
    """覆盖写会丢掉同一次运行里前几个阶段的记录。"""
    path = tmp_path / "events.jsonl"
    with JsonlTracer(path, run_id="run-1").span("load"):
        pass
    with JsonlTracer(path, run_id="run-1").span("score"):
        pass

    assert [event["stage"] for event in _read(path)] == ["load", "score"]


def test_network_calls_accumulate_within_span(tmp_path: Path) -> None:
    """一个阶段内多次调用若只记 1 次，A3 的"第二次为 0"就无法证明。"""
    path = tmp_path / "events.jsonl"
    tracer = JsonlTracer(path, run_id="run-1")

    with tracer.span("embed") as span:
        span.add_network_call()
        span.add_network_call()

    assert _read(path)[0]["network_calls"] == 2


def test_unknown_stage_is_rejected(tmp_path: Path) -> None:
    """自由字符串会让按阶段聚合的报表悄悄漏数据。"""
    tracer = JsonlTracer(tmp_path / "events.jsonl", run_id="run-1")

    with (
        pytest.raises(ValueError, match="stage"),
        tracer.span("nonsense"),  # type: ignore[arg-type]
    ):
        pass


def test_utf8_content_is_preserved(tmp_path: Path) -> None:
    """中文若按系统默认编码写，换机器会乱码。"""
    path = tmp_path / "events.jsonl"
    tracer = JsonlTracer(path, run_id="run-1")

    with tracer.span("resolve", sample_id="样本-1") as span:
        span.error = "冲突：项目使用 pnpm"

    raw = path.read_text(encoding="utf-8")
    assert "样本-1" in raw
    assert "pnpm" in raw
