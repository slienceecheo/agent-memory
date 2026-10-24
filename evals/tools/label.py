"""标注工具：列出、确认、计算一致性。

    uv run python -m evals.tools.label list [--status proposed]
    uv run python -m evals.tools.label confirm --id dev-sup-01 --label SUPERSEDE --labeler alice
    uv run python -m evals.tools.label kappa --a alice --b bob

为什么是脚本而不是表格：标签必须能追溯到"谁在什么时候确认的"。
CSV 手工编辑会丢失这个信息，也会让"改了但没记录"变得无法发现。
"""

from __future__ import annotations

import argparse
import dataclasses
import sys
from collections import Counter
from collections.abc import Callable, Iterator
from dataclasses import dataclass
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
    """多类别 Cohen's κ。

    **必须是多类别口径**，不能折成"是否一致"二分类：
    二分类会丢掉"错成了哪一类"的信息，且把 majority class 的一致率算得过高。
    六类标签的 κ 应该按 6×6 列联表计算。

    边界：
    - 两者都只给同一个标签 → 观察一致率与期望一致率都是 1，κ 定义为 1
    - 完全相反 → κ 为负，不做截断（截断会掩盖"口径根本不一致"）
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
    # 期望一致率：两边各自边缘分布的乘积和（这正是多类别 κ 的定义）
    p_expected = sum(
        (counts_a[key] / total) * (counts_b[key] / total) for key in set(counts_a) | set(counts_b)
    )

    if p_expected == 1.0:
        return 1.0
    return (p_observed - p_expected) / (1.0 - p_expected)


# ---------- 交互式标注 ----------

_NUMBER_TO_KIND: dict[str, DecisionKind] = {
    "1": DecisionKind.NOOP,
    "2": DecisionKind.ADD,
    "3": DecisionKind.MERGE,
    "4": DecisionKind.SUPERSEDE,
    "5": DecisionKind.CONFLICT,
    "6": DecisionKind.BRANCH,
}


def parse_input(raw: str) -> DecisionKind | None:
    """把用户输入解析为类别；无法识别时返回 None（由调用方重新提问）。"""
    text = raw.strip()
    if not text:
        return None
    if text in _NUMBER_TO_KIND:
        return _NUMBER_TO_KIND[text]
    try:
        return DecisionKind(text.upper())
    except ValueError:
        return None


def _looks_like_copy(path: Path) -> bool:
    """判断文件名是否像"标注者副本"（如 `test.bob.jsonl`）。

    主文件是 `test.jsonl` / `dev.jsonl`；副本在中间多一段标注者名字。
    这个判断刻意保守：宁可要求加 `--force`，也不能因为误判冲掉主标注。
    """
    return path.stem.count(".") >= 1


def create_annotator_copy(
    source: Path | str, *, name: str, force: bool = False
) -> Path:
    """从主标注文件生成一份全 `proposed` 的标注者副本。

    手工 `Copy-Item` 最容易忘的就是重置标签：副本会继承 `confirmed` 状态，
    第二标注者打开后只会被问到剩下那一两条，κ 的样本量退化到没有意义。

    参数：
        source: 主文件（如 `test.jsonl`）
        name:   标注者名字，用于生成 `test.bob.jsonl`
        force:  副本已存在时是否覆盖（默认拒绝，避免丢掉别人的标注）
    """
    if not name.strip():
        raise ValueError("name 不能为空：需要标注者名字来命名副本")

    src = Path(source)
    target = src.with_name(f"{src.stem}.{name.strip()}.jsonl")
    if target.exists() and not force:
        raise FileExistsError(f"{target.name} 已存在；如需覆盖请加 --force")

    dataset = load_conflict_set(src)
    reset = ConflictSet(
        tuple(
            dataclasses.replace(
                case, label_status="proposed", labeler=None, confirmed_at=None
            )
            for case in dataset.cases
        )
    )
    save_conflict_set(reset, target)
    return target


class ReviewSession:
    """一次标注会话的状态。

    把状态放进对象而不是散在循环里，是为了让"回退"这类跨步行为可测。

    两种模式严格区分：

    - **补充标注**（`include_confirmed=False`）：只问 `proposed`，
      用于自己接着上次标。
    - **独立复核**（`include_confirmed=True`）：问全部并覆盖，
      用于第二标注者。副本从已标注文件复制而来会继承 `confirmed` 状态，
      若只问 `proposed`，第二标注者只会被问到剩下那一两条，κ 退化成 n=1。

    安全约束：覆盖已有标注只允许发生在**副本文件**上
    （`test.alice.jsonl` 这类）。误对主文件用会冲掉别人的工作。
    """

    def __init__(
        self,
        path: Path | str,
        *,
        labeler: str,
        blind: bool = True,
        include_confirmed: bool = False,
        force: bool = False,
    ) -> None:
        if not labeler.strip():
            raise ValueError("labeler 不能为空：没有确认者就算不出双人一致性")
        self.path = Path(path)
        self.labeler = labeler.strip()
        self.blind = blind

        if include_confirmed and not force and not _looks_like_copy(self.path):
            raise ValueError(
                f"{self.path.name} 看起来是主标注文件，不是副本。"
                "--all 会覆盖已有标注，只允许在副本（如 test.bob.jsonl）上使用。"
                "确实要重标主文件请显式加 --force。"
            )

        self._include_confirmed = include_confirmed
        dataset = load_conflict_set(self.path)
        if include_confirmed:
            self._pending = list(dataset.cases)
        else:
            # 只处理尚未确认的条目，保持文件中的原始顺序
            self._pending = [
                case for case in dataset.cases if case.label_status != "confirmed"
            ]
        self._position = 0
        self._history: list[tuple[str, str]] = []

    @property
    def position(self) -> int:
        return self._position

    @property
    def confirmed_count(self) -> int:
        return len(self._history)

    @property
    def remaining(self) -> int:
        return max(0, len(self._pending) - self._position)

    def current(self) -> ConflictCase | None:
        if self._position >= len(self._pending):
            return None
        return self._pending[self._position]

    def confirm(self, kind: DecisionKind | str) -> ConflictCase:
        """写入一条确认并前进。立即落盘，中途退出不丢进度。

        接受字符串是为了让调用方不必先做枚举转换——内部统一校验。
        """
        case = self.current()
        if case is None:
            raise IndexError("没有更多待确认条目")
        resolved = kind if isinstance(kind, DecisionKind) else parse_input(str(kind))
        if resolved is None:
            raise ValueError(f"非法标签 {kind!r}")
        updated = confirm_case(
            self.path, case_id=case.id, label=resolved.value, labeler=self.labeler
        )
        self._history.append((case.id, resolved.value))
        self._position += 1
        return updated

    def back(self) -> bool:
        """回退一条：把上一条改回 proposed。

        返回是否真的回退了（在第一条按回退时返回 False）。
        """
        if self._position == 0:
            return False
        self._position -= 1
        case_id, _ = self._history.pop()
        update_label(
            self.path, case_id=case_id, label="ADD", labeler=self.labeler, status="proposed"
        )
        return True


def render_case(case: ConflictCase, *, blind: bool) -> list[str]:
    """渲染一条待标注条目。

    `blind=True` 时不显示 `expected`——一旦显示，标注者会跟着提案走。
    """
    lines = [
        "",
        f"[{case.id}]",
        f"  新陈述：{case.text}",
        f"  候选值：{case.candidate_value}",
        f"  既有值：{case.existing_value if case.existing_value is not None else '（无）'}",
    ]
    if case.condition or case.existing_condition:
        lines.append(f"  条件：新={case.condition} 旧={case.existing_condition}")
    lines.append(f"  权威：{case.authority}")
    if case.note:
        lines.append(f"  备注：{case.note}")
    if not blind:
        lines.append(f"  [提案标签：{case.expected.value}]")
    lines.append("  1=NOOP 2=ADD 3=MERGE 4=SUPERSEDE 5=CONFLICT 6=BRANCH  s=跳过 b=回退 q=退出")
    return lines


def review(
    path: Path | str,
    *,
    labeler: str,
    inputs: Iterator[str],
    output: Callable[[str], None],
    blind: bool = True,
    include_confirmed: bool = False,
    force: bool = False,
) -> ReviewSession:
    """逐条交互式标注。

    `inputs` 与 `output` 通过参数注入，使整个流程可在测试中驱动，
    不必依赖真实 stdin/stdout。

    `include_confirmed=True` 时问全部并覆盖，用于第二标注者的独立复核。
    """
    session = ReviewSession(
        path,
        labeler=labeler,
        blind=blind,
        include_confirmed=include_confirmed,
        force=force,
    )

    if session.current() is None:
        output("没有待确认的条目。")
        return session

    output(f"共 {len(session._pending)} 条待确认，标注者：{session.labeler}")

    while (case := session.current()) is not None:
        for line in render_case(case, blind=blind):
            output(line)

        raw = next(inputs, "q").strip()
        if raw.lower() == "q":
            break
        if raw.lower() == "s":
            session._position += 1
            continue
        if raw.lower() == "b":
            if not session.back():
                output("已经是第一条，无法回退。")
            continue

        kind = parse_input(raw)
        if kind is None:
            output(f"无法识别的输入 {raw!r}，请输入 1-6 或类别名。")
            continue

        session.confirm(kind)
        output(f"  → 已记录 {kind.value}")

    done = session.confirmed_count
    output(f"\n本次确认 {done} 条，剩余 {session.remaining} 条待确认。")
    return session


def _dataset_path(split: str, file: str | None = None) -> Path:
    return Path(file) if file else DEFAULT_SET / f"{split}.jsonl"


# ---------- 双人标注的 κ ----------


@dataclass(frozen=True, slots=True)
class Disagreement:
    case_id: str
    left: str
    right: str


@dataclass(frozen=True, slots=True)
class KappaResult:
    kappa: float
    shared: int
    disagreements: list[Disagreement]
    only_left: list[str]
    only_right: list[str]
    verdict: str


_VERDICTS: tuple[tuple[float, str], ...] = (
    (0.8, "高度一致，可直接采用"),
    (0.7, "可接受，报告里说明"),
    (0.6, "偏弱，建议逐条讨论不一致项后重标"),
    (-1.0, "一致性不足，结论强度受限；先对齐六类定义再标"),
)


def _read_labels(path: Path | str) -> dict[str, str]:
    dataset = load_conflict_set(path)
    return {case.id: case.expected.value for case in dataset.cases}


def kappa_from_files(left: Path | str, right: Path | str) -> KappaResult:
    """从两份标注副本计算多类别 κ。

    用 `expected` 而不是 `labeler`：两份副本里 labeler 天然不同，
    用它求一致率等于同义反复。
    """
    a = _read_labels(left)
    b = _read_labels(right)
    shared = sorted(set(a) & set(b))
    if not shared:
        raise ValueError(
            "两份文件没有共同的条目，无法计算 κ。请确认两份副本来自同一批场景。"
        )

    kappa = cohen_kappa([a[key] for key in shared], [b[key] for key in shared])
    disagreements = [
        Disagreement(case_id=key, left=a[key], right=b[key]) for key in shared if a[key] != b[key]
    ]
    verdict = next(label for threshold, label in _VERDICTS if kappa >= threshold)

    return KappaResult(
        kappa=kappa,
        shared=len(shared),
        disagreements=disagreements,
        only_left=sorted(set(a) - set(b)),
        only_right=sorted(set(b) - set(a)),
        verdict=verdict,
    )


def _cmd_kappa(args: argparse.Namespace) -> int:
    if args.a_file or args.b_file:
        if not (args.a_file and args.b_file):
            print("--a-file 与 --b-file 必须成对使用", file=sys.stderr)
            return 2
        try:
            result = kappa_from_files(args.a_file, args.b_file)
        except ValueError as exc:
            print(str(exc), file=sys.stderr)
            return 2
        _print_kappa(result)
        return 0 if result.kappa >= 0.7 else 1

    path = _dataset_path(args.split, args.file)
    dataset = load_conflict_set(path)
    by_labeler: dict[str, dict[str, str]] = {}
    for case in dataset.cases:
        if case.labeler and case.label_status == "confirmed":
            by_labeler.setdefault(case.labeler, {})[case.id] = case.expected.value

    if args.a not in by_labeler or args.b not in by_labeler:
        print(
            f"缺少标注者数据。已记录：{', '.join(by_labeler) or '无'}\n"
            "提示：同一文件只有一条期望标签，两人标同一份会互相覆盖。"
            "真双人标注请用两份副本 + --a-file/--b-file。",
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


def _print_kappa(result: KappaResult) -> None:
    print(f"共同条目 {result.shared} 条，Cohen's κ = {result.kappa:.3f}")
    print(f"判定：{result.verdict}")
    if result.only_left:
        print(f"仅左侧标注：{', '.join(result.only_left)}")
    if result.only_right:
        print(f"仅右侧标注：{', '.join(result.only_right)}")
    if result.disagreements:
        print("不一致条目：")
        for item in result.disagreements:
            print(f"  {item.case_id}: {item.left} vs {item.right}")


def _cmd_list(args: argparse.Namespace) -> int:
    path = _dataset_path(args.split, getattr(args, 'file', None))
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
    path = _dataset_path(args.split, getattr(args, 'file', None))
    case = confirm_case(
        path, case_id=args.id, label=args.label, labeler=args.labeler
    )
    print(f"已确认 {case.id} → {case.expected.value}（{case.labeler}）")
    return 0


def _cmd_summary(args: argparse.Namespace) -> int:
    path = _dataset_path(args.split, args.file)
    dataset: ConflictSet = load_conflict_set(path)
    counts = dataset.class_counts()
    confirmed = dataset.confirmed()
    print(f"{path.name}: {len(dataset)} 条，已确认 {len(confirmed)} 条")
    for kind, count in counts.items():
        print(f"  {kind.value:<10} {count}")
    print(f"均衡：{dataset.is_balanced()}")
    return 0


def _cmd_review(args: argparse.Namespace) -> int:
    path = _dataset_path(args.split, args.file)
    try:
        review(
            path,
            labeler=args.labeler,
            inputs=iter(lambda: input(), "q"),
            output=print,
            blind=not args.show_expected,
            include_confirmed=args.all,
            force=args.force,
        )
    except (ValueError, FileExistsError) as exc:
        print(str(exc), file=sys.stderr)
        return 2
    return 0


def _cmd_new_annotator(args: argparse.Namespace) -> int:
    source = _dataset_path(args.split)
    try:
        target = create_annotator_copy(source, name=args.name, force=args.force)
    except (ValueError, FileExistsError) as exc:
        print(str(exc), file=sys.stderr)
        return 2
    print(f"已创建副本：{target}")
    print(f"全部 {len(load_conflict_set(target))} 条已重置为 proposed。")
    print("下一步：")
    print(
        f"  uv run python -m evals.tools.label --file {target} "
        f"review --labeler {args.name}"
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="evals.tools.label", description="冲突场景标注工具")
    parser.add_argument(
        "--split",
        default="dev",
        choices=["dev", "test"],
        help="要操作的数据集；若给了 --file 则以 --file 为准",
    )
    parser.add_argument("--file", default=None, help="直接指定标注文件（用于双人副本）")
    sub = parser.add_subparsers(dest="command", required=True)

    review_parser = sub.add_parser("review", help="交互式逐条标注（默认盲标）")
    review_parser.add_argument("--labeler", required=True)
    review_parser.add_argument(
        "--show-expected",
        action="store_true",
        help="显示提案标签；默认不显示，避免被带偏",
    )
    review_parser.add_argument(
        "--all",
        action="store_true",
        help="问全部条目并覆盖已有标签（第二标注者独立复核用）",
    )
    review_parser.add_argument(
        "--force",
        action="store_true",
        help="允许 --all 作用于主标注文件（危险，会覆盖别人的标注）",
    )
    review_parser.set_defaults(func=_cmd_review)

    new_annotator_parser = sub.add_parser(
        "new-annotator", help="生成一份全 proposed 的标注者副本"
    )
    new_annotator_parser.add_argument("--name", required=True, help="标注者名字")
    new_annotator_parser.add_argument(
        "--force", action="store_true", help="副本已存在时覆盖"
    )
    new_annotator_parser.set_defaults(func=_cmd_new_annotator)

    list_parser = sub.add_parser("list", help="列出场景")
    list_parser.add_argument("--status", choices=["proposed", "confirmed"], default=None)
    list_parser.set_defaults(func=_cmd_list)

    confirm_parser = sub.add_parser("confirm", help="确认一条场景的标签")
    confirm_parser.add_argument("--id", required=True)
    confirm_parser.add_argument("--label", required=True)
    confirm_parser.add_argument("--labeler", required=True)
    confirm_parser.set_defaults(func=_cmd_confirm)

    kappa_parser = sub.add_parser("kappa", help="计算双人一致性")
    kappa_parser.add_argument("--a", default=None, help="标注者名字（单文件模式）")
    kappa_parser.add_argument("--b", default=None, help="标注者名字（单文件模式）")
    kappa_parser.add_argument("--a-file", default=None, help="左标注者的文件")
    kappa_parser.add_argument("--b-file", default=None, help="右标注者的文件")
    kappa_parser.set_defaults(func=_cmd_kappa)

    summary_parser = sub.add_parser("summary", help="显示分布与确认进度")
    summary_parser.set_defaults(func=_cmd_summary)

    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
