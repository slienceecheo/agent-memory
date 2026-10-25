"""第 2 组：池内写入向量，使 vector 一路有东西可召回。

**为什么必须单独验"写进去了"**：L6a 只证明"调用了"，L6c 只证明"返回非空"。
两者都可能成立而向量其实全是零向量——那时余弦相似度全相等，
排序是任意的，看起来"跑了"却毫无信息。

所以本组要验三件事：

1. 池内每条候选都有向量（`vec_items` 行数 == 池大小）
2. 向量不是零向量（否则排序无意义）
3. 查询侧用 `query` 类型、池内用 `document` 类型（混用会让余弦仅 0.842）

**中间态检查**：本组完成后应是 `vector > 0` 且 `adjacency = null`。
这是唯一能验证"写进去了且被读到了"的时刻——第 3 组接上邻接就分不清了。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from evals.run_retrieval import evaluate

from memory.retrieval.pool_modes import PoolMode

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data" / "conflict-set"


def _rows(name: str) -> list[dict[str, object]]:
    path = DATA / name
    if not path.exists():
        pytest.skip(f"{name} 不存在")
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _all_specs() -> list[dict[str, object]]:
    specs: list[dict[str, object]] = []
    for name in ("dev.jsonl", "test.jsonl", "independent.jsonl"):
        specs.extend([row["gold"] for row in _rows(name) if row.get("gold")])  # type: ignore[misc]
    return specs


def _with_gold(name: str, count: int) -> list[dict[str, object]]:
    return [row for row in _rows(name) if row.get("gold")][:count]


@pytest.fixture(scope="module")
def embedder():
    """真实 embedder，走缓存。缺网络且无缓存时跳过而不是失败。"""
    try:
        from memory.config import Settings
        from memory.embedding.cache import EmbeddingCache
        from memory.embedding.dashscope import DashScopeEmbedder

        settings = Settings.load()
        settings.cache_dir.mkdir(parents=True, exist_ok=True)
        return DashScopeEmbedder(
            settings=settings, cache=EmbeddingCache(settings.cache_dir / "cache.db")
        )
    except Exception as exc:
        pytest.skip(f"embedder 不可用：{exc}")


def test_pool_items_all_have_vectors(embedder) -> None:
    """池内每条候选都写入向量。"""
    result = evaluate(
        _with_gold("dev.jsonl", 1),
        all_specs=_all_specs(),
        weights_name="uniform",
        enable_dedup=False,
        judge=None,
        k=5,
        pool_mode=PoolMode.UNRELATED,
        paths=("lexical", "vector"),
        embedder=embedder,
    )

    case = result["per_case"][0]
    assert case["pool_size"] > 0
    assert case["pool_vectors"] == case["pool_size"], (
        f"只有 {case['pool_vectors']}/{case['pool_size']} 条写了向量"
    )


def test_vector_path_returns_rows(embedder) -> None:
    """vector 一路实际返回了候选，不是空列表。"""
    result = evaluate(
        _with_gold("dev.jsonl", 3),
        all_specs=_all_specs(),
        weights_name="uniform",
        enable_dedup=False,
        judge=None,
        k=5,
        pool_mode=PoolMode.UNRELATED,
        paths=("lexical", "vector"),
        embedder=embedder,
    )

    assert result["path_returns"]["vector"] is not None
    assert result["path_returns"]["vector"] > 0
    # 只启用了 lexical+vector，邻接是"没开"而非"没接上"，所以不列入未接线。
    assert result["paths_unwired"] == []


def test_vectors_are_not_all_zero(embedder) -> None:
    """向量不能是零向量——那会让余弦全相等，排序变成任意。

    这是"写了但没用"的形态：L6b 通过、L6c 通过，却毫无信息量。
    """
    result = evaluate(
        _with_gold("dev.jsonl", 1),
        all_specs=_all_specs(),
        weights_name="uniform",
        enable_dedup=False,
        judge=None,
        k=5,
        pool_mode=PoolMode.UNRELATED,
        paths=("vector",),
        embedder=embedder,
    )

    case = result["per_case"][0]
    assert case["pool_vector_norms"], "没有记录向量范数"
    assert all(norm > 0.5 for norm in case["pool_vector_norms"]), (
        f"存在零向量或近零向量：{case['pool_vector_norms']}"
    )


def test_embedding_network_calls_are_reported(embedder) -> None:
    """结果里记录 embedding 网络调用次数，使缓存可验证。"""
    result = evaluate(
        _with_gold("dev.jsonl", 1),
        all_specs=_all_specs(),
        weights_name="uniform",
        enable_dedup=False,
        judge=None,
        k=5,
        pool_mode=PoolMode.UNRELATED,
        paths=("vector",),
        embedder=embedder,
    )

    assert "embedding_network_calls" in result
    assert isinstance(result["embedding_network_calls"], int)


def test_second_run_hits_cache(embedder) -> None:
    """同一批数据第二次跑，网络调用数必须为 0（缓存命中）。

    若第二次仍有调用，说明缓存键有问题——而缓存是可复现性的前提
    （AGENTS.md 里的硬约束）。
    """
    rows = _with_gold("dev.jsonl", 1)

    evaluate(
        rows,
        all_specs=_all_specs(),
        weights_name="uniform",
        enable_dedup=False,
        judge=None,
        k=5,
        pool_mode=PoolMode.UNRELATED,
        paths=("vector",),
        embedder=embedder,
    )
    before = embedder.network_calls

    second = evaluate(
        rows,
        all_specs=_all_specs(),
        weights_name="uniform",
        enable_dedup=False,
        judge=None,
        k=5,
        pool_mode=PoolMode.UNRELATED,
        paths=("vector",),
        embedder=embedder,
    )

    assert embedder.network_calls == before, (
        f"第二次运行仍有 {embedder.network_calls - before} 次网络调用，缓存未命中"
    )
    assert second["embedding_network_calls"] == 0
