"""原文保存的行为契约。

为什么必须存原文：C3 独立集暴露的 9 条错误，正是"原文与存储值零重叠"
（`"靠窗那一排"` vs `"C区第三排左数第二个工位"`）。若不存原文，
检索层无法用用户实际说过的话找到这条记忆——它只能看见被抽取出的三元组。

这也是"一条记忆为什么存在"的唯一凭证。
"""

from __future__ import annotations

import dataclasses
from datetime import UTC, datetime
from pathlib import Path

from memory.store.models import Authority, MemoryItem, Scope, Source, Status
from memory.store.sqlite import SqliteStore

NOW = datetime(2026, 1, 1, tzinfo=UTC)


def _item(**overrides: object) -> MemoryItem:
    base: dict[str, object] = {
        "owner": "o",
        "scope": Scope.PROJECT,
        "subject": "user:default",
        "relation": "seat",
        "value": "C区第三排左数第二个工位",
        "condition": None,
        "status": Status.ACTIVE,
        "valid_from": NOW,
        "valid_to": None,
        "recorded_at": NOW,
        "authority": Authority.USER_DIRECT,
        "source": Source(session_id="s1"),
    }
    base.update(overrides)
    return MemoryItem(**base)  # type: ignore[arg-type]


def test_text_defaults_to_none() -> None:
    """旧数据没有原文，必须能继续构造，否则迁移会全线失败。"""
    assert _item().text is None


def test_text_is_preserved() -> None:
    item = _item(text="就是C区第三排左数第二个工位。")

    assert item.text == "就是C区第三排左数第二个工位。"


def test_blank_text_becomes_none() -> None:
    """空串与 None 不该在库里并存，否则检索判断要写两套。"""
    assert _item(text="   ").text is None


def test_text_is_trimmed() -> None:
    assert _item(text="  就是那个工位  ").text == "就是那个工位"


def test_text_survives_roundtrip(tmp_path: Path) -> None:
    store = SqliteStore(tmp_path / "m.db")
    stored = store.insert(_item(text="就是C区第三排左数第二个工位。"), reason="r", actor="t")

    loaded = store.get(stored.id)

    assert loaded.text == "就是C区第三排左数第二个工位。"


def test_missing_text_reads_back_as_none(tmp_path: Path) -> None:
    store = SqliteStore(tmp_path / "m.db")
    stored = store.insert(_item(), reason="r", actor="t")

    assert store.get(stored.id).text is None


def test_supersede_does_not_wipe_old_text(tmp_path: Path) -> None:
    """旧条目的原文是它的出生凭证，更新时不能被清空。"""
    store = SqliteStore(tmp_path / "m.db")
    first = store.insert(_item(text="原来我坐靠窗那一排。"), reason="r", actor="t")

    store.supersede(
        first.id,
        _item(value="A区第一排", text="换成A区第一排了。", valid_from=NOW.replace(day=2)),
        reason="moved",
        actor="t",
    )

    assert store.get(first.id).text == "原来我坐靠窗那一排。"


def test_text_is_not_used_as_content_fingerprint(tmp_path: Path) -> None:
    """原文是元数据，不是内容。同一事实换个说法说一遍，不该产生新版本。"""
    store = SqliteStore(tmp_path / "m.db")
    first = store.insert(_item(value="pnpm", text="我们用 pnpm。"), reason="r", actor="t")

    second = store.insert(
        _item(value="pnpm", text="这个仓库用 pnpm 管理依赖。"),
        reason="again",
        actor="t",
    )

    assert second.id == first.id
    assert store.count() == 1


def test_text_field_is_frozen() -> None:
    item = _item(text="原文")

    try:
        item.text = "改掉"  # type: ignore[misc]
    except dataclasses.FrozenInstanceError:
        return
    raise AssertionError("text 应当不可就地修改")
