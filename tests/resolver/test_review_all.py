"""独立复核模式的行为契约。

背景：`review` 原本只挑 `proposed` 条目。这对"自己接着上次标"是对的，
但对"独立复核"是错的——副本是从已标注文件复制来的，继承了 `confirmed` 状态，
第二标注者只会被问剩下那一两条，κ 退化成 n=1。

三种模式必须严格区分：

| 模式 | 问什么 | 用途 |
|---|---|---|
| 补充标注（默认） | 只问 `proposed` | 自己接着上次标 |
| 独立复核（`--all`） | **问全部**，覆盖已有标签 | 第二标注者 |
| 新建副本（`new-annotator`） | 先重置为全 `proposed`，再问全部 | 避免手工 copy 时忘重置 |

安全要求：`--all` 会覆盖已有标注，必须拒绝在非副本文件上使用。
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path

import pytest
from evals.datasets.conflict_set import load_conflict_set
from evals.tools.label import ReviewSession, create_annotator_copy, review


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


def _confirmed(case_id: str, **overrides: object) -> dict[str, object]:
    return _case(
        case_id,
        label_status="confirmed",
        labeler="xly",
        confirmed_at="2026-10-25T10:00:00",
        **overrides,
    )


# ---------- 默认模式：只问 proposed ----------


def test_default_only_asks_proposed(tmp_path: Path) -> None:
    """补充标注时不该重复问已确认条目——当前行为，必须保持。"""
    path = _write(tmp_path / "test.jsonl", [_confirmed("c1"), _case("c2")])
    session = ReviewSession(path, labeler="alice")

    assert [case.id for case in session._pending] == ["c2"]


# ---------- 独立复核：问全部 ----------


def test_include_confirmed_asks_everything(tmp_path: Path) -> None:
    """第二标注者必须看到全部条目，否则 κ 的样本量退化到离谱。"""
    path = _write(
        tmp_path / "test.bob.jsonl",
        [_confirmed("c1"), _confirmed("c2"), _case("c3")],
    )

    session = ReviewSession(path, labeler="bob", include_confirmed=True)

    assert [case.id for case in session._pending] == ["c1", "c2", "c3"]


def test_include_confirmed_overwrites_previous_labeler(tmp_path: Path) -> None:
    """复核要真的覆盖，而不是保留原标注者却记成新结论。"""
    path = _write(tmp_path / "test.bob.jsonl", [_confirmed("c1", expected="SUPERSEDE")])
    session = ReviewSession(path, labeler="bob", include_confirmed=True)

    session.confirm("MERGE")

    case = load_conflict_set(path).cases[0]
    assert case.expected.value == "MERGE"
    assert case.labeler == "bob"


def test_review_all_flag_reaches_every_case(tmp_path: Path) -> None:
    path = _write(tmp_path / "test.bob.jsonl", [_confirmed("c1"), _confirmed("c2")])
    seen: list[str] = []

    review(
        path,
        labeler="bob",
        inputs=_feed("1", "2", "q"),
        output=seen.append,
        include_confirmed=True,
    )

    joined = "\n".join(seen)
    assert "c1" in joined and "c2" in joined
    assert load_conflict_set(path).confirmed().__len__() == 2


# ---------- 安全：拒绝在原始文件上用 --all ----------


def test_include_confirmed_refuses_non_copy_filename(tmp_path: Path) -> None:
    """误对 test.jsonl 用 --all 会冲掉主标注，必须挡住。"""
    path = _write(tmp_path / "test.jsonl", [_confirmed("c1")])

    with pytest.raises(ValueError, match="副本"):
        ReviewSession(path, labeler="bob", include_confirmed=True)


def test_include_confirmed_allows_copy_filename(tmp_path: Path) -> None:
    """`test.alice.jsonl` / `test.bob.jsonl` 这类副本允许复核。"""
    for name in ("test.alice.jsonl", "test.bob.jsonl", "dev.carol.jsonl"):
        path = _write(tmp_path / name, [_confirmed("c1")])
        session = ReviewSession(path, labeler="x", include_confirmed=True)
        assert len(session._pending) == 1


def test_force_bypasses_copy_check(tmp_path: Path) -> None:
    """确实需要在主文件上重标时，必须显式加 force。"""
    path = _write(tmp_path / "test.jsonl", [_confirmed("c1")])

    session = ReviewSession(path, labeler="bob", include_confirmed=True, force=True)

    assert len(session._pending) == 1


# ---------- new-annotator：一条命令建副本 ----------


def test_create_annotator_copy_resets_all_labels(tmp_path: Path) -> None:
    """手工 copy 最容易忘的就是重置，所以必须由命令来做。"""
    source = _write(tmp_path / "test.jsonl", [_confirmed("c1"), _confirmed("c2")])

    target = create_annotator_copy(source, name="bob")

    assert target.name == "test.bob.jsonl"
    dataset = load_conflict_set(target)
    assert len(dataset.cases) == 2
    assert len(dataset.confirmed()) == 0
    assert all(case.label_status == "proposed" for case in dataset.cases)
    assert all(case.labeler is None for case in dataset.cases)


def test_create_annotator_copy_keeps_content(tmp_path: Path) -> None:
    """重置的只有标签，内容必须原样保留。"""
    source = _write(
        tmp_path / "test.jsonl",
        [_confirmed("c1", text="原文本", candidate_value="新值")],
    )

    target = create_annotator_copy(source, name="bob")

    case = load_conflict_set(target).cases[0]
    assert case.text == "原文本"
    assert case.candidate_value == "新值"


def test_create_annotator_copy_refuses_existing_file(tmp_path: Path) -> None:
    """已存在的副本不能被静默覆盖——那会丢掉别人的标注。"""
    source = _write(tmp_path / "test.jsonl", [_case("c1")])
    create_annotator_copy(source, name="bob")

    with pytest.raises(FileExistsError, match="已存在"):
        create_annotator_copy(source, name="bob")


def test_create_annotator_copy_force_overwrites(tmp_path: Path) -> None:
    source = _write(tmp_path / "test.jsonl", [_case("c1")])
    target = create_annotator_copy(source, name="bob")
    assert target.exists()

    create_annotator_copy(source, name="bob", force=True)


def test_create_annotator_copy_rejects_blank_name(tmp_path: Path) -> None:
    source = _write(tmp_path / "test.jsonl", [_case("c1")])

    with pytest.raises(ValueError, match="name"):
        create_annotator_copy(source, name="   ")


def test_create_annotator_copy_result_is_blind_ready(tmp_path: Path) -> None:
    """副本建好后，默认模式下会问全部条目（因为它们都是 proposed）。"""
    source = _write(tmp_path / "test.jsonl", [_confirmed("c1"), _confirmed("c2")])
    target = create_annotator_copy(source, name="bob")

    session = ReviewSession(target, labeler="bob")

    assert len(session._pending) == 2
