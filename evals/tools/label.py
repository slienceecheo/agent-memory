"""标注工具：列出、确认、计算一致性。

    uv run python -m evals.tools.label list [--status proposed]
    uv run python -m evals.tools.label confirm --id dev-sup-01 --label SUPERSEDE --labeler alice
    uv run python -m evals.tools.label kappa --a alice --b bob

为什么是脚本而不是表格：标签必须能追溯到"谁在什么时候确认的"。
CSV 手工编辑会丢失这个信息，也会让"改了但没记录"变得无法发现。
"""

from __future__ import annotations

import argparse
import sys
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

from evals.datasets.conflict_set import (
    ConflictCase,
    ConflictSet,
    load_conflict_set,
    save_conflict_set,
)
from memory.resolver.rules import DecisionKind

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SET = ROOT / "data" / "conflict-set"


def list_cases(path: Path | str, *, status: str | None = None) -> list[ConflictCase]:
    dataset = load_conflict_set(path)
    if status is None:
        return list(dataset.cases)
    return [case for case in dataset.cases if case.label_status == status]


def _validate_label(label: str) -> DecisionKind:
    try:
        return DecisionKind(label.upper())
    except ValueError as exc:
        allowed = ", ".join(kind.value for kind in DecisionKind)
        raise ValueError(f"非法标签 {label!r}，可用值：{allowed}") from exc


def update_label(
    path: Path | str,
    *,
    case_id: str,
    label: str,
    labeler: str,
    at: str | None = None,
    status: str = "confirmed",
) -> ConflictCase:
    """修改一条场景的期望标签与状态，保持其余条目不变。"""
    if not labeler.strip():
        raise ValueError("labeler 不能为空：没有确认者就无法计算一致性")

    dataset = load_conflict_set(path)
    target = next((case for case in dataset.cases if case.id == case_id), None)
    if target is None:
        raise KeyError(f"找不到场景 {case_id}")

    import dataclasses

    updated = dataclasses.replace(
        target,
        expected=_validate_label(label),
        label_status=status,  # type: ignore[arg-type]
        labeler=labeler.strip(),
        confirmed_at=at or datetime.now(UTC).isoformat(timespec="seconds"),
    )
    save_conflict_set(dataset.with_case(updated), path)
    return updated


def confirm_case(
    path: Path | str,
    *,
    case_id: str,
    label: str,
    labeler: str,
    at: str | None = None,
) -> ConflictCase:
    return update_label(
        path, case_id=case_id, label=label, labeler=labeler, at=at, status="confirmed"
    )


def cohen_kappa(labels_a: list[str], labels_b: list[str]) -> float:
    """把"是否一致"折成二分类后计算 Cohen's κ。

    对多类别 κ 而言，本研究关心的是"人工确认与提案是否一致"，
    因此按"完全一致 / 不一致"二分类统计即可，避免类别过多导致 κ 不稳定。
    """
    if len(labels_a) != len(labels_b):
        raise ValueError(f"两组标签长度不一致：{len(labels_a)} vs {len(labels_b)}")
    if not labels_a:
        raise ValueError("两组标签都为空，无法计算 κ")

    total = len(labels_a)
    agree = sum(1 for a, b in zip(labels_a, labels_b, strict=True) if a == b)
    p_observed = agree / total

    counts_a = Counter(labels_a)
    counts_b = Counter(labels_b)
    p_expected = sum(
        (counts_a[key] / total) * (counts_b[key] / total) for key in set(counts_a) | set(counts_b)
    )

    if p_expected == 1.0:
        # 两者都只给同一个标签：观察与期望都完全一致，κ 定义为 1
        return 1.0
    return (p_observed - p_expected) / (1.0 - p_expected)


def _dataset_path(split: str) -> Path:
    return DEFAULT_SET / f"{split}.jsonl"


def _cmd_list(args: argparse.Namespace) -> int:
    path = _dataset_path(args.split)
    cases = list_cases(path, status=args.status)
    for case in cases:
        marker = "✓" if case.label_status == "confirmed" else "?"
        print(
            f"{marker} {case.id:<16} expected={case.expected.value:<10} "
            f"text={case.text[:50]}"
        )
    print(f"\n共 {len(cases)} 条")
    return 0


def _cmd_confirm(args: argparse.Namespace) -> int:
    path = _dataset_path(args.split)
    case = confirm_case(
        path, case_id=args.id, label=args.label, labeler=args.labeler
    )
    print(f"已确认 {case.id} → {case.expected.value}（{case.labeler}）")
    return 0


def _cmd_kappa(args: argparse.Namespace) -> int:
    path = _dataset_path(args.split)
    dataset = load_conflict_set(path)
    by_labeler: dict[str, dict[str, str]] = {}
    for case in dataset.cases:
        if case.labeler and case.label_status == "confirmed":
            by_labeler.setdefault(case.labeler, {})[case.id] = case.expected.value

    if args.a not in by_labeler or args.b not in by_labeler:
        print(
            f"缺少标注者数据。已记录：{', '.join(by_labeler) or '无'}",
            file=sys.stderr,
        )
        return 2

    shared = sorted(set(by_labeler[args.a]) & set(by_labeler[args.b]))
    if not shared:
        print("两名标注者没有共同标注的条目", file=sys.stderr)
        return 2

    value = cohen_kappa(
        [by_labeler[args.a][key] for key in shared],
        [by_labeler[args.b][key] for key in shared],
    )
    print(f"共同条目 {len(shared)} 条，Cohen's κ = {value:.3f}")
    if value < 0.7:
        print("κ < 0.7：标签一致性不足，结论强度受限。", file=sys.stderr)
        return 1
    return 0


def _cmd_summary(args: argparse.Namespace) -> int:
    path = _dataset_path(args.split)
    dataset: ConflictSet = load_conflict_set(path)
    counts = dataset.class_counts()
    confirmed = dataset.confirmed()
    print(f"{args.split}: {len(dataset)} 条，已确认 {len(confirmed)} 条")
    for kind, count in counts.items():
        print(f"  {kind.value:<10} {count}")
    print(f"均衡：{dataset.is_balanced()}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="evals.tools.label", description="冲突场景标注工具")
    parser.add_argument("--split", default="dev", choices=["dev", "test"])
    sub = parser.add_subparsers(dest="command", required=True)

    list_parser = sub.add_parser("list", help="列出场景")
    list_parser.add_argument("--status", choices=["proposed", "confirmed"], default=None)
    list_parser.set_defaults(func=_cmd_list)

    confirm_parser = sub.add_parser("confirm", help="确认一条场景的标签")
    confirm_parser.add_argument("--id", required=True)
    confirm_parser.add_argument("--label", required=True)
    confirm_parser.add_argument("--labeler", required=True)
    confirm_parser.set_defaults(func=_cmd_confirm)

    kappa_parser = sub.add_parser("kappa", help="计算双人一致性")
    kappa_parser.add_argument("--a", required=True)
    kappa_parser.add_argument("--b", required=True)
    kappa_parser.set_defaults(func=_cmd_kappa)

    summary_parser = sub.add_parser("summary", help="显示分布与确认进度")
    summary_parser.set_defaults(func=_cmd_summary)

    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
