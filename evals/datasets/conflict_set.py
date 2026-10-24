"""场景集的数据模型与加载。

设计要点：

- 每条带 `label_status`：`proposed`（脚本生成）或 `confirmed`（人工确认）。
  **指标只在 confirmed 上用**，避免"用规则生成的标签测规则"的循环论证。
- 六类分布要均衡：某类只有 1 条样本时，macro-F1 的方差会让结论毫无意义。
- 缺字段、非法类别、重复 id 一律拒绝加载，而不是跳过——
  静默跳过会让"60 条里有 8 条没被统计"这种事没人发现。
"""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from memory.resolver.rules import DecisionKind

LabelStatus = Literal["proposed", "confirmed"]

_REQUIRED_FIELDS = (
    "id",
    "text",
    "subject",
    "relation",
    "candidate_value",
    "existing_value",
    "expected",
    "label_status",
)

_MIN_PER_CLASS = 2


class InvalidCase(ValueError):
    """场景字段缺失或非法。"""


class DuplicateCaseId(ValueError):
    """场景 id 重复。"""


@dataclass(frozen=True, slots=True)
class ConflictCase:
    id: str
    text: str
    subject: str
    relation: str
    candidate_value: str
    existing_value: str | None
    expected: DecisionKind
    label_status: LabelStatus
    condition: str | None = None
    existing_condition: str | None = None
    authority: str = "user_direct"
    note: str = ""
    labeler: str | None = None
    confirmed_at: str | None = None


@dataclass(frozen=True, slots=True)
class ConflictSet:
    cases: tuple[ConflictCase, ...] = field(default_factory=tuple)

    def __len__(self) -> int:
        return len(self.cases)

    def confirmed(self) -> ConflictSet:
        return ConflictSet(tuple(c for c in self.cases if c.label_status == "confirmed"))

    def proposed(self) -> ConflictSet:
        return ConflictSet(tuple(c for c in self.cases if c.label_status == "proposed"))

    def class_counts(self) -> dict[DecisionKind, int]:
        counts = Counter(case.expected for case in self.cases)
        return {kind: counts.get(kind, 0) for kind in DecisionKind}

    def min_class_count(self) -> int:
        counts = self.class_counts()
        present = [value for value in counts.values() if value > 0]
        return min(present) if present else 0

    def is_balanced(self, *, minimum: int = _MIN_PER_CLASS) -> bool:
        """六类是否都至少有 `minimum` 条样本。

        不均衡不会阻止加载，但会让报告标注"结论强度受限"。
        """
        counts = self.class_counts()
        return all(count >= minimum for count in counts.values())

    def with_case(self, updated: ConflictCase) -> ConflictSet:
        replaced = tuple(updated if case.id == updated.id else case for case in self.cases)
        return ConflictSet(replaced)


def _parse_case(raw: dict[str, object], *, source: Path, line_number: int) -> ConflictCase:
    for field_name in _REQUIRED_FIELDS:
        if field_name not in raw:
            raise InvalidCase(
                f"{source.name}:{line_number} 缺少字段 {field_name}"
            )

    expected_raw = str(raw["expected"])
    try:
        expected = DecisionKind(expected_raw)
    except ValueError as exc:
        allowed = ", ".join(kind.value for kind in DecisionKind)
        raise InvalidCase(
            f"{source.name}:{line_number} expected 非法：{expected_raw!r}，可用值：{allowed}"
        ) from exc

    status_raw = str(raw["label_status"])
    if status_raw not in ("proposed", "confirmed"):
        raise InvalidCase(
            f"{source.name}:{line_number} label_status 非法：{status_raw!r}，"
            "只能是 proposed 或 confirmed"
        )

    labeler = raw.get("labeler")
    if status_raw == "confirmed" and not labeler:
        raise InvalidCase(
            f"{source.name}:{line_number} 已确认的条目必须记录 labeler，"
            "否则双人一致性无法计算"
        )

    existing_value = raw["existing_value"]
    return ConflictCase(
        id=str(raw["id"]),
        text=str(raw["text"]),
        subject=str(raw["subject"]),
        relation=str(raw["relation"]),
        candidate_value=str(raw["candidate_value"]),
        existing_value=None if existing_value is None else str(existing_value),
        expected=expected,
        label_status=status_raw,  # type: ignore[arg-type]
        condition=_opt_str(raw.get("condition")),
        existing_condition=_opt_str(raw.get("existing_condition")),
        authority=str(raw.get("authority") or "user_direct"),
        note=str(raw.get("note") or ""),
        labeler=str(labeler) if labeler else None,
        confirmed_at=_opt_str(raw.get("confirmed_at")),
    )


def _opt_str(value: object) -> str | None:
    if value is None:
        return None
    text = str(value)
    return text if text else None


def load_conflict_set(path: Path | str) -> ConflictSet:
    source = Path(path)
    if not source.exists():
        raise FileNotFoundError(
            f"找不到场景集：{source}\n"
            "场景集位于 data/conflict-set/，可用 `python -m evals.tools.label list` 查看。"
        )

    cases: list[ConflictCase] = []
    seen: set[str] = set()
    for line_number, line in enumerate(
        source.read_text(encoding="utf-8").splitlines(), start=1
    ):
        stripped = line.strip()
        if not stripped:
            continue
        try:
            raw = json.loads(stripped)
        except json.JSONDecodeError as exc:
            raise InvalidCase(f"{source.name}:{line_number} 不是合法 JSON") from exc
        case = _parse_case(raw, source=source, line_number=line_number)
        if case.id in seen:
            raise DuplicateCaseId(f"{source.name}:{line_number} 重复的 id：{case.id}")
        seen.add(case.id)
        cases.append(case)

    return ConflictSet(tuple(cases))


def save_conflict_set(dataset: ConflictSet, path: Path | str) -> None:
    """按 id 排序后写回，保证 diff 稳定。"""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    lines = []
    for case in sorted(dataset.cases, key=lambda item: item.id):
        lines.append(json.dumps(_case_to_dict(case), ensure_ascii=False))
    target.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _case_to_dict(case: ConflictCase) -> dict[str, object]:
    payload: dict[str, object] = {
        "id": case.id,
        "text": case.text,
        "subject": case.subject,
        "relation": case.relation,
        "candidate_value": case.candidate_value,
        "existing_value": case.existing_value,
        "expected": case.expected.value,
        "label_status": case.label_status,
    }
    if case.condition is not None:
        payload["condition"] = case.condition
    if case.existing_condition is not None:
        payload["existing_condition"] = case.existing_condition
    if case.authority != "user_direct":
        payload["authority"] = case.authority
    if case.note:
        payload["note"] = case.note
    if case.labeler:
        payload["labeler"] = case.labeler
    if case.confirmed_at:
        payload["confirmed_at"] = case.confirmed_at
    return payload
