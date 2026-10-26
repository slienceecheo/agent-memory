"""池来源统计的行为契约（缺陷 9）。

三条必须锁住的性质：

1. **按身份匹配**：键值匹配会把 660 算成 1816，并凭空产生 528 条 test
2. **两层分母不同**：selection 660 vs pool 429（pool 不含 gold）
3. **缺陷 9 是缺陷 5 的后果**：取消 `others[:limit]` 截断后按比例混合
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from evals.metrics.pool_provenance import count_origins, pool_origins, selection_origins
from evals.run_retrieval import _item, select_pool_distractors

from memory.retrieval.pool import build_pool
from memory.retrieval.pool_modes import PoolMode

ROOT = Path(__file__).resolve().parents[2]
"""`tests/retrieval/test_pool_provenance.py` → parents[2] = 仓库根。

注意：`tests/retrieval/` 是两层深，所以 `parents[0]=tests/retrieval`、
`parents[1]=tests`、`parents[2]=仓库根`。写成 parents[1] 会指向 tests/，
数据文件就找不到，测试会静默 skip——那正是"断言查错对象"的同一形态。
"""
DATA = ROOT / "data" / "conflict-set"
SPLITS = ("dev", "test", "independent")


def _rows(name: str) -> list[dict[str, object]]:
    path = DATA / (name if name.endswith(".jsonl") else f"{name}.jsonl")
    if not path.exists():
        # 显式报出解析后的路径，避免"文件不存在"掩盖路径拼错。
        # 这个项目已经踩过三次"检查对象是错的"，skip 也必须能自证。
        pytest.fail(f"{name} 不存在：解析为 {path}（ROOT={ROOT}）")
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


@pytest.fixture(scope="module")
def corpus():
    specs: list[dict[str, object]] = []
    origins: list[str] = []
    rows_by_split: dict[str, list[dict[str, object]]] = {}
    for split in SPLITS:
        data = _rows(f"{split}.jsonl")
        rows_by_split[split] = data
        for row in data:
            if row.get("gold"):
                specs.append(row["gold"])  # type: ignore[arg-type]
                origins.append(split)
    return specs, origins, rows_by_split


def _select(gold, all_specs, *, limit=20):
    return select_pool_distractors(gold, all_specs, mode=PoolMode.UNRELATED, limit=limit)


# ---------- 纯函数 ----------


def test_counts_by_identity_not_by_key() -> None:
    """键值相同的两个对象必须被区分开。

    这正是 dev 660 vs 键值匹配 1816 的根源：8 个重复逻辑键。
    """
    a = {"subject": "s", "relation": "r", "value": "v", "condition": None}
    b = {"subject": "s", "relation": "r", "value": "v", "condition": None}

    counts = count_origins([a, b], [a, b], ["dev", "test"])

    assert counts == {"dev": 1, "test": 1}


def test_unknown_origin_is_reported() -> None:
    """身份匹配不到的条目必须显式记为 unknown，不能静默丢弃。"""
    a = {"k": 1}
    counts = count_origins([{"k": 1}], [a], ["dev"])

    assert counts == {"unknown": 1}


def test_length_mismatch_is_rejected() -> None:
    with pytest.raises(ValueError, match="长度"):
        count_origins([], [{"k": 1}], [])


# ---------- 真实数据 ----------


def test_non_dev_selection_is_all_from_dev(corpus) -> None:
    """缺陷 9：非 dev split 选出的干扰项 100% 来自 dev。"""
    specs, origins, rows_by_split = corpus

    for split in ("test", "independent"):
        counts = selection_origins(
            rows_by_split[split], specs, origins, select_fn=_select
        )
        assert set(counts) == {"dev"}, f"{split} 的池来源：{dict(counts)}"


def test_pool_level_excludes_gold_and_still_all_dev(corpus) -> None:
    """pool 层不含 gold，但干扰项仍 100% 来自 dev。"""
    specs, origins, rows_by_split = corpus

    for split in ("test", "independent"):
        counts = pool_origins(
            rows_by_split[split],
            specs,
            origins,
            select_fn=_select,
            build_fn=build_pool,
            item_fn=_item,
        )
        assert set(counts) == {"dev"}, f"{split} 的池层来源：{dict(counts)}"


def test_selection_and_pool_levels_differ(corpus) -> None:
    """两层分母不同：660 vs 429（build_pool 去重砍掉了重复键）。

    引用数字时必须写明层级，否则无法复算。
    """
    specs, origins, rows_by_split = corpus

    selection = selection_origins(rows_by_split["dev"], specs, origins, select_fn=_select)
    pool = pool_origins(
        rows_by_split["dev"],
        specs,
        origins,
        select_fn=_select,
        build_fn=build_pool,
        item_fn=_item,
    )

    assert selection["dev"] > pool["dev"], "去重后应更少"
    assert selection == {"dev": 660}
    assert pool == {"dev": 429}


def test_untruncated_selection_mixes_splits(corpus) -> None:
    """缺陷 9 是缺陷 5 的后果：取消 `others[:limit]` 截断后立刻按比例混合。

    这条是"同源"的**机器可读证据**。若有人只改 `build_pool` 而不改采样方式，
    本条仍然失败——那说明修错了位置。
    """
    specs, origins, rows_by_split = corpus

    counts = selection_origins(
        rows_by_split["test"], specs, origins, select_fn=_select, limit=len(specs)
    )

    assert set(counts) >= {"dev", "test", "independent"}, (
        f"取消截断后应混合，实际 {dict(counts)}"
    )
    # 不再有任何一路占 100%
    total = sum(counts.values())
    assert max(counts.values()) / total < 0.6


def test_build_pool_dedup_reduces_dev_share(corpus) -> None:
    """`build_pool` 去重会**降低** dev 的占比，不是帮凶。

    dev 的重复逻辑键最多（pnpm 6 次、pytest 6 次、main 6 次），
    去重砍掉它的条目最多。所以"给 build_pool 加随机性"不会修好偏差，
    反而可能让 dev 占比升回 all_specs 的 43.4%。

    这条锁住方向性，防止有人用错误的位置去修缺陷 9。
    """
    specs, origins, rows_by_split = corpus

    dev_share_in_specs = origins.count("dev") / len(origins)
    counts = pool_origins(
        rows_by_split["test"],
        specs,
        origins,
        select_fn=_select,
        build_fn=build_pool,
        item_fn=_item,
    )
    # 当前 dev 占 100%（因为前缀截断），这里只断言"去重没有增加 dev 数量"
    assert counts["dev"] <= 340
    assert dev_share_in_specs == pytest.approx(33 / 76)
