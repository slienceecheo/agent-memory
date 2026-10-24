"""FactConsolidation 适配器。

真实数据形状（2026-10-24 实测）：
- 一个 parquet 含 8 行：{sh, mh} × {6k, 32k, 64k, 262k}
- 每行 `context` 是一段文本，编号事实形如 `0. ...` 到 `454. ...`
- `questions` 100 条，`answers` 是 100 个字符串**列表**
- `metadata.qa_pair_ids` 形如 `factconsolidation_sh_6k_no0`

设计取舍：
- 编号即"新旧"，不需要解析时间。这正是本项目"确定性裁决"主张的落点。
- 每条事实只解析一次并挂在 sample 上，大子集有 455 条事实、100 个问题。
- 数据缺失时**不自动下载**，只报错并给出地址，保证离线可复现。
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

Length = Literal["6k", "32k", "64k", "262k"]
Hop = Literal["sh", "mh"]

_FACT_PATTERN = re.compile(r"^(\d+)\.\s+(.*\S)\s*$")
_KNOWN_LENGTHS: tuple[Length, ...] = ("6k", "32k", "64k", "262k")
_DOWNLOAD_HINT = (
    "请从 https://huggingface.co/datasets/ai-hyz/MemoryAgentBench 下载 "
    "data/Conflict_Resolution-00000-of-00001.parquet，"
    "保存为 data/raw/Conflict_Resolution.parquet。"
)


class SubsetNotFoundError(LookupError):
    """请求的子集在数据集中不存在。"""


@dataclass(frozen=True, slots=True)
class Fact:
    ordinal: int
    text: str


@dataclass(frozen=True, slots=True)
class Question:
    id: str
    question: str
    answers: list[str]


@dataclass(frozen=True, slots=True)
class Sample:
    source: str
    length: Length
    hop: Hop
    facts: list[Fact]
    questions: list[Question]


def parse_facts(context: str) -> list[Fact]:
    """从 context 文本中抽出编号事实。

    只接受 `<数字>. <文本>` 的行；表头与空行被忽略。
    """
    facts: list[Fact] = []
    for line in context.splitlines():
        match = _FACT_PATTERN.match(line.strip())
        if match is None:
            continue
        facts.append(Fact(ordinal=int(match.group(1)), text=match.group(2)))
    return facts


def _parse_source(source: str) -> tuple[Hop, Length]:
    """`factconsolidation_sh_6k` → ("sh", "6k")。

    注意 `factconsolidation` 本身不含下划线，所以 split 后是 3 段而不是 4 段。
    """
    parts = source.split("_")
    if len(parts) < 3:
        raise SubsetNotFoundError(f"无法解析 source 字段：{source!r}")
    hop = parts[-2]
    length = parts[-1]
    if hop not in ("sh", "mh") or length not in _KNOWN_LENGTHS:
        raise SubsetNotFoundError(f"无法解析 source 字段：{source!r}")
    return hop, length


class FactConsolidationAdapter:
    def __init__(self, path: Path | str) -> None:
        self._path = Path(path)
        if not self._path.exists():
            raise FileNotFoundError(f"找不到数据集文件：{self._path}\n{_DOWNLOAD_HINT}")

    def _rows(self) -> list[dict[str, object]]:
        import pyarrow.parquet as pq

        return list(pq.read_table(self._path).to_pylist())

    def load(
        self, *, length: Length | None = None, hop: Hop | None = None
    ) -> list[Sample]:
        samples: list[Sample] = []
        for row in self._rows():
            sample = self._to_sample(row)
            if length is not None and sample.length != length:
                continue
            if hop is not None and sample.hop != hop:
                continue
            samples.append(sample)

        if not samples:
            available = sorted(
                {self._to_sample(row).source for row in self._rows()}
            )
            raise SubsetNotFoundError(
                f"没有匹配的子集（length={length!r}, hop={hop!r}）。"
                f"可用子集：{', '.join(available)}"
            )
        return samples

    def manifest(
        self, *, length: Length | None = None, hop: Hop | None = None
    ) -> dict[str, object]:
        samples = self.load(length=length, hop=hop)
        return {
            "dataset": str(self._path.name),
            "subsets": [sample.source for sample in samples],
            "samples": len(samples),
            "questions": sum(len(sample.questions) for sample in samples),
            "facts": sum(len(sample.facts) for sample in samples),
        }

    def _to_sample(self, row: dict[str, object]) -> Sample:
        metadata = row.get("metadata") or {}
        if not isinstance(metadata, dict):
            raise SubsetNotFoundError("metadata 字段结构异常")
        source = str(metadata.get("source") or "")
        hop, length = _parse_source(source)

        context = row.get("context")
        questions_raw = row.get("questions")
        answers_raw = row.get("answers")
        ids_raw = metadata.get("qa_pair_ids")
        if not isinstance(context, str):
            raise SubsetNotFoundError(f"{source}: context 不是字符串")
        if not isinstance(questions_raw, list) or not isinstance(answers_raw, list):
            raise SubsetNotFoundError(f"{source}: questions/answers 不是列表")
        if not isinstance(ids_raw, list):
            raise SubsetNotFoundError(f"{source}: qa_pair_ids 不是列表")

        questions = [
            Question(
                id=str(ids_raw[index]),
                question=str(question),
                answers=[str(item) for item in _as_list(answers_raw[index])],
            )
            for index, question in enumerate(questions_raw)
        ]
        return Sample(
            source=source,
            length=length,
            hop=hop,
            facts=parse_facts(context),
            questions=questions,
        )


def _as_list(value: object) -> list[object]:
    return list(value) if isinstance(value, list) else [value]


def iter_questions(samples: list[Sample]) -> Iterator[tuple[Sample, Question]]:
    for sample in samples:
        for question in sample.questions:
            yield sample, question
