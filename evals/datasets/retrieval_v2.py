"""检索数据集 v2：schema 与加载。

协议：`docs/requirements/retrieval-dataset-v2.md`（tag `dataset-v2-protocol`）。

与 C4 旧集的三处结构性差别，每一处都对应一个已记录的缺陷：

1. **记忆库与查询分离**（不是"一条场景自带一条 gold"）。
   C4 的池只能从别处凑，且用的是文件顺序前缀（缺陷 5）。
2. **每条记忆都有 `memory_text`**（产生它的原话）。
   C4 的干扰项 `text=None`，物理上无法参与词面竞争（缺陷 2）。
3. **`query` 与 `memory_text` 必须不同**，且 `query` 是问句。
   C4 的 `query = row["text"]`，查询就是答案本身（缺陷 1）。
"""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from memory.store.models import Authority, Status

SCHEMA_VERSION = 2


class InvalidDataset(ValueError):
    """字段缺失、取值非法或跨文件引用错误。"""


class Axis(StrEnum):
    A = "A"
    C = "C"
    MIXED = "mixed"


class CueType(StrEnum):
    """A 轴难度的真正来源：条件是被命名还是被推断。"""

    EXPLICIT = "explicit"
    IMPLICIT = "implicit"


class BranchNature(StrEnum):
    """分支是天然的，还是为了凑数编造的。"""

    NATURAL = "natural"
    FORCED = "forced"


class Author(StrEnum):
    PRIMARY = "primary"
    INDEPENDENT = "independent"


@dataclass(frozen=True, slots=True)
class Memory:
    memory_id: str
    subject: str
    relation: str
    value: str
    memory_text: str
    authority: Authority
    status: Status
    branch_nature: BranchNature
    valid_from: str
    condition: str | None = None
    supersedes: str | None = None


@dataclass(frozen=True, slots=True)
class Query:
    query_id: str
    query: str
    subject: str
    axis: Axis
    cue_type: CueType
    gold_memory_id: str
    expected_value: str
    author: Author
    query_condition: str | None = None


@dataclass(frozen=True, slots=True)
class Dataset:
    memories: tuple[Memory, ...]
    queries: tuple[Query, ...]

    def by_subject(self, subject: str) -> tuple[Memory, ...]:
        return tuple(m for m in self.memories if m.subject == subject)

    def memory(self, memory_id: str) -> Memory:
        for item in self.memories:
            if item.memory_id == memory_id:
                return item
        raise InvalidDataset(f"找不到记忆 {memory_id!r}")

    def subjects(self) -> tuple[str, ...]:
        seen: list[str] = []
        for item in self.memories:
            if item.subject not in seen:
                seen.append(item.subject)
        return tuple(seen)

    def cue_type_counts(self) -> dict[str, int]:
        counted = Counter(q.cue_type.value for q in self.queries)
        return {kind.value: counted.get(kind.value, 0) for kind in CueType}

    def forced_subject_ratio(self) -> float:
        """`forced` 的 subject 占比。按 subject 计，不按条目计。"""
        forced: set[str] = set()
        all_subjects = set(self.subjects())
        for subject in all_subjects:
            if all(m.branch_nature is BranchNature.FORCED for m in self.by_subject(subject)):
                forced.add(subject)
        return len(forced) / len(all_subjects) if all_subjects else 0.0


def _require(raw: dict[str, object], name: str, *, where: str) -> object:
    """取必填字段。纯空白也算缺失——L4 要的是"非空"，不是"键存在"。"""
    if name not in raw or raw[name] is None:
        raise InvalidDataset(f"{where} 缺少字段 {name}")
    value = raw[name]
    if isinstance(value, str) and not value.strip():
        raise InvalidDataset(f"{where} 字段 {name} 为空白，等同于缺失")
    return value


def _enum(value: object, enum_type: object, *, where: str, name: str) -> object:
    try:
        return enum_type(value)  # type: ignore[operator]
    except ValueError as exc:
        raise InvalidDataset(f"{where} 字段 {name} 非法：{value!r}") from exc


