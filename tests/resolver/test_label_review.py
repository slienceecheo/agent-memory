"""交互式标注的行为契约。

三条必须锁住的性质：

1. **默认盲标**：不显示 `expected`。一旦显示，标注者会跟着提案走，
   标签就失去了独立性，κ 和 macro-F1 都变成自证。
2. **输入即时落盘**：标完一条立刻写文件。否则中途退出会丢掉全部进度。
3. **可回退**：标错了能退回上一条，且退回后状态是 proposed 而不是留着一个错标签。
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path

import pytest
from evals.datasets.conflict_set import load_conflict_set
from evals.tools.label import ReviewSession, render_case, review


def _case(case_id: str, **overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "id": case_id,
        "text": "现在改用 npm 了",
        "subject": "project:x",
        "relation": "package_manager",
        "candidate_value": "npm",
        "existing_value": "pnpm",
        "expected": "SUPERSEDE",
        "label_status": "proposed",
    }
    base.update(overrides)
    return base


def _write(path: Path, cases: list[dict[str, object]]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join(json.dumps(c, ensure_ascii=False) for c in cases) + "\n",
        encoding="utf-8",
    )
    return path


def _feed(*values: str) -> Iterator[str]:
    yield from values


def test_blind_mode_hides_expected(tmp_path: Path) -> None:
    """显示提案标签会让标注失去独立性——这是整个评估可信度的基础。

    注意：确认后的回显（"已记录 SUPERSEDE"）是用户自己输入的结果，不是泄露。
    要断言的是**渲染条目时**不出现提案标签。
    """
    path = _write(tmp_path / "test.jsonl", [_case("c1")])
    session = ReviewSession(path, labeler="alice", blind=True)
    case = session.current()
    assert case is not None

    rendered = "\n".join(render_case(case, blind=True))

    assert "提案标签" not in rendered
    assert "SUPERSEDE" not in rendered.replace("4=SUPERSEDE", "")


def test_non_blind_mode_shows_expected(tmp_path: Path) -> None:
    """对照组：非盲标模式确实会显示提案，证明 blind 参数真的起作用。"""
    path = _write(tmp_path / "test.jsonl", [_case("c1")])
    session = ReviewSession(path, labeler="alice", blind=False)
    case = session.current()
    assert case is not None

    rendered = "\n".join(render_case(case, blind=False))

    assert "提案标签" in rendered


def test_shows_case_content(tmp_path: Path) -> None:
    """标注者需要看到足够信息才能判断。"""
    path = _write(tmp_path / "test.jsonl", [_case("c1")])
    lines: list[str] = []

    review(path, labeler="alice", inputs=_feed("4", "q"), output=lines.append)

    joined = "\n".join(lines)
    assert "现在改用 npm 了" in joined
    assert "npm" in joined
    assert "pnpm" in joined


def test_numeric_input_confirms_label(tmp_path: Path) -> None:
    """输入 4 应等价于输入 SUPERSEDE。"""
    path = _write(tmp_path / "test.jsonl", [_case("c1")])

    review(path, labeler="alice", inputs=_feed("4", "q"), output=lambda _: None)

    dataset = load_conflict_set(path)
    assert dataset.cases[0].label_status == "confirmed"
    assert dataset.cases[0].expected.value == "SUPERSEDE"
    assert dataset.cases[0].labeler == "alice"


def test_named_input_also_works(tmp_path: Path) -> None:
    """有人习惯打字，不该强制记数字。"""
    path = _write(tmp_path / "test.jsonl", [_case("c1")])

    review(path, labeler="alice", inputs=_feed("merge", "q"), output=lambda _: None)

    assert load_conflict_set(path).cases[0].expected.value == "MERGE"


def test_progress_is_written_immediately(tmp_path: Path) -> None:
    """中途退出不能丢进度——这是交互模式存在的意义。"""
    path = _write(tmp_path / "test.jsonl", [_case("c1"), _case("c2")])

    review(path, labeler="alice", inputs=_feed("4", "q"), output=lambda _: None)

    dataset = load_conflict_set(path)
    assert dataset.cases[0].label_status == "confirmed"
    assert dataset.cases[1].label_status == "proposed"


def test_skip_leaves_case_untouched(tmp_path: Path) -> None:
    path = _write(tmp_path / "test.jsonl", [_case("c1"), _case("c2")])

    review(
        path,
        labeler="alice",
        inputs=_feed("s", "4", "q"),
        output=lambda _: None,
    )

    dataset = load_conflict_set(path)
    by_id = {case.id: case for case in dataset.cases}
    assert by_id["c1"].label_status == "proposed"
    assert by_id["c2"].label_status == "confirmed"


def test_back_reverts_previous_confirmation(tmp_path: Path) -> None:
    """标错了要能退回去，且退回后不能留下一个错的 confirmed 标签。"""
    path = _write(tmp_path / "test.jsonl", [_case("c1"), _case("c2")])

    review(
        path,
        labeler="alice",
        inputs=_feed("4", "b", "1", "q"),
        output=lambda _: None,
    )

    dataset = load_conflict_set(path)
    by_id = {case.id: case for case in dataset.cases}
    # c1 被标成 SUPERSEDE 后又被回退成 proposed，然后重新标成 NOOP
    assert by_id["c1"].label_status == "confirmed"
    assert by_id["c1"].expected.value == "NOOP"
    assert by_id["c2"].label_status == "proposed"


def test_back_at_first_case_is_safe(tmp_path: Path) -> None:
    """第一条就按 b 不能崩，也不能把游标移到 -1。"""
    path = _write(tmp_path / "test.jsonl", [_case("c1")])
    lines: list[str] = []

    review(
        path,
        labeler="alice",
        inputs=_feed("b", "4", "q"),
        output=lines.append,
    )

    assert load_conflict_set(path).cases[0].label_status == "confirmed"
    assert any("第一条" in line for line in lines)


def test_invalid_input_reprompts(tmp_path: Path) -> None:
    """输错不该退出，也不该把错值写进去。"""
    path = _write(tmp_path / "test.jsonl", [_case("c1")])
    lines: list[str] = []

    review(
        path,
        labeler="alice",
        inputs=_feed("99", "4", "q"),
        output=lines.append,
    )

    assert load_conflict_set(path).cases[0].expected.value == "SUPERSEDE"
    assert any("无法识别" in line for line in lines)


def test_quit_prints_summary(tmp_path: Path) -> None:
    """退出时要知道标了几条、还剩几条。"""
    path = _write(tmp_path / "test.jsonl", [_case("c1"), _case("c2"), _case("c3")])
    lines: list[str] = []

    review(path, labeler="alice", inputs=_feed("4", "q"), output=lines.append)

    joined = "\n".join(lines)
    assert "1" in joined
    assert "2" in joined  # 剩余 2 条


def test_already_confirmed_cases_are_skipped(tmp_path: Path) -> None:
    """重跑时不该再问已经确认过的条目。"""
    path = _write(
        tmp_path / "test.jsonl",
        [
            _case("c1", label_status="confirmed", labeler="alice", confirmed_at="2026-01-01"),
            _case("c2"),
        ],
    )
    lines: list[str] = []

    review(path, labeler="bob", inputs=_feed("1", "q"), output=lines.append)

    dataset = load_conflict_set(path)
    by_id = {case.id: case for case in dataset.cases}
    assert by_id["c1"].labeler == "alice"
    assert by_id["c2"].labeler == "bob"


def test_session_tracks_cursor_and_history(tmp_path: Path) -> None:
    """把状态放进对象里，才能测回退这类跨步行为。"""
    path = _write(tmp_path / "test.jsonl", [_case("c1"), _case("c2")])
    session = ReviewSession(path, labeler="alice")

    session.confirm("SUPERSEDE")
    assert session.position == 1
    assert session.confirmed_count == 1

    session.back()
    assert session.position == 0
    assert session.confirmed_count == 0


def test_empty_pending_set(tmp_path: Path) -> None:
    """全部确认完再跑，应直接告知无事可做。"""
    path = _write(
        tmp_path / "test.jsonl",
        [_case("c1", label_status="confirmed", labeler="alice", confirmed_at="2026-01-01")],
    )
    lines: list[str] = []

    review(path, labeler="alice", inputs=_feed("q"), output=lines.append)

    assert any("没有待确认" in line for line in lines)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("1", "NOOP"),
        ("2", "ADD"),
        ("3", "MERGE"),
        ("4", "SUPERSEDE"),
        ("5", "CONFLICT"),
        ("6", "BRANCH"),
        ("noop", "NOOP"),
        ("  BRANCH  ", "BRANCH"),
    ],
)
def test_input_parsing(tmp_path: Path, raw: str, expected: str) -> None:
    """数字与名字都要能用，且大小写空格不敏感。"""
    path = _write(tmp_path / "test.jsonl", [_case("c1")])

    review(path, labeler="alice", inputs=_feed(raw, "q"), output=lambda _: None)

    assert load_conflict_set(path).cases[0].expected.value == expected
