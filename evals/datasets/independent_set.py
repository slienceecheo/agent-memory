"""独立来源场景集：schema 与加载。

与此前 60 条的关键差别：**这批场景由第三方独立编写**，
包括标注（expected）也是他的判断。因此它是本项目第一个能测出真实泛化能力的集合。

三条不能违反的纪律：

1. **不在这批数据上调规则**。它是 held-out。
   若发现规则错了，只记录，不改规则——否则就变成"看着测试集调参"。
2. **`existing_authority` 必须显式给出**。
   此前 `_seed_existing` 硬编码 existing 为 user_direct，
   导致"第三方转述 vs 第三方转述"被误判成"低权威 vs 高权威"。
3. **`condition` 由人工从原文提取**。C3 不做条件抽取，
   若不给显式 condition，BRANCH 场景会被判成 SUPERSEDE。
   这一点必须在报告里注明，否则会高估系统能力。
"""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from memory.resolver.rules import DecisionKind
from memory.store.models import Authority

INDEPENDENT_FILE = "independent.jsonl"

_CONFIDENCE = ("确定", "不太确定")


class InvalidIndependentCase(ValueError):
    """字段缺失或非法。"""


@dataclass(frozen=True, slots=True)
class IndependentCase:
    id: str
    text: str
    subject: str
    relation: str
    candidate_value: str
    existing_value: str | None
    expected: DecisionKind
    authority: Authority
    existing_authority: Authority
    condition: str | None = None
    existing_condition: str | None = None
    rationale: str = ""
    confidence: str = "确定"
    source: str = "friend"


@dataclass(frozen=True, slots=True)
class IndependentSet:
    cases: tuple[IndependentCase, ...]

    def __len__(self) -> int:
        return len(self.cases)

    def class_counts(self) -> dict[DecisionKind, int]:
        counts = Counter(case.expected for case in self.cases)
        return {kind: counts.get(kind, 0) for kind in DecisionKind}

    def with_condition_extracted(self) -> IndependentSet:
        """返回只含"条件已显式给出"的子集。

        用于分离两个问题：判定逻辑错，还是条件抽取缺失。
        """
        return IndependentSet(tuple(c for c in self.cases if c.condition is not None))

    def without_condition_requirement(self) -> IndependentSet:
        """排除所有需要条件抽取才能正确判定的场景。

        在这些场景上，C3 的表现才是"判定逻辑本身"的表现。
        """
        needs_condition = {c.id for c in self.cases if c.condition is not None}
        return IndependentSet(tuple(c for c in self.cases if c.id not in needs_condition))


def _require(raw: dict[str, object], name: str, *, where: str) -> object:
    if name not in raw:
        raise InvalidIndependentCase(f"{where} 缺少字段 {name}")
    return raw[name]


def _enum(value: object, enum_type: object, *, where: str, name: str) -> object:
    try:
        return enum_type(value)  # type: ignore[operator]
    except ValueError as exc:
        raise InvalidIndependentCase(f"{where} 字段 {name} 非法：{value!r}") from exc


def parse_independent_case(raw: dict[str, object], *, where: str) -> IndependentCase:
    confidence = str(raw.get("confidence") or "确定")
    if confidence not in _CONFIDENCE:
        raise InvalidIndependentCase(
            f"{where} confidence 只能是 {'/'.join(_CONFIDENCE)}，收到 {confidence!r}"
        )

    existing = raw.get("existing_value")
    return IndependentCase(
        id=str(_require(raw, "id", where=where)),
        text=str(_require(raw, "text", where=where)),
        subject=str(_require(raw, "subject", where=where)),
        relation=str(_require(raw, "relation", where=where)),
        candidate_value=str(_require(raw, "candidate_value", where=where)),
        existing_value=None if existing in (None, "") else str(existing),
        expected=_enum(
            _require(raw, "expected", where=where),
            DecisionKind,
            where=where,
            name="expected",
        ),  # type: ignore[arg-type]
        authority=_enum(
            raw.get("authority") or "user_direct",
            Authority,
            where=where,
            name="authority",
        ),  # type: ignore[arg-type]
        existing_authority=_enum(
            raw.get("existing_authority") or "user_direct",
            Authority,
            where=where,
            name="existing_authority",
        ),  # type: ignore[arg-type]
        condition=_opt(raw.get("condition")),
        existing_condition=_opt(raw.get("existing_condition")),
        rationale=str(raw.get("rationale") or ""),
        confidence=confidence,
        source=str(raw.get("source") or "friend"),
    )


def _opt(value: object) -> str | None:
    if value in (None, ""):
        return None
    return str(value)


def load_independent_set(path: Path | str) -> IndependentSet:
    source = Path(path)
    if not source.exists():
        raise FileNotFoundError(f"找不到独立场景集：{source}")

    cases: list[IndependentCase] = []
    seen: set[str] = set()
    for number, line in enumerate(source.read_text(encoding="utf-8").splitlines(), start=1):
        stripped = line.strip()
        if not stripped:
            continue
        try:
            raw = json.loads(stripped)
        except json.JSONDecodeError as exc:
            raise InvalidIndependentCase(f"{source.name}:{number} 不是合法 JSON") from exc
        case = parse_independent_case(raw, where=f"{source.name}:{number}")
        if case.id in seen:
            raise InvalidIndependentCase(f"{source.name}:{number} 重复 id：{case.id}")
        seen.add(case.id)
        cases.append(case)

    return IndependentSet(tuple(cases))
