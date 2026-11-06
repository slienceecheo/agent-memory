"""三条召回路径都只返回 ACTIVE —— 这是删除 `status` 特征的前提。

## 为什么需要

`status` 在候选池内恒为 1.0，所以它不提供任何排序信息。

**但这个结论依赖一个契约**：所有召回路径只返回 ACTIVE 条目。
若某条路径返回非 ACTIVE，`status` 就会有方差，那时它应该重新成为特征。

## 现有断言为什么不够

| 位置 | 测什么 | 为什么不够 |
|---|---|---|
| `test_rerank_variance.py:110` | `status_score` 的取值数 | 测**函数**，不是召回路径 |
| `test_v3_capability_boundary.py:140` | 记忆库的 status 集合 | 测**数据集**，不是召回路径 |
| `test_rerank.py:53` | ACTIVE > CONFLICTED | 测**值域**，不是池 |

**三者都不证明"召回会过滤掉非 ACTIVE"。**

## 这条断言测什么

**构造一个含非 ACTIVE 条目的 store，跑三条召回路径，断言它们都不返回非 ACTIVE。**

这是"路径级"验证，不是"数据级"。
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _make_store(tmp_path, statuses, *, embedding_dims: int = 1024):
    """构造一个含多种 status 的 store，返回 (store, 期望的 ACTIVE id 集合)。"""
    from memory.store.models import Status
    from memory.store.sqlite import SqliteStore

    store = SqliteStore(tmp_path / "recall.db", embedding_dims=embedding_dims)

    active_ids = set()
    for i, status in enumerate(statuses):
        item = store.insert(
            _item(status=status, idx=i),
            reason="test",
            actor="test",
            # **给非 ACTIVE 也写向量**：否则"它们没被召回"可能只是因为没向量，
            # 而不是因为 status 过滤。这是"过滤生效"的必要构造。
            embedding=[0.1] * embedding_dims,
        )
        if status is Status.ACTIVE:
            active_ids.add(item.id)
    return store, active_ids


def _item(*, status, idx: int):
    from datetime import UTC, datetime

    from memory.store.models import Authority, MemoryItem, Scope, Source

    now = datetime(2026, 1, 1, tzinfo=UTC)
    return MemoryItem(
        owner="test",
        scope=Scope.PROJECT,
        subject="project:test",
        relation=f"rel_{idx}",
        value=f"value_{idx}",
        condition=None,
        status=status,
        valid_from=now,
        valid_to=None,
        recorded_at=now,
        authority=Authority.USER_DIRECT,
        source=Source(session_id="test"),
        text=f"测试记忆 {idx}",
    )


def test_lexical_returns_only_active(tmp_path) -> None:
    """**lexical 路径只返回 ACTIVE。**

    实测：它包装 `search_text`，而 `search_text` 的 FTS 查询带
    `status = 'ACTIVE'` 过滤。
    """
    from memory.retrieval.lexical import recall_by_lexical
    from memory.store.models import Status

    store, active_ids = _make_store(
        tmp_path, [Status.ACTIVE, Status.SUPERSEDED, Status.CONFLICTED]
    )
    try:
        hits = recall_by_lexical(store, "测试记忆", limit=10)
        got = {h.id for h in hits}
        non_active = got - active_ids
        assert not non_active, (
            f"lexical 返回了非 ACTIVE 条目：{non_active}\n"
            "这是 'status 恒为 1.0' 这个结论的前提——若破裂，status 要重新成为特征。"
        )
    finally:
        store.close()


def test_vector_returns_only_active(tmp_path) -> None:
    """**vector 路径只返回 ACTIVE。**

    实测：SQL 里带 `WHERE i.status = 'ACTIVE'`。
    """
    from memory.retrieval.vector import recall_by_vector
    from memory.store.models import Status

    dims = 8
    store, active_ids = _make_store(
        tmp_path,
        [Status.ACTIVE, Status.SUPERSEDED, Status.CONFLICTED],
        embedding_dims=dims,
    )
    try:
        # 所有条目（含非 ACTIVE）都写了同方向向量 -> 它们在向量空间里等距
        # 所以"没被召回"只能是因为 status 过滤，而不是"没有向量"
        hits = recall_by_vector(store, [0.1] * dims, limit=10)
        got = {h.id for h in hits}
        non_active = got - active_ids
        assert not non_active, (
            f"vector 返回了非 ACTIVE 条目：{non_active}\n"
            "SQL 里的 `WHERE i.status = 'ACTIVE'` 可能被去掉了。"
        )
    finally:
        store.close()


def test_adjacency_returns_only_active(tmp_path) -> None:
    """**adjacency 路径只返回 ACTIVE。**

    实测：SQL 里有 `AND status = 'ACTIVE'`，另外 Python 侧还有一道
    `if item.status is Status.ACTIVE` 的二次过滤。

    **这条行为断言只能抓 SQL 那层**：实测把 Python 二次过滤删掉，
    本断言**仍然通过**（因为 SQL 已经过滤了）。
    所以 Python 层由 `test_adjacency_has_python_side_refilter` 单独守。

    **这个区分很重要**：若以为这条断言能守住两层过滤，
    那一层被删掉时不会有任何提示。
    """
    from memory.retrieval.adjacency import recall_by_adjacency
    from memory.store.models import Status

    store, active_ids = _make_store(
        tmp_path, [Status.ACTIVE, Status.SUPERSEDED, Status.CONFLICTED]
    )
    try:
        hits = recall_by_adjacency(
            store,
            subject="project:test",
            relation="rel_0",
            condition=None,
            owner="test",
            limit=10,
        )
        got = {h.id for h in hits}
        non_active = got - active_ids
        assert not non_active, (
            f"adjacency 返回了非 ACTIVE 条目：{non_active}\n"
            "SQL 过滤可能被去掉了（Python 二次过滤由另一条断言守）。"
        )
    finally:
        store.close()


def test_all_three_paths_agree_on_active_only() -> None:
    """**三条路径的过滤语义必须一致**（都只返回 ACTIVE）。

    单条路径测试证明"每条都过滤"，这条证明"三条的契约相同"——
    若将来只有一条改了口径，这条会指出是哪一条。

    **为什么用源码检查**：三条路径的过滤位置不同
    （lexical 走 FTS、vector 走 SQL、adjacency 走 SQL + Python），
    行为测试已经分别覆盖；这条只需要确认"三处过滤都还在"。
    """
    src = ROOT / "src" / "memory" / "retrieval"
    checks = {
        "lexical.py": "search_text",  # lexical 依赖 search_text 的过滤
        "vector.py": "WHERE i.status = 'ACTIVE'",
        "adjacency.py": "status = 'ACTIVE'",
    }
    missing = []
    for name, needle in checks.items():
        text = (src / name).read_text(encoding="utf-8")
        if needle not in text:
            missing.append(f"{name}: {needle!r}")

    assert not missing, (
        f"这些路径的 ACTIVE 过滤不见了：{missing}\n"
        "删除 status 特征的前提是'所有召回路径只返回 ACTIVE'——"
        "若某条路径不再过滤，status 会有方差，就应重新成为特征。"
    )


def test_adjacency_has_python_side_refilter() -> None:
    """**adjacency 有 Python 侧二次过滤**——SQL 过滤不够。

    实测 `adjacency.py:43`：
    `return [item for item in items if item.status is Status.ACTIVE]`

    **为什么需要二次过滤**：SQL 的 `status = 'ACTIVE'` 是字符串比较，
    而 store 返回的对象可能是 `Status` 枚举。若枚举值与字符串不同源，
    SQL 会漏掉。二次过滤是防御。
    """
    text = (ROOT / "src" / "memory" / "retrieval" / "adjacency.py").read_text(
        encoding="utf-8"
    )
    assert "is Status.ACTIVE" in text, (
        "adjacency 的 Python 侧二次过滤不见了——\n"
        "SQL 过滤是字符串比较，与枚举可能不同源；二次过滤是必要的防御。"
    )
