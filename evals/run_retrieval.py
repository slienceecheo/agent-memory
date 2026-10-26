"""检索评测入口。

    uv run python -m evals.run_retrieval --split independent
    uv run python -m evals.run_retrieval --split independent --no-dedup
    uv run python -m evals.run_retrieval --split independent --weights base_heavy

三个设计约束：

1. **每条场景独立建库**：池里只有该场景的候选，跨场景不污染
2. **保留未截断的融合排名**：否则"排序过低"与"重排丢弃"无法区分
3. **运行次数可验证**：结果 JSON 记录 `run_count`，使"test 只跑一次"可检查
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

import numpy as np

from evals.metrics.retrieval import (
    Attribution,
    attribute_failure,
    attribution_breakdown,
    seh_at_k,
    srs,
)
from memory.config import PROJECT_ROOT, Settings
from memory.embedding.cache import EmbeddingCache
from memory.embedding.dashscope import DashScopeEmbedder
from memory.llm.cache import ResponseCache
from memory.llm.client import LLMClient
from memory.retrieval.adjacency import recall_by_adjacency
from memory.retrieval.condition import condition_match
from memory.retrieval.dedup import dedup
from memory.retrieval.equivalence import EquivalenceJudge
from memory.retrieval.fusion import rrf
from memory.retrieval.lexical import recall_by_lexical
from memory.retrieval.pool import build_pool
from memory.retrieval.pool_modes import PoolMode
from memory.retrieval.rerank import (
    PREREGISTERED_WEIGHTS,
    FeatureScores,
    Ranked,
    authority_score,
    rerank,
    rrf_norm,
    status_score,
)
from memory.retrieval.vector import recall_by_vector
from memory.store.models import Authority, MemoryItem, Scope, Source, Status
from memory.store.sqlite import SqliteStore

ROOT = PROJECT_ROOT
DATA = ROOT / "data" / "conflict-set"
OUT_DIR = ROOT / "results"
BASE_TIME = datetime(2026, 1, 1, tzinfo=UTC)
DEFAULT_K = 5

#: 三路召回的规范顺序。顺序固定，使 `paths_enabled` 可逐位比较。
ALL_PATHS: tuple[str, ...] = ("lexical", "vector", "adjacency")

#: 已实现但**尚未接进评测入口**的路径。
#: 它们被启用时记为 `null` + 出现在 `paths_unwired`，而不是 `0`——
#: `0` 的意思是"跑了但返回空"，与"没接上"是两件不同的事。
#:
#: 三路已全部接线，本集合为空。保留这个机制是为了将来新增路径时
#: 仍能区分"没开"与"没接上"。
_UNWIRED: frozenset[str] = frozenset()


#: 融合前每路截断到的条数。
#:
#: **为什么是 20**：20 相对 RRF 的 `k=60` 是 1/3，满足 `L << k`。
#: **不要按 `k*4` 推算**——`k` 是平滑常数，不是"列表该有多长"的基准。
#: 按 `60*4=240` 算会得到远超 `k` 的长度，等于没截。
#:
#: **为什么截**：实测 lexical 每 case 最多 3 条、vector 约 14 条，
#: 而 RRF 是 `Σ 1/(k+rank)`——长列表靠"条数多"系统性占优，
#: 不是靠"更相关"。向量第 14 名单条得分已是词面第 1 名的 82%。
#:
#: **已知限制**：本 cap 在旧数据上**不生效**（池经 `build_pool` 去重后只剩 14 条，
#: 小于 20）。它防的是"一路几百条刷分"，防不了"一路本来就召回得多"。
FUSION_CAP = 20


class EmbedderLike(Protocol):
    """评测只需要 `embed` 与 `network_calls` 两个成员。"""

    network_calls: int

    def embed(self, text: str, *, text_type: str) -> Any: ...


def parse_paths(raw: str | None) -> tuple[str, ...]:
    """解析 `--paths`：**白名单**语义，逗号分隔。

    为什么是白名单而不是减法（`all,-adjacency`）：
    - 白名单可枚举，2^3=8 种全部合法，不存在自相矛盾的组合
    - `""` 天然表示"全关"，直接对应规格的"全部关闭返回空"
    - 减法需要解析负号，多一层出错空间

    `None` 表示用默认值（全开）——新用户跑一遍应看到完整行为。
    """
    if raw is None:
        return ALL_PATHS

    if not raw.strip():
        return ()

    seen: list[str] = []
    for token in raw.split(","):
        name = token.strip().lower()
        if not name:
            continue
        if name not in ALL_PATHS:
            raise ValueError(
                f"未知的召回路径 {name!r}；可用：{', '.join(ALL_PATHS)}"
            )
        if name not in seen:
            seen.append(name)

    # 按规范顺序输出，使 paths_enabled 与调用方传入顺序无关
    return tuple(name for name in ALL_PATHS if name in seen)


def _rows(path: Path) -> list[dict[str, object]]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _item(
    row: dict[str, object], spec: dict[str, object], *, tag: str, text: str | None
) -> MemoryItem:
    condition = spec.get("condition")
    return MemoryItem(
        owner="default",
        scope=Scope.PROJECT,
        subject=str(spec["subject"]),
        relation=str(spec["relation"]),
        value=str(spec["value"]),
        condition=str(condition) if condition else None,
        status=Status.ACTIVE,
        valid_from=BASE_TIME,
        valid_to=None,
        recorded_at=BASE_TIME,
        authority=Authority(str(spec.get("authority") or "user_direct")),
        source=Source(session_id=tag),
        text=text,
        id=f"{tag}",
    )


def _embedding_text(item: MemoryItem) -> str:
    """池内条目送去向量化的文本。

    与 `items_fts` 的索引内容保持一致（`subject + relation + value + 原文`）。
    **只用 value 会让"深夜"这类短值与其他短值难以区分**——那正是
    C4 里干扰项无法竞争的老问题换一个位置。

    用 `document` 侧：与查询的 `query` 侧必须分开，实测同文本两侧余弦仅 0.842。
    """
    parts = [item.subject, item.relation, item.value]
    if item.text:
        parts.append(item.text)
    return " ".join(parts)


def select_pool_distractors(
    spec: dict[str, object],
    all_specs: list[dict[str, object]],
    *,
    mode: PoolMode,
    limit: int,
) -> list[dict[str, object]]:
    """按难度模式选干扰项的 spec（在构造成 MemoryItem 之前筛选）。

    **必须在 spec 层面筛**，因为 `PoolMode.SAME_RELATION` 需要看 relation，
    而 `MemoryItem` 的构造需要 text 等字段的额外处理。
    """
    gold_key = (spec.get("subject"), spec.get("relation"), spec.get("condition"))
    others = [
        candidate
        for candidate in all_specs
        if (candidate.get("subject"), candidate.get("relation"), candidate.get("condition"))
        != gold_key
    ]

    if mode is PoolMode.UNRELATED:
        return others[:limit]

    same_relation = [
        candidate for candidate in others if candidate.get("relation") == spec.get("relation")
    ]
    if mode is PoolMode.SAME_RELATION:
        return same_relation[:limit]

    gold_chars = set(str(spec.get("value") or ""))
    return [
        candidate
        for candidate in same_relation
        if gold_chars & set(str(candidate.get("value") or ""))
    ][:limit]


def evaluate_case(
    row: dict[str, object],
    *,
    all_specs: list[dict[str, object]],
    weights_name: str,
    enable_dedup: bool,
    judge: EquivalenceJudge | None,
    k: int,
    pool_mode: PoolMode = PoolMode.UNRELATED,
    paths: tuple[str, ...] = ALL_PATHS,
    embedder: EmbedderLike | None = None,
) -> dict[str, object]:
    """评估单条场景。返回该条的排名、指标与归因。"""
    gold_spec = row.get("gold")
    query = str(row["query"])
    weights = PREREGISTERED_WEIGHTS[weights_name]

    if not gold_spec:
        return {
            "case_id": row["id"],
            "has_gold": False,
            "pool_size": 0,
            "rank_after_fusion": None,
            "rank_after_rerank": None,
            "seh": None,
            "srs": None,
            "attribution": None,
        }

    selected = select_pool_distractors(gold_spec, all_specs, mode=pool_mode, limit=20)

    # 池太小就无法评估：排名会退化成"只有 gold 一条"，SEH 恒为 1。
    # 这是数据的真实约束（independent 集 28/29 个 relation 只出现 1 次），
    # 必须显式跳过并计数，而不是给出一个虚高的分数。
    if len(selected) + 1 <= k:
        return {
            "case_id": row["id"],
            "has_gold": True,
            "skipped": True,
            "skip_reason": f"池只有 {len(selected) + 1} 条，不足 K={k}",
            "pool_size": len(selected) + 1,
            "rank_after_fusion": None,
            "rank_after_rerank": None,
            "seh": None,
            "srs": None,
            "attribution": None,
        }

    distractors = [
        _item({"text": ""}, spec, tag=f"d-{row['id']}-{i}", text=None)
        for i, spec in enumerate(selected)
    ]

    with tempfile.TemporaryDirectory() as directory:
        store = SqliteStore(Path(directory) / "eval.db")
        try:
            gold = _item(row, gold_spec, tag=f"gold-{row['id']}", text=str(row.get("text") or ""))
            pool = build_pool(gold, distractors, seed=0)

            id_map: dict[str, MemoryItem] = {}
            tag_by_id: dict[str, str] = {}
            vector_norms: list[float] = []
            for entry in pool.items:
                import dataclasses

                embedding = None
                if "vector" in paths and embedder is not None:
                    embedding = embedder.embed(_embedding_text(entry), text_type="document")
                    vector_norms.append(float(np.linalg.norm(embedding)))

                stored = store.insert(
                    dataclasses.replace(entry, id=""),
                    reason="pool",
                    actor="harness",
                    embedding=embedding,
                )
                id_map[entry.id] = stored
                # entry.id 是构造时的稳定 tag（`gold-<case_id>` / `d-<case_id>-<i>`），
                # stored.id 是 uuid4，跨运行不可比。A5 只能比 tag。
                tag_by_id[stored.id] = entry.id

            gold_id = id_map[pool.gold_id].id

            # 第 1 组：只加观测，不改召回逻辑。
            # vector / adjacency 尚未接进本入口（见 _UNWIRED），因此它们的
            # 返回值记为 None，而不是 0——"没接上"与"跑了但空"是两件事。
            path_returns: dict[str, int | None] = {name: None for name in ALL_PATHS}
            adjacency_tags: list[str] = []
            path_raw_lengths: dict[str, int | None] = {name: None for name in ALL_PATHS}
            path_fused_lengths: dict[str, int | None] = {name: None for name in ALL_PATHS}
            ranked_lists: dict[str, list[str]] = {}

            def _record(name: str, ids: list[str]) -> None:
                """记录原长与截断后长度，并把截断结果放进融合输入。"""
                path_raw_lengths[name] = len(ids)
                capped = ids[:FUSION_CAP]
                path_fused_lengths[name] = len(capped)
                path_returns[name] = len(ids)
                ranked_lists[name] = capped

            if "lexical" in paths:
                lexical = [
                    i.id for i in recall_by_lexical(store, query, limit=len(pool.items))
                ]
                _record("lexical", lexical)

            if "vector" in paths and embedder is not None:
                query_vector = embedder.embed(query, text_type="query")
                hits = recall_by_vector(store, query_vector, limit=len(pool.items))
                _record("vector", [i.id for i in hits])

            if "adjacency" in paths:
                # 邻接的输入取自 **gold 的逻辑键**（design 决策 4）：
                # 它的语义是"同一逻辑键下的其他条件分支"，与查询文本无关，
                # 所以它天生"知道答案在哪"。为防白送分，只取同键兄弟，
                # 并把召回条数单独记录供 A3 判决。
                adjacency_hits = recall_by_adjacency(
                    store,
                    subject=str(gold_spec["subject"]),
                    relation=str(gold_spec["relation"]),
                    condition=(
                        str(gold_spec["condition"]) if gold_spec.get("condition") else None
                    ),
                    owner="default",
                    limit=len(pool.items),
                )
                adjacency_tags = [tag_by_id.get(i.id, i.id) for i in adjacency_hits]
                _record("adjacency", [i.id for i in adjacency_hits])

            fused = rrf(ranked_lists, k=60) if ranked_lists else []
            fused_order = [entry.item_id for entry in fused]
            recalled_count = len(fused_order)
            rank_fusion = (
                fused_order.index(gold_id) + 1 if gold_id in fused_order else None
            )

            score_by_id = {entry.item_id: entry.score for entry in fused}
            max_score = max(score_by_id.values()) if score_by_id else 0.0
            query_condition = row.get("condition")

            # 去重位置：**融合后、重排前**（design 决策 1）。
            # 若放在重排之后，一次合并就可能干掉重排排出的第 1 名，
            # 等于让二分类模型覆盖四特征权重。
            dedup_input_tags: list[str] = []
            dedup_input_scores: list[float] = []
            if enable_dedup and judge is not None and fused_order:
                # 批量回读原文（design 决策 2）：逐条 store.get 会把单次评估的
                # 查询数从 O(1) 推到 O(N)。
                placeholders = ",".join("?" * len(fused_order))
                rows_by_id = {
                    row_[0]: row_[1]
                    for row_ in store.conn.execute(
                        f"SELECT id, source_text FROM items WHERE id IN ({placeholders})",
                        tuple(fused_order),
                    ).fetchall()
                }
                # 入参三元组是 (id, text, score)：
                # text 必须是原文、score 必须是真实融合分——
                # 常数分会让 dedup 内部的 (-score, id) 排序退化为字典序。
                texts = [
                    (
                        item_id,
                        rows_by_id.get(item_id) or tag_by_id.get(item_id, item_id),
                        score_by_id[item_id],
                    )
                    for item_id in fused_order
                ]
                kept, _ = dedup(texts, judge=judge, top_k=k)
                dedup_input_tags = [tag_by_id.get(e[0], e[0]) for e in texts]
                dedup_input_scores = [float(e[2]) for e in texts]
                fused_after_dedup = [e[0] for e in kept]
            else:
                fused_after_dedup = fused_order

            candidates = []
            for item_id in fused_after_dedup:
                item = store.get(item_id)
                candidates.append(
                    _RerankCandidate(
                        item_id=item_id,
                        features=FeatureScores(
                            base=rrf_norm(score_by_id[item_id], max_score=max_score),
                            condition=condition_match(
                                str(query_condition) if query_condition else None,
                                item.condition,
                            ),
                            authority=authority_score(item.authority),
                            status=status_score(item.status),
                        ),
                    )
                )

            ranked: list[Ranked] = rerank(candidates, weights=weights)
        finally:
            store.close()

    order = [item.item_id for item in ranked]

    rank_rerank = order.index(gold_id) + 1 if gold_id in order else None

    attribution = attribute_failure(
        gold_in_pool=True,
        rank_after_fusion=rank_fusion,
        rank_after_rerank=rank_rerank,
        k=k,
    )

    return {
        "case_id": row["id"],
        "has_gold": True,
        "pool_size": len(pool.items),
        "rank_after_fusion": rank_fusion,
        "rank_after_rerank": rank_rerank,
        # 以下两项用**稳定 tag**，不是 uuid4：A5 要做跨运行逐位比较，
        # 而 uuid 每次运行都不同（实测两次建库 id 完全不同）。
        "fusion_tags": [tag_by_id.get(item_id, item_id) for item_id in fused_order],
        "adjacency_tags": adjacency_tags,
        "dedup_input_tags": dedup_input_tags,
        "dedup_input_scores": dedup_input_scores,
        "rerank_top1_tag": tag_by_id.get(order[0], order[0]) if order else None,
        "path_returns": path_returns,
        "path_raw_lengths": path_raw_lengths,
        "path_fused_lengths": path_fused_lengths,
        "fusion_cap": FUSION_CAP,
        # A5 的效力取决于"排名有没有余地"：
        # 池内只有 1 条候选时，所有排名指标在任何实现下都必然相同，
        # 此时通过只能算烟雾测试。用一列把它显式化，不靠人记得看池大小。
        "a5_strength": "strong" if recalled_count >= 2 else "weak",
        "pool_vectors": len(vector_norms),
        "pool_vector_norms": [round(norm, 4) for norm in vector_norms],
        "seh": seh_at_k(rank=rank_rerank, k=k),
        "srs": srs(rank=rank_rerank),
        "attribution": attribution.value if attribution else None,
    }


class _RerankCandidate:
    def __init__(self, *, item_id: str, features: FeatureScores) -> None:
        self.item_id = item_id
        self.features = features


def evaluate(
    rows: list[dict[str, object]],
    *,
    all_specs: list[dict[str, object]],
    weights_name: str,
    enable_dedup: bool,
    judge: EquivalenceJudge | None,
    k: int = DEFAULT_K,
    pool_mode: PoolMode = PoolMode.UNRELATED,
    paths: tuple[str, ...] = ALL_PATHS,
    embedder: EmbedderLike | None = None,
) -> dict[str, object]:
    calls_before = embedder.network_calls if embedder is not None else 0
    per_case = [
        evaluate_case(
            row,
            all_specs=all_specs,
            weights_name=weights_name,
            enable_dedup=enable_dedup,
            judge=judge,
            k=k,
            pool_mode=pool_mode,
            paths=paths,
            embedder=embedder,
        )
        for row in rows
    ]

    scored = [item for item in per_case if item["has_gold"] and not item.get("skipped", False)]
    skipped = [item for item in per_case if item.get("skipped", False)]
    seh_values = [bool(item["seh"]) for item in scored]
    srs_values = [float(item["srs"]) for item in scored]

    # 路径返回值按整批汇总：启用但没接上的记 None，跑了的记总条数。
    path_totals: dict[str, int | None] = {}
    for name in ALL_PATHS:
        if name not in paths:
            path_totals[name] = None
            continue
        observed = [
            item["path_returns"][name]  # type: ignore[index]
            for item in per_case
            if isinstance(item.get("path_returns"), dict)
            and item["path_returns"].get(name) is not None  # type: ignore[union-attr]
        ]
        path_totals[name] = sum(observed) if observed else None

    return {
        "weights": weights_name,
        "pool_mode": pool_mode.value,
        "dedup": enable_dedup,
        "k": k,
        "cases": len(per_case),
        "with_gold": len(scored),
        "without_gold": len(per_case) - len([i for i in per_case if i["has_gold"]]),
        "skipped_small_pool": len(skipped),
        "paths_enabled": list(paths),
        # 只有"启用了但代码里还没有调用点"才算未接线。
        # 未启用的路径是"没开"，不是"没接上"——两者诊断方向不同。
        "paths_unwired": [name for name in paths if name in _UNWIRED],
        "path_returns": path_totals,
        "embedding_network_calls": (
            embedder.network_calls - calls_before if embedder is not None else 0
        ),
        "seh_at_k": sum(seh_values) / len(seh_values) if seh_values else 0.0,
        "srs": sum(srs_values) / len(srs_values) if srs_values else 0.0,
        "attribution": attribution_breakdown(
            [
                None if item["attribution"] is None else Attribution(str(item["attribution"]))
                for item in scored
            ]
        ),
        "per_case": per_case,
    }


def _assert_writable(out: Path, result: dict[str, object], *, overwrite: bool) -> None:
    """写结果前先做**实验身份检查**。

    缺陷 12：归档文件名不区分实际参与测量的路径集合。
    默认全开时 `paths_tag` 是空串，输出路径与 C4 归档完全同名——
    而 C4 归档是在"默认全开、但只接了词面"的代码下产生的。
    于是任何一次默认参数的重跑都会**静默覆盖归档**，并把两个不同实验
    算进同一个 `run_count`（实测：3 → 4）。

    因此：目标文件已存在且其 `paths_enabled` 与本次不同时，拒绝写入。
    归档没有 `paths_enabled` 字段（`None`）视为"未知"，同样拒绝。
    """
    if not out.exists() or overwrite:
        return
    try:
        existing = json.loads(out.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        existing = {}
    previous = existing.get("paths_enabled")
    current = result.get("paths_enabled")
    if previous != current:
        raise SystemExit(
            f"拒绝覆盖 {out.name}：\n"
            f"  已有文件的 paths_enabled = {previous!r}（None 表示未知，多为 C4 归档）\n"
            f"  本次运行的 paths_enabled = {current!r}\n"
            "这会把两个不同的实验写进同一个文件与同一份 run_count。\n"
            "若确实要覆盖，请显式加 --overwrite；否则换 --paths 或换 --out。"
        )


def _bump_run_count(out: Path) -> int:
    """记录同一配置被跑了几次，使"test 只跑一次"可验证。"""
    counter = OUT_DIR / "retrieval-run-count.json"
    counts: dict[str, int] = {}
    if counter.exists():
        counts = json.loads(counter.read_text(encoding="utf-8"))
    key = out.name
    counts[key] = counts.get(key, 0) + 1
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    counter.write_text(json.dumps(counts, ensure_ascii=False, indent=2), encoding="utf-8")
    return counts[key]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="evals.run_retrieval")
    parser.add_argument("--split", default="independent", choices=["dev", "test", "independent"])
    parser.add_argument("--weights", default="uniform", choices=sorted(PREREGISTERED_WEIGHTS))
    parser.add_argument("--no-dedup", action="store_true")
    parser.add_argument("--k", type=int, default=DEFAULT_K)
    parser.add_argument(
        "--pool",
        default="unrelated",
        choices=[mode.value for mode in PoolMode],
        help="候选池难度模式",
    )
    parser.add_argument("--dataset", type=Path, default=None)
    parser.add_argument(
        "--out",
        type=Path,
        default=None,
        help="显式指定结果文件（默认按 split/weights/paths 推导）",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="允许覆盖 paths_enabled 不同的既有结果文件（缺陷 12 的显式逃生口）",
    )
    parser.add_argument(
        "--paths",
        default=None,
        metavar="LIST",
        help=(
            "启用的召回路径，逗号分隔的白名单（默认全开）。"
            f"可选：{', '.join(ALL_PATHS)}；空串表示全关（零召回基线）"
        ),
    )
    args = parser.parse_args(argv)

    try:
        paths = parse_paths(args.paths)
    except ValueError as exc:
        print(f"{exc}", file=sys.stderr)
        return 2

    path = args.dataset or (DATA / f"{args.split}.jsonl")
    if not path.exists():
        print(f"数据集不存在：{path}", file=sys.stderr)
        return 2
    rows = _rows(path)

    all_specs: list[dict[str, object]] = []
    for name in ("dev.jsonl", "test.jsonl", "independent.jsonl"):
        other = DATA / name
        if other.exists():
            all_specs.extend(
                [row["gold"] for row in _rows(other) if row.get("gold")]  # type: ignore[misc]
            )

    judge: EquivalenceJudge | None = None
    settings: Settings | None = None
    if not args.no_dedup or "vector" in paths:
        settings = Settings.load()
        settings.cache_dir.mkdir(parents=True, exist_ok=True)

    if not args.no_dedup and settings is not None:
        llm = LLMClient(
            settings=settings,
            response_cache=ResponseCache(settings.cache_dir / "responses.db"),
            max_retries=0,
        )
        judge = EquivalenceJudge(llm=llm)

    embedder: DashScopeEmbedder | None = None
    if "vector" in paths and settings is not None:
        embedder = DashScopeEmbedder(
            settings=settings,
            cache=EmbeddingCache(settings.cache_dir / "cache.db"),
        )

    result = evaluate(
        rows,
        all_specs=all_specs,
        weights_name=args.weights,
        enable_dedup=not args.no_dedup,
        judge=judge,
        k=args.k,
        pool_mode=PoolMode(args.pool),
        paths=paths,
        embedder=embedder,
    )
    result["split"] = args.split

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    suffix = ("-nodedup" if args.no_dedup else "") + f"-pool{args.pool}"
    paths_tag = "" if paths == ALL_PATHS else "-paths" + "-".join(paths or ("none",))
    out = args.out or (
        OUT_DIR / f"retrieval-{args.split}-{args.weights}{suffix}{paths_tag}.json"
    )
    _assert_writable(out, result, overwrite=args.overwrite)
    run_count = _bump_run_count(out)
    result["run_count"] = run_count
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")

    returns = " ".join(
        f"{name}={'-' if value is None else value}"
        for name, value in result["path_returns"].items()
    )
    print(
        f"split={args.split} weights={args.weights} pool={args.pool} dedup={not args.no_dedup} "
        f"paths={','.join(paths) or '(none)'}"
    )
    # 总数单独看有歧义：41 可能是"33 条各返回 1.2 条"，也可能是"1 条返回 41 条"。
    # 后一种说明某个 case 的池异常大，是数据缺陷。均值能立刻区分。
    def _fmt(name: str, value: int | None) -> str:
        if value is None:
            return f"{name}=-"
        if value == 0:
            return f"{name}=0"
        mean = value / result["with_gold"] if result["with_gold"] else 0.0
        return f"{name}={value} ({result['with_gold']} cases, mean {mean:.2f})"

    per_path = " ".join(
        _fmt(name, value) for name, value in result["path_returns"].items()
    )
    print(f"  path_returns: {per_path}")
    if result["paths_unwired"]:
        print(f"  未接线的路径（记 null 而非 0）：{', '.join(result['paths_unwired'])}")
    print(
        f"  n={result['with_gold']}/{result['cases']} skipped={result['skipped_small_pool']} "
        f"SEH@{args.k}={result['seh_at_k']:.3f} SRS={result['srs']:.3f} "
        f"run#{run_count}"
    )
    print(f"  {returns}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
