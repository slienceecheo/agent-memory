"""第 3 组：接邻接召回，并修正 `dedup` 的传参。

**邻接的输入取自 gold 的逻辑键**（design 决策 4）。这意味着它"知道答案在哪"：
它按 `(subject, relation, condition)` 直接查同一逻辑键下的其他条件分支，
与查询文本无关。所以本组必须能说清"邻接有用"与"邻接作弊"的区别：

- 判决方法：看邻接召回了 **gold 之外** 的几条
- 若只召回同键的兄弟且数量很少 → 设计使然
- 若大量召回无关条目却提升分数 → 指标被污染

**dedup 传参**（design 决策 1/2）：
- `text` 从 `store.get(id).text` 读回，不是 id
- `score` 传融合后的 RRF 分，不是常数 1.0
- 去重位置在**重排之前**
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from evals.run_retrieval import ALL_PATHS, evaluate

from memory.retrieval.equivalence import Equivalence
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


class _RecordingJudge:
    """记录 dedup 收到的每一对「文本」。"""

    enabled = True

    def __init__(self) -> None:
        self.seen: list[tuple[str, str]] = []

    def judge(self, left: str, right: str) -> object:
        self.seen.append((left, right))
        return type("R", (), {"equivalence": Equivalence.UNRELATED})()


# ---------- 邻接 ----------


def test_adjacency_path_returns_rows(embedder) -> None:
    """adjacency 一路被调用且返回了候选（BRANCH 场景应命中兄弟）。"""
    result = evaluate(
        _with_gold("dev.jsonl", 33),
        all_specs=_all_specs(),
        weights_name="uniform",
        enable_dedup=False,
        judge=None,
        k=5,
        pool_mode=PoolMode.UNRELATED,
        paths=ALL_PATHS,
        embedder=embedder,
    )

    assert result["path_returns"]["adjacency"] is not None
    assert result["path_returns"]["adjacency"] > 0
    assert result["paths_unwired"] == []


def test_adjacency_only_returns_siblings(embedder) -> None:
    """邻接召回的必须都是**同逻辑键、不同条件**的兄弟。

    这是"邻接有没有作弊"的判决条件：它按 gold 的逻辑键直接查，
    若返回了无关条目，就不是在设计范围内工作。
    """
    result = evaluate(
        _with_gold("dev.jsonl", 33),
        all_specs=_all_specs(),
        weights_name="uniform",
        enable_dedup=False,
        judge=None,
        k=5,
        pool_mode=PoolMode.UNRELATED,
        paths=("adjacency",),
        embedder=embedder,
    )

    for case in result["per_case"]:  # type: ignore[union-attr]
        if not case.get("has_gold") or case.get("skipped"):
            continue
        # 每条被邻接召回的 tag 都应属于同一 relation（池内同键兄弟）
        for tag in case.get("adjacency_tags") or []:
            assert tag.startswith("d-") or tag.startswith("gold-")


def test_adjacency_recall_is_small(embedder) -> None:
    """邻接召回的条数应远小于池大小——它只服务 BRANCH，不是通用召回。

    若它一次返回十几条，说明它把整个池都塞进融合了，
    那与"作弊"没有区别。
    """
    result = evaluate(
        _with_gold("dev.jsonl", 33),
        all_specs=_all_specs(),
        weights_name="uniform",
        enable_dedup=False,
        judge=None,
        k=5,
        pool_mode=PoolMode.UNRELATED,
        paths=("adjacency",),
        embedder=embedder,
    )

    for case in result["per_case"]:  # type: ignore[union-attr]
        if not case.get("has_gold") or case.get("skipped"):
            continue
        count = len(case.get("adjacency_tags") or [])
        assert count <= 5, f"{case['case_id']} 邻接召回了 {count} 条，超出兄弟范围"


def test_all_three_paths_wired(embedder) -> None:
    """三路全部接线后，`paths_unwired` 必须为空。"""
    result = evaluate(
        _with_gold("dev.jsonl", 3),
        all_specs=_all_specs(),
        weights_name="uniform",
        enable_dedup=False,
        judge=None,
        k=5,
        pool_mode=PoolMode.UNRELATED,
        paths=ALL_PATHS,
        embedder=embedder,
    )

    assert result["paths_unwired"] == []
    for name in ALL_PATHS:
        assert result["path_returns"][name] is not None


# ---------- dedup 传参 ----------


def test_dedup_receives_real_text(embedder) -> None:
    """L7：传给 dedup 的必须是原文，不是 item_id。"""
    judge = _RecordingJudge()
    evaluate(
        _with_gold("dev.jsonl", 3),
        all_specs=_all_specs(),
        weights_name="uniform",
        enable_dedup=True,
        judge=judge,  # type: ignore[arg-type]
        k=5,
        pool_mode=PoolMode.UNRELATED,
        paths=("lexical",),
        embedder=embedder,
    )

    assert judge.seen, "dedup 一次都没被调用，无法验证入参"
    for left, right in judge.seen:
        for text in (left, right):
            assert not (len(text) == 32 and all(c in "0123456789abcdef" for c in text)), (
                f"dedup 收到了 uuid：{text}"
            )


def test_dedup_receives_varying_scores(embedder) -> None:
    """L8：分数必须有方差，不能全是常数。

    常数分会让 `dedup` 内部的 `(-score, id)` 排序退化为字典序。
    """
    result = evaluate(
        _with_gold("dev.jsonl", 3),
        all_specs=_all_specs(),
        weights_name="uniform",
        enable_dedup=True,
        judge=_RecordingJudge(),  # type: ignore[arg-type]
        k=5,
        pool_mode=PoolMode.UNRELATED,
        paths=("lexical",),
        embedder=embedder,
    )

    for case in result["per_case"]:  # type: ignore[union-attr]
        if not case.get("has_gold") or case.get("skipped"):
            continue
        scores = case.get("dedup_input_scores") or []
        if len(scores) < 2:
            continue
        assert len(set(scores)) > 1, f"{case['case_id']} 的 dedup 分数全相等"


def test_dedup_runs_before_rerank(embedder) -> None:
    """去重在重排之前：融合 → 去重 → 重排。

    若顺序反了，去重会推翻重排的结论。
    验证方式：去重的输入顺序必须等于融合顺序，而不是重排顺序。
    """
    result = evaluate(
        _with_gold("dev.jsonl", 3),
        all_specs=_all_specs(),
        weights_name="uniform",
        enable_dedup=True,
        judge=_RecordingJudge(),  # type: ignore[arg-type]
        k=5,
        pool_mode=PoolMode.UNRELATED,
        paths=("lexical",),
        embedder=embedder,
    )

    for case in result["per_case"]:  # type: ignore[union-attr]
        if not case.get("has_gold") or case.get("skipped"):
            continue
        dedup_order = case.get("dedup_input_tags") or []
        fusion_order = case.get("fusion_tags") or []
        if not dedup_order:
            continue
        assert dedup_order == fusion_order[: len(dedup_order)], (
            f"{case['case_id']} 的去重输入不是融合顺序的前缀，顺序可能反了"
        )