def _opt(value: object) -> str | None:
    if value in (None, ""):
        return None
    return str(value)


def parse_memory(raw: dict[str, object], *, where: str) -> Memory:
    return Memory(
        memory_id=str(_require(raw, "memory_id", where=where)),
        subject=str(_require(raw, "subject", where=where)),
        relation=str(_require(raw, "relation", where=where)),
        value=str(_require(raw, "value", where=where)),
        # L4：每条记忆都必须有原文。空值在这里就拒绝，而不是等到评测时才发现。
        memory_text=str(_require(raw, "memory_text", where=where)),
        authority=_enum(
            _require(raw, "authority", where=where), Authority, where=where, name="authority"
        ),  # type: ignore[arg-type]
        status=_enum(
            raw.get("status") or "ACTIVE", Status, where=where, name="status"
        ),  # type: ignore[arg-type]
        branch_nature=_enum(
            _require(raw, "branch_nature", where=where),
            BranchNature,
            where=where,
            name="branch_nature",
        ),  # type: ignore[arg-type]
        valid_from=str(_require(raw, "valid_from", where=where)),
        condition=_opt(raw.get("condition")),
        supersedes=_opt(raw.get("supersedes")),
    )


def parse_query(raw: dict[str, object], *, where: str) -> Query:
    return Query(
        query_id=str(_require(raw, "query_id", where=where)),
        query=str(_require(raw, "query", where=where)),
        subject=str(_require(raw, "subject", where=where)),
        axis=_enum(_require(raw, "axis", where=where), Axis, where=where, name="axis"),  # type: ignore[arg-type]
        cue_type=_enum(
            _require(raw, "cue_type", where=where), CueType, where=where, name="cue_type"
        ),  # type: ignore[arg-type]
        gold_memory_id=str(_require(raw, "gold_memory_id", where=where)),
        expected_value=str(_require(raw, "expected_value", where=where)),
        author=_enum(
            _require(raw, "author", where=where), Author, where=where, name="author"
        ),  # type: ignore[arg-type]
        query_condition=_opt(raw.get("query_condition")),
    )


def _load_jsonl(path: Path) -> list[dict[str, object]]:
    if not path.exists():
        raise FileNotFoundError(f"找不到数据文件：{path}")
    rows: list[dict[str, object]] = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        stripped = line.strip()
        if not stripped:
            continue
        try:
            rows.append(json.loads(stripped))
        except json.JSONDecodeError as exc:
            raise InvalidDataset(f"{path.name}:{number} 不是合法 JSON") from exc
    return rows


def load_dataset(directory: Path | str) -> Dataset:
    """加载并校验一个 v2 数据集目录。"""
    root = Path(directory)
    memories = tuple(
        parse_memory(raw, where=f"memories.jsonl:{index}")
        for index, raw in enumerate(_load_jsonl(root / "memories.jsonl"), start=1)
    )
    queries = tuple(
        parse_query(raw, where=f"queries.jsonl:{index}")
        for index, raw in enumerate(_load_jsonl(root / "queries.jsonl"), start=1)
    )

    seen: set[str] = set()
    for item in memories:
        if item.memory_id in seen:
            raise InvalidDataset(f"重复的 memory_id：{item.memory_id}")
        seen.add(item.memory_id)

    for query in queries:
        if query.gold_memory_id not in seen:
            raise InvalidDataset(
                f"{query.query_id} 的 gold_memory_id {query.gold_memory_id!r} 不在记忆库中"
            )

    return Dataset(memories=memories, queries=queries)


__all__ = [
    "SCHEMA_VERSION",
    "Author",
    "Axis",
    "BranchNature",
    "CueType",
    "Dataset",
    "InvalidDataset",
    "Memory",
    "Query",
    "load_dataset",
    "parse_memory",
    "parse_query",
]
