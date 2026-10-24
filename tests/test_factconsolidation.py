"""FactConsolidation 适配器的行为契约。

真实数据形状（实测，2026-10-24 从 ai-hyz/MemoryAgentBench 下载）：
- 一个 parquet 有 8 行：{sh, mh} × {6k, 32k, 64k, 262k}
- 每行 `context` 是单个字符串，含 `0. ...` 到 `454. ...` 的编号事实
- `questions` 是 100 个字符串，`answers` 是 100 个字符串列表
- `metadata.qa_pair_ids` 形如 `factconsolidation_sh_6k_no0`
- `metadata.source` 形如 `factconsolidation_sh_6k`

关键点：事实的"新旧"由**编号**决定（编号越大越新），不是由列表位置或时间戳。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from evals.datasets.factconsolidation import (
    FactConsolidationAdapter,
    SubsetNotFoundError,
    parse_facts,
)

CONTEXT = """Here is a list of facts:
0. Amy Winehouse died in the city of Camden Town.
1. Hines Ward plays the position of wide receiver.
2. Amy Winehouse died in the city of London.
"""


def test_parse_facts_extracts_ordinal_and_text() -> None:
    """序号若被丢弃，就无法判断哪条更新——整个 resolver 的前提就没了。"""
    facts = parse_facts(CONTEXT)

    assert [fact.ordinal for fact in facts] == [0, 1, 2]
    assert facts[0].text == "Amy Winehouse died in the city of Camden Town."
    assert facts[2].text == "Amy Winehouse died in the city of London."


def test_parse_facts_ignores_header_line() -> None:
    """把 `Here is a list of facts:` 当事实会凭空多出一条。"""
    facts = parse_facts(CONTEXT)

    assert len(facts) == 3
    assert all("Here is a list" not in fact.text for fact in facts)


def test_parse_facts_is_monotonic() -> None:
    """序号必须严格递增，否则"取最大编号"这个策略无法实现。"""
    facts = parse_facts(CONTEXT)

    ordinals = [fact.ordinal for fact in facts]
    assert ordinals == sorted(ordinals)
    assert len(set(ordinals)) == len(ordinals)


def test_parse_facts_handles_empty_context() -> None:
    """空上下文返回空列表，而不是崩溃。"""
    assert parse_facts("") == []


def test_parse_facts_handles_multi_line_fact() -> None:
    """事实文本本身可能不含换行，但编号行之间可能夹空行，须跳过。"""
    facts = parse_facts("0. A.\n\n1. B.\n")

    assert [fact.text for fact in facts] == ["A.", "B."]


class _FakeTable:
    """最小化地模拟 pyarrow 读出的行结构。"""

    def __init__(self, rows: list[dict[str, object]]) -> None:
        self._rows = rows

    def to_pylist(self) -> list[dict[str, object]]:
        return self._rows


def _row(source: str, n_questions: int = 2) -> dict[str, object]:
    return {
        "context": CONTEXT,
        "questions": [f"q{i}" for i in range(n_questions)],
        "answers": [[f"a{i}"] for i in range(n_questions)],
        "metadata": {
            "qa_pair_ids": [f"{source}_no{i}" for i in range(n_questions)],
            "source": source,
            "question_types": None,
        },
    }


def _write_rows(path: Path, rows: list[dict[str, object]]) -> None:
    """用真实 parquet 写测试数据，避免 adapter 只对假对象工作。"""
    import pyarrow as pa
    import pyarrow.parquet as pq

    table = pa.Table.from_pylist(rows)
    pq.write_table(table, path)


@pytest.fixture
def dataset_file(tmp_path: Path) -> Path:
    path = tmp_path / "Conflict_Resolution.parquet"
    _write_rows(
        path,
        [
            _row("factconsolidation_sh_6k"),
            _row("factconsolidation_sh_32k"),
            _row("factconsolidation_mh_6k"),
        ],
    )
    return path


def test_load_selects_subset_by_length_and_hop(dataset_file: Path) -> None:
    """若筛选失效，跑 6K 会混进 32K 的样本，分数不可比。"""
    adapter = FactConsolidationAdapter(dataset_file)

    samples = adapter.load(length="6k", hop="sh")

    assert len(samples) == 1
    assert samples[0].source == "factconsolidation_sh_6k"
    assert len(samples[0].questions) == 2


def test_load_returns_questions_with_ids(dataset_file: Path) -> None:
    """qa_pair_id 是跨运行对齐结果的主键；丢了就无法做配对比较。"""
    adapter = FactConsolidationAdapter(dataset_file)

    sample = adapter.load(length="6k", hop="sh")[0]

    assert sample.questions[0].id == "factconsolidation_sh_6k_no0"
    assert sample.questions[0].question == "q0"
    assert sample.questions[0].answers == ["a0"]


def test_load_rejects_unknown_subset(dataset_file: Path) -> None:
    """返回空列表会让人以为"跑通了但没样本"，实际是配置错了。"""
    adapter = FactConsolidationAdapter(dataset_file)

    with pytest.raises(SubsetNotFoundError) as excinfo:
        adapter.load(length="8k", hop="sh")

    message = str(excinfo.value)
    assert "8k" in message
    assert "6k" in message, "错误信息必须列出可用子集"


def test_load_all_lengths(dataset_file: Path) -> None:
    """不传 length 时返回全部长度，用于批量跑分。"""
    adapter = FactConsolidationAdapter(dataset_file)

    samples = adapter.load(hop="sh")

    assert {sample.length for sample in samples} == {"6k", "32k"}


def test_facts_are_parsed_once_per_sample(dataset_file: Path) -> None:
    """每个样本 455 条事实，重复解析会让大子集慢到不可用。"""
    adapter = FactConsolidationAdapter(dataset_file)
    sample = adapter.load(length="6k", hop="sh")[0]

    assert sample.facts[0].ordinal == 0
    assert len(sample.facts) == 3


def test_missing_file_raises_with_download_hint(tmp_path: Path) -> None:
    """自动联网下载会让离线复现失败；只提示，不偷偷下载。"""
    with pytest.raises(FileNotFoundError) as excinfo:
        FactConsolidationAdapter(tmp_path / "nope.parquet")

    message = str(excinfo.value)
    assert "huggingface" in message.lower()
    assert ".parquet" in message


def test_real_dataset_shape_if_available() -> None:
    """对真实数据跑一遍结构断言；数据未下载时跳过。"""
    real = Path("data/raw/Conflict_Resolution.parquet")
    if not real.exists():
        pytest.skip("真实数据集未下载")

    adapter = FactConsolidationAdapter(real)
    samples = adapter.load(length="6k", hop="sh")

    assert len(samples) == 1
    sample = samples[0]
    assert len(sample.questions) == 100
    assert len(sample.facts) == 455
    assert sample.facts[-1].ordinal == 454
    # 至少有一条问题是非空字符串
    assert sample.questions[0].question.strip()


def test_jsonl_manifest_is_written_for_reproducibility(tmp_path: Path) -> None:
    """记录每个样本的 id 与事实数，方便与报告数字对账。"""
    path = tmp_path / "data.parquet"
    _write_rows(path, [_row("factconsolidation_sh_6k")])
    adapter = FactConsolidationAdapter(path)

    manifest = adapter.manifest(length="6k", hop="sh")

    parsed = json.loads(json.dumps(manifest))
    assert parsed["subsets"] == ["factconsolidation_sh_6k"]
    assert parsed["samples"] == 1
    assert parsed["questions"] == 2
