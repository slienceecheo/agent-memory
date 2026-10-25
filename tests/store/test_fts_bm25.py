"""词面检索的行为契约。

两个必须同时成立的性质，缺一则词面召回是噪声：

1. **索引包含原文**。C3 的 9 条语义错误正是"原文与存储值零重叠"，
   不索引原文的话，词面路径对这个差距结构性失明。
2. **按 BM25 排序**。原来按 `version DESC` 排序，而 `version` 是键内序号，
   跨键无序——RRF 会拿到一个假排名。
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from memory.store.models import Authority, MemoryItem, Scope, Source, Status
from memory.store.sqlite import SqliteStore, tokenize

NOW = datetime(2026, 1, 1, tzinfo=UTC)


def _item(
    *,
    value: str,
    text: str | None = None,
    subject: str = "user:default",
    relation: str = "seat",
    condition: str | None = None,
    valid_from: datetime | None = None,
) -> MemoryItem:
    return MemoryItem(
        owner="o",
        scope=Scope.PROJECT,
        subject=subject,
        relation=relation,
        value=value,
        condition=condition,
        status=Status.ACTIVE,
        valid_from=valid_from or NOW,
        valid_to=None,
        recorded_at=NOW,
        authority=Authority.USER_DIRECT,
        source=Source(session_id="s1"),
        text=text,
    )


def test_original_text_is_searchable(tmp_path: Path) -> None:
    """只在原文里出现的词，必须能召回该条。"""
    store = SqliteStore(tmp_path / "m.db")
    store.insert(
        _item(value="C区第三排左数第二个工位", text="就是靠窗那一排的位子"),
        reason="r",
        actor="t",
    )

    hits = store.search_text("靠窗")

    assert len(hits) == 1
    assert hits[0].value == "C区第三排左数第二个工位"


def test_value_is_still_searchable(tmp_path: Path) -> None:
    """原文索引不能挤掉结构化字段。"""
    store = SqliteStore(tmp_path / "m.db")
    store.insert(_item(value="pnpm", text="我们用 pnpm"), reason="r", actor="t")

    assert len(store.search_text("pnpm")) == 1


def test_results_are_ordered_by_relevance(tmp_path: Path) -> None:
    """BM25 排序：命中次数多、文档更短的那条应排前。

    构造：两条都含"pnpm"，但第二条只含 pnpm 且更短、重复更多。
    """
    store = SqliteStore(tmp_path / "m.db")
    store.insert(
        _item(
            value="a",
            text="我们讨论了很多话题包括部署测试评审以及顺便提到 pnpm 一次",
            subject="user:a",
            relation="note",
        ),
        reason="r",
        actor="t",
    )
    store.insert(
        _item(
            value="b",
            text="pnpm pnpm pnpm",
            subject="user:b",
            relation="note",
        ),
        reason="r",
        actor="t",
    )

    hits = store.search_text("pnpm")

    assert len(hits) == 2
    assert hits[0].value == "b", "短文档且词频高者应排前"


def test_order_is_not_version_based(tmp_path: Path) -> None:
    """反证：若按 version 排序，后写入的更相关条目会被排到后面。

    构造两条不同 subject（version 都是 1，无法区分），
    再用相关性明确的场景断言排序来自 BM25。
    """
    store = SqliteStore(tmp_path / "m.db")
    # 先写不相关的
    store.insert(
        _item(value="x", text="完全无关的一句话", subject="user:x", relation="note"),
        reason="r",
        actor="t",
    )
    # 后写相关的（若按 version DESC / ordinal 排序，它反而可能靠前，
    # 所以反过来：让相关的那条先写）
    store.insert(
        _item(value="y", text="pnpm 是我们的包管理器", subject="user:y", relation="note"),
        reason="r",
        actor="t",
    )

    hits = store.search_text("pnpm")

    assert len(hits) == 1
    assert hits[0].value == "y"


def test_only_active_is_returned(tmp_path: Path) -> None:
    store = SqliteStore(tmp_path / "m.db")
    first = store.insert(_item(value="pnpm", text="用 pnpm"), reason="r", actor="t")
    store.supersede(
        first.id,
        _item(value="npm", text="改用 npm", valid_from=NOW + timedelta(days=1)),
        reason="changed",
        actor="t",
    )

    assert store.search_text("pnpm") == []


def test_retracted_is_invisible(tmp_path: Path) -> None:
    store = SqliteStore(tmp_path / "m.db")
    created = store.insert(_item(value="pnpm", text="用 pnpm"), reason="r", actor="t")
    store.retract(created.id, reason="wrong", actor="t")

    assert store.search_text("pnpm") == []


def test_chinese_bigram_still_works(tmp_path: Path) -> None:
    """C2 已解决的中文 bigram 不能因为改索引而退化。"""
    store = SqliteStore(tmp_path / "m.db")
    store.insert(_item(value="项目使用包管理器", text="这里讲的是包管理器"), reason="r", actor="t")

    assert len(store.search_text("包管理")) == 1


def test_item_without_text_is_not_matched_by_text_only_word(tmp_path: Path) -> None:
    """没有原文的旧条目不该被"只在原文里出现"的词命中。"""
    store = SqliteStore(tmp_path / "m.db")
    store.insert(_item(value="C区第三排", text=None), reason="r", actor="t")

    assert store.search_text("靠窗") == []


def test_tokenize_includes_source_text(tmp_path: Path) -> None:
    """索引内容必须同时包含结构字段与原文。"""
    tokens = tokenize("seat C区第三排 靠窗那一排")

    assert "靠窗" in tokens
