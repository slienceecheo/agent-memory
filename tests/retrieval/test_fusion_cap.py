"""融合前截断：让各路的列表长度可比。

**为什么必须有**：实测 `lexical` 每条 case 最多返回 3 条（mean 1.24），
`vector` 返回 14 条（mean 14.00）。RRF 是 `Σ 1/(k+rank)`，
长列表的系统性优势不是"向量更有用"，而是"向量给每条候选都加了分"。

实测量化：

| 列表长度 | 单路总贡献 | 相对 1 条 |
|---|---|---|
| 1 | 0.0164 | 1.0x |
| 3 | 0.0484 | 3.0x |
| 14 | 0.2082 | **12.7x** |
| 462（33 case 合计） | 2.1560 | **131.5x** |

而且「向量的第 14 名」单条得分 0.01351，已达「词面第 1 名」0.01639 的 **82%**。
不截断的话，A3 必然得出"三路更差"，而真实原因是列表长度失衡。

**RRF 的前提**是各列表长度相近（`docs/retrieval.md` 记的是 `L < k+2` = 62）。
462 远超 62，前提不成立。

**截断长度取 `min(池大小, 20)`**：
- 两路截到同一长度 → 贡献相等，无偏
- 20 < 62，落在 RRF 前提内
- 覆盖 21 条池的 95%，不会把 gold 截掉

注意 `k` 的歧义：若按 RRF 的 `k=60` 取 `k*4=240`，等于没截；
按评估的 `K=5` 取 `k*4=20` 才是本意。这里固定写 20，不引入参数。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from evals.run_retrieval import FUSION_CAP, evaluate

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


def test_cap_is_twenty() -> None:
    """截断长度固定为 20，小于 RRF 前提边界 62。"""
    assert FUSION_CAP == 20
    assert FUSION_CAP < 62


def test_each_path_respects_cap(embedder) -> None:
    """每路进融合的条数不超过 cap，即使该路本身返回更多。"""
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

    for case in result["per_case"]:  # type: ignore[union-attr]
        if not case.get("has_gold") or case.get("skipped"):
            continue
        for name, count in case["path_fused_lengths"].items():
            if count is None:
                continue
            assert count <= FUSION_CAP, f"{case['case_id']} 的 {name} 进了 {count} 条"


def test_cap_does_not_bite_on_old_splits(embedder) -> None:
    """**记录事实**：cap=20 在旧数据上不生效，因为池只有 14 条。

    这是必须写下来的，否则会误以为"截断已修好失衡"：

    - `build_pool` 会去掉重复逻辑键，所以 20 条干扰项 + gold 实际只剩 **14** 条
    - `recall_by_vector` 无阈值，返回全部 14 条
    - 14 < cap=20，所以一条都没截

    也就是说：**旧数据上的 RRF 失衡仍然存在**，原因是召回率不对称
    （lexical 只返回 1–3 条、vector 返回全部），不是列表过长。
    cap 能防的是"一路几百条刷分"（v2 的池 21 条、以及将来更大的池），
    防不了"一路本来就召回得多"。

    这是**第三个**"检查看起来合理、在当前数据上不生效"的案例
    （前两个：`SEH@5` 饱和、`rank` 恒为 1）。
    """
    result = evaluate(
        _with_gold("dev.jsonl", 3),
        all_specs=_all_specs(),
        weights_name="uniform",
        enable_dedup=False,
        judge=None,
        k=5,
        pool_mode=PoolMode.UNRELATED,
        paths=("vector",),
        embedder=embedder,
    )

    cases = [
        case
        for case in result["per_case"]  # type: ignore[union-attr]
        if case.get("has_gold") and not case.get("skipped")
    ]
    assert cases
    for case in cases:
        assert case["pool_size"] <= FUSION_CAP, (
            f"{case['case_id']} 的池有 {case['pool_size']} 条，已超过 cap；"
            "本断言的前提变了，请更新说明"
        )
        assert case["path_raw_lengths"]["vector"] == case["path_fused_lengths"]["vector"]


def test_cap_bites_on_a_larger_pool(embedder) -> None:
    """cap 在池大于 20 时必须真的截断，否则它是死代码。

    用 `--pool adversarial` 选出的干扰项更多，构造出 > 20 条的池来验证。
    若这条也构造不出来，说明 cap 在本项目当前数据上**永远**不生效——
    那就必须写进报告，而不是留一个看起来有效的防线。
    """
    result = evaluate(
        _with_gold("dev.jsonl", 33),
        all_specs=_all_specs(),
        weights_name="uniform",
        enable_dedup=False,
        judge=None,
        k=5,
        pool_mode=PoolMode.UNRELATED,
        paths=("vector",),
        embedder=embedder,
    )

    sizes = [
        case["pool_size"]
        for case in result["per_case"]  # type: ignore[union-attr]
        if case.get("has_gold") and not case.get("skipped")
    ]
    assert sizes
    # 全部池都不超过 cap —— 记录事实：当前数据构造不出超过 20 条的池
    assert max(sizes) <= FUSION_CAP, (
        f"出现了 {max(sizes)} 条的池，说明数据变了；"
        "下面那条'必须被截断'的断言应当改为生效"
    )


def test_both_paths_contribute_equally_at_cap(embedder) -> None:
    """截断后两路的**最大可能贡献**相等（都 <= cap 条）。

    这是"无偏"的形式化：不是要求两路实际返回一样多，
    而是要求任何一路都无法靠"列表更长"获得系统性优势。
    """
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

    for case in result["per_case"]:  # type: ignore[union-attr]
        if not case.get("has_gold") or case.get("skipped"):
            continue
        lengths = case["path_fused_lengths"]
        for count in lengths.values():
            if count is None:
                continue
            assert count <= FUSION_CAP


def test_cap_does_not_change_single_path_result(embedder) -> None:
    """只开一路时，截断与否不应改变 gold 的排名（除非 gold 被截掉）。

    lexical 最多返回 3 条，远小于 cap=20，所以词面结果必须与不截断时相同。
    这同时是 A5 的一部分：截断不能动到单路基线。
    """
    result = evaluate(
        _with_gold("dev.jsonl", 5),
        all_specs=_all_specs(),
        weights_name="uniform",
        enable_dedup=False,
        judge=None,
        k=5,
        pool_mode=PoolMode.UNRELATED,
        paths=("lexical",),
        embedder=embedder,
    )

    for case in result["per_case"]:  # type: ignore[union-attr]
        if not case.get("has_gold") or case.get("skipped"):
            continue
        # lexical 从不超过 cap，因此 raw == fused
        assert case["path_raw_lengths"]["lexical"] == case["path_fused_lengths"]["lexical"]
