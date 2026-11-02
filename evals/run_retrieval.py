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
import hashlib
import json
import subprocess
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
    RerankWeights,
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


def code_version() -> str:
    """当前代码版本：`<short-rev>` 或 `<short-rev>-dirty`。

    **为什么 `-dirty` 重要**：未提交代码产生的结果**不可复现**，
    所以必须能从结果文件本身看出来。这一轮曾把工作区未提交的
    `{1:29, 2:4}` 当成归档读，花了四轮才查清。

    **为什么限定路径**：只看 `evals` 与 `src`。若不限，改一份报告
    或新增一个临时文件都会标 `-dirty`，标记就失去信息量。
    """
    rev = subprocess.run(
        ["git", "rev-parse", "--short", "HEAD"],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
    ).stdout.strip()
    if not rev:
        # 不是 git 仓库或 git 不可用时，明确标注而不是静默给空。
        return "unknown"

    dirty = subprocess.run(
        ["git", "status", "--porcelain", "evals", "src"],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
    ).stdout.strip()

    return f"{rev}-dirty" if dirty else rev


def code_diff_hash() -> str | None:
    """未提交代码的 diff 摘要（sha256 hex）；干净时为 `None`。

    **只记 `-dirty` 不够**：两份 `-dirty` 结果无法区分
    （比如"改了 run_retrieval"与"改了 v2_baselines"）。
    有了 hash，相同即同一份工作区代码，不同即两次不同的未提交状态。

    **已知局限：只覆盖 `evals/` 与 `src/`，不覆盖 `data/` 与 `results/`。**
    若实验涉及数据集变更，`code_diff_hash` 抓不到——那需要另行记录
    数据指纹（测试命名约定 `test_data_fingerprint_*`）。
    v2 数据集冻结前，「哪个文件算数据」的语义还不稳定，
    所以这里不加 `data_hash`；冻结后应当补上。
    """
    version = code_version()
    if not version.endswith("-dirty"):
        return None

    diff = subprocess.run(
        ["git", "diff", "HEAD", "--", "evals", "src"],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
    ).stdout
    # 未跟踪的新文件不在 `git diff` 里，单独补上它们的路径与内容摘要。
    untracked = subprocess.run(
        ["git", "ls-files", "--others", "--exclude-standard", "evals", "src"],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
    ).stdout
    payload = diff + "\n---untracked---\n" + untracked
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def code_fingerprint() -> dict[str, str | None]:
    """结果文件里要记的代码身份。"""
    return {"code_version": code_version(), "code_diff_hash": code_diff_hash()}


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


def active_paths(paths: tuple[str, ...]) -> tuple[str, ...]:
    """**唯一**的「某一路是否真的会被调用」判定。

    为什么必须收敛到一处：`paths_unwired` 与"是否调用 `recall_by_*`"
    若各判一次，两者可以不一致——那会让 `path_returns["vector"] > 0`
    与 `paths_unwired` 含 `vector` 同时成立，状态自相矛盾。
    这与缺陷 12（同一件事在两处定义）是同一类问题。

    测试可通过 monkeypatch 本函数的输出来验证"未接线"机制，
    而不依赖 `_UNWIRED` 的当前取值。
    """
    return tuple(name for name in paths if name not in _UNWIRED)


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


def _dedup_text(item: MemoryItem) -> str:
    """`dedup` 的比较文本：**必须同时含 condition 与 value**。

    **为什么与 `_embedding_text` 不同**（三条规则各自有理由，不能统一）：

    | 用途 | 构造 | 理由 |
    |---|---|---|
    | `_embedding_text` | `subject + relation + value` | 向量不该掺条件 |
    | `_dedup_text` | `subject + relation + value + condition` | 去重必须区分条件分支 |
    | `items_fts` | `subject + relation + value + 原文` | 词面要保留原文 |

    **不含 condition 的后果**（实测）：33/33 条 case 的池里都存在
    "合成文本完全相同、但 condition 不同"的一对（`ruff/None` 与
    `ruff/backend`）。判官看到两条一字不差的文本几乎必然判 `equivalent`，
    把一条删掉——而那正是 BRANCH 语义下必须并存的两条。

    **为什么不用源行 `text`**：660 条干扰项里只有 44.1% 的 `value`
    出现在源行 `text` 里；其余描述的是 `candidate_value`（BRANCH 行），
    等于给干扰项贴上一句描述别的值的话，比 tag 更误导。
    """
    parts = [item.subject, item.relation, item.value]
    if item.condition:
        parts.append(item.condition)
    return " ".join(parts)


def _embedding_text(item: MemoryItem) -> str:
    """池内条目送去向量化的文本。

    **只用 `subject + relation + value`，不读 `item.text`。**

    两条理由：

    1. **泄露**：`row["text"]` 与 `query` 逐字相同（33/33）。
       若拼进来，gold 的向量输入就含一份查询副本，余弦测的是自相似。
       实测平均余弦 0.7419 → 去掉后 0.4586（缺陷 14）。

    2. **对称性**：gold 原先有 `text`、干扰项 `text=None`，
       两边构造规则不同，使"向量的贡献"无法解释。

    **为什么不干脆把 `text` 也设成 None**：`text` 同时被 FTS 使用
    （`sqlite._write_fts` 拼 `item.text`）。实测去掉后
    lexical 召回 41 → 28、gold 命中 33/33 → 20/33、**10 条 case 零召回**。
    所以 `text` 必须保留给词面，只在向量侧不读它。

    用 `document` 侧：与查询的 `query` 侧必须分开，
    实测同文本两侧余弦仅 0.842。
    """
    return f"{item.subject} {item.relation} {item.value}"


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


def count_competitors(*, pool, gold) -> int:
    """池中与 gold 同 `relation` 的候选数（**不含 gold 自己**）。

    **这是 `axis` 与 `n_competitors` 的单一实现**：`derive_axis` 只判断
    `> 0`，`evaluate_case` 既要数也要标签——两处都调这里，
    避免"结果文件里的 `n_competitors`"与"派生 axis 用的计数"是两份代码。
    """
    def _mid(m: object) -> object:
        if isinstance(m, dict):
            return m.get("memory_id")
        return getattr(m, "memory_id", None)

    def _rel(m: object) -> object:
        if isinstance(m, dict):
            return m.get("relation")
        return getattr(m, "relation", None)

    gold_id = _mid(gold)
    gold_rel = _rel(gold)

    # **无法识别 gold 时必须报错，不能静默退化。**
    # 实测：所有候选都没有 `memory_id` 时，`mid == gold_id` 恒真（None == None），
    # 每个候选都被当成 gold 跳过，`within` 恒返回 `cross`——一个 0 竞争者的假象。
    if gold_id is None:
        raise ValueError(
            "无法从 gold 取到 memory_id，不能派生轴。"
            "若用 dict，必须提供 memory_id 键；否则所有候选都会被误判为 gold。"
        )

    n = 0
    for m in pool:
        if _mid(m) == gold_id:
            continue
        if _rel(m) == gold_rel:
            n += 1
    return n


def derive_axis(*, pool, gold) -> str:
    """由池结构派生轴（design D2）。

    `n_competitors` = 池中与 gold 同 `relation` 的候选数（**不含 gold 自己**）。

    - `n_competitors > 0` -> `relation_within`
    - 否则               -> `relation_cross`

    **为什么要派生而不是读数据集的 `axis` 字段**：
    v2 的 `axis` 是人工标注，与池的实际结构脱钩。
    实测 `billing` 的 3 条 C 标注查询在池结构上都是 `relation_within`
    （gold relation 各有 3 分支 -> 每条都有 2 个同 relation 对手），
    即标注与派生不一致 **3/12**；`ledger` 则是 0/12。
    而 `billing` 的 A 与 C 两轴 `n_competitors` 取值集合都是 `{2}`，
    在去掉 condition 加权后完全同构——标注字段看不出这一点。
    """
    n = count_competitors(pool=pool, gold=gold)
    return "relation_within" if n > 0 else "relation_cross"


def derive_axis_policy(cases: dict[str, list[int]]) -> str:
    """按 subject 判定两轴的关系（design D2）。

    参数 `cases` 形如 `{"A": [2, 2, 2], "C": [0, 0]}`，值是逐条查询的
    `n_competitors`。

    返回三个值之一：

    | 情形 | 返回 | 报告处置 |
    |---|---|---|
    | 两轴都有查询，`set(A) == set(C)` | `merged` | 只报一个轴的分数 |
    | 两轴都有查询，`set(A) != set(C)` | `two_axes` | 两轴分别报 |
    | **只有一轴有查询** | `single_axis` | 报该轴；说明另一轴不存在 |
    | **两轴都没有查询** | `no_axis` | 不报轴分数，并说明不可判定 |

    **为什么 `single_axis` 与 `merged` 必须分开**：两者的报告轴数都是 1，
    数字上看不出差别。但 `merged` 是"两轴同构，合并后仍代表两轴"，
    `single_axis` 是"只有一轴存在"。用同一个值会让报告写出
    "两轴合并"而实际只有一轴——**同"数字相同所以看不出错"的形态。**

    实测这一情形**必然出现**：proposal 的路 2 允许 subject 没有 cross 轴，
    而 `billing` 三个 relation 全多分支，永远产生不了 cross 查询。

    **判据用取值集合，不用中位数 / 有序列表 / 标签集合**：

    | 判据 | 问题 |
    |---|---|
    | 中位数 | 漏掉尾部：`[1,1,1,1,9]` 与 `[1,1,1,1,1]` 中位数都是 1 |
    | 有序列表 | **混入样本量**：`[2]*9 != [2]*3`，那只是查询条数不同 |
    | 标签集合 | 太粗：`{1}` 与 `{7}` 都是 within，但难度不同 |
    | **取值集合** | ✅ 忽略样本量，保留结构差异与尾部 |

    实测：`billing` 的 `set(A) == set(C) == {2}` -> `merged`；
    `ledger` 的 `{2,3}` vs `{0}` -> `two_axes`。
    """
    a = set(cases.get("A") or [])
    c = set(cases.get("C") or [])
    if not a and not c:
        return "no_axis"
    if not a or not c:
        return "single_axis"
    return "merged" if a == c else "two_axes"


def axis_policy_from_per_case(
    per_case: list[dict[str, object]],
) -> tuple[str, dict[str, dict[str, object]]]:
    """由 `per_case` 的**派生轴**汇总 subject 级 policy 与证据。

    返回 `(policy, evidence)`，`evidence` 形如：

    ```python
    {
        "relation_within": {"n": 10, "values": [2, 3]},
        "relation_cross":  {"n": 2,  "values": [0]},
    }
    ```

    **必须按派生轴分组，不能按数据集标注分组**：`billing` 的 3 条 C 标注
    在池结构上都是 `within`。按标注分组会得 `merged`（A={2}、C={2}），
    而正确答案是 `single_axis`（没有 cross 查询）。两者报告轴数都是 1，
    **数字上看不出差别，语义相反。**

    `values` 是**去重后排序**的取值集合——样本量不进证据，
    因为判定不看样本量（见 `derive_axis_policy`）。
    """
    grouped: dict[str, list[int]] = {"relation_within": [], "relation_cross": []}
    for case in per_case:
        if not case.get("has_gold") or case.get("skipped"):
            continue
        axis = str(case.get("axis"))
        if axis not in grouped:
            continue
        grouped[axis].append(int(case["n_competitors"]))  # type: ignore[arg-type]

    evidence: dict[str, dict[str, object]] = {
        axis: {"n": len(values), "values": sorted(set(values))}
        for axis, values in grouped.items()
    }

    # **显式映射到 `derive_axis_policy` 的键名**，不能依赖"名字碰巧对上"。
    # 若直接把 `{"relation_within": [...], "relation_cross": []}` 传进去，
    # `cases.get("A")` 恒为 None -> 两轴都空 -> `no_axis`。
    # 这是个**静默错误**：policy 仍是一个合法值，只是与数据无关。
    policy = derive_axis_policy(
        {
            "A": grouped["relation_within"],
            "C": grouped["relation_cross"],
        }
    )
    return policy, evidence


def recompute_order(
    candidates,
    *,
    weights: RerankWeights,
    fusion_tags: list[str] | None,
) -> list[str]:
    """按 `evaluate_case` 的两步裁决复算名次（离线，不碰 store、不调模型）。

    **两步缺一不可**：

    1. `rerank(candidates, weights)`：按三项加权得分排
    2. 按 `fusion_tags` 的位置破并列

    **第 2 步不是可选的**：`rerank` 内部的并列判据是 `item_id`，
    而这里的 `item_id` 是 tag。tag 字典序会让 `d-<case>-0` 恒排在
    `gold-<case>` 之前（`"d" < "g"`），于是每个并列都以 gold 输给干扰项告终——
    一个固定偏向，看起来却像"排序结果"。

    `fusion_tags=None` 时退回第 1 步的结果（tag 字典序）。
    **那个返回值是错的**，保留它只是为了能演示"缺输入会静默给出另一个名次"。
    """
    ranked = rerank(candidates, weights=weights)
    if fusion_tags is None:
        return [r.item_id for r in ranked]

    position = {tag: i for i, tag in enumerate(fusion_tags)}
    ordered = sorted(
        ranked,
        key=lambda r: (-r.score, position.get(r.item_id, len(fusion_tags))),
    )
    return [r.item_id for r in ordered]


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

    # 干扰项的 `text`：优先用 spec 自带的 `memory_text`。
    #
    # C4 的 gold spec 没有这个字段，所以那条路径仍然得到 `text=None`——
    # 行为自动分化，不需要开关。而 v2 的 spec 有 `memory_text`，
    # 丢掉它会让 FTS 索引里只剩 value，共享情境词进不去（缺陷 2 复发）。
    distractors = [
        _item(
            {"text": ""},
            spec,
            tag=f"d-{row['id']}-{i}",
            text=str(spec.get("memory_text") or "") or None,
        )
        for i, spec in enumerate(selected)
    ]

    with tempfile.TemporaryDirectory() as directory:
        store = SqliteStore(Path(directory) / "eval.db")
        try:
            # gold 的 `text`：v2 用 spec 的 `memory_text`（= 产生这条记忆的原话），
            # C4 用 row 的 `text`（那是 query 的副本，见缺陷 14）。
            # 两者都保留，是因为 `_embedding_text` 已经不读 `text`，
            # 而 FTS 需要它——**FTS 的输入不该等于查询**（缺陷 1）。
            gold_text = str(gold_spec.get("memory_text") or row.get("text") or "") or None
            gold = _item(row, gold_spec, tag=f"gold-{row['id']}", text=gold_text)
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

            # tag -> store id 的反向映射。
            # 融合与重排都在 tag 域进行（tag 稳定，store id 是 uuid4），
            # 需要回 store 取条目时用这个。
            id_by_tag: dict[str, str] = {tag: sid for sid, tag in tag_by_id.items()}

            # tag -> (subject, relation)。
            #
            # **为什么必须暴露**：`rerank_order_tags` 只给出顺序，而
            # A 轴的竞争集是"同 subject 同 relation 的全部记忆"。
            # 没有这个映射，就只能从整池名次推断竞争集名次的范围，
            # 无法给出确切值——而那正是"分母是整池还是竞争集"这一争论的核心。
            #
            # 实测反例：`ledger-q4` 整池 rank=6，竞争集只有 4 条。
            # 名次超过容量，说明两个口径不同；要判定它在竞争集里排第几，
            # 必须知道排在它前面的 5 条里哪些是同 relation 的。
            #
            # **只记 subject 与 relation，不记 condition**：
            # 竞争集判定只用这两项，而 20 个 subject × 每池 12 条 × 3 字段
            # 会让结果文件多出上万个小对象。condition 用不上就不存。
            tag_meta: dict[str, tuple[str, str]] = {
                entry.id: (str(entry.subject), str(entry.relation))
                for entry in pool.items
            }

            # 第 1 组：只加观测，不改召回逻辑。
            # vector / adjacency 尚未接进本入口（见 _UNWIRED），因此它们的
            # 返回值记为 None，而不是 0——"没接上"与"跑了但空"是两件事。
            path_returns: dict[str, int | None] = {name: None for name in ALL_PATHS}
            adjacency_tags: list[str] = []
            path_raw_lengths: dict[str, int | None] = {name: None for name in ALL_PATHS}
            path_fused_lengths: dict[str, int | None] = {name: None for name in ALL_PATHS}
            ranked_lists: dict[str, list[str]] = {}

            # 用 active_paths 判定，与 paths_unwired 同源（P0-g）。
            enabled = active_paths(paths)

            def _record(name: str, ids: list[str]) -> None:
                """记录原长与截断后长度，并把截断结果放进融合输入。"""
                path_raw_lengths[name] = len(ids)
                capped = ids[:FUSION_CAP]
                path_fused_lengths[name] = len(capped)
                path_returns[name] = len(ids)
                ranked_lists[name] = capped

            if "lexical" in enabled:
                lexical = [
                    i.id for i in recall_by_lexical(store, query, limit=len(pool.items))
                ]
                _record("lexical", lexical)

            if "vector" in enabled and embedder is not None:
                query_vector = embedder.embed(query, text_type="query")
                hits = recall_by_vector(store, query_vector, limit=len(pool.items))
                _record("vector", [i.id for i in hits])

            if "adjacency" in enabled:
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

            # **融合前把 id 换成稳定 tag**，因为 `rrf` 的并列判据是 `item_id`（字典序），
            # 而 store 的 id 是 uuid4——每次运行都不同。
            #
            # **两个地方都受影响**，且都不明显：

            # 1. `rrf` 内部对同分项按 id 排序 → 融合顺序跨运行不同
            #    （实测 `ledger-q1`：fusion 前 4 名在 5 次运行里有 2 种排列）
            # 2. `rerank` 同样按 id 破并列 → 重排后名次也跟着变
            #    （实测 rank = 1,2,2,2,1；条件消融的 A 轴 `SEH@1`
            #     在 0.3000 / 0.4000 之间跳，`drop` 在 0.50 / 0.60 之间跳）
            #
            # 两处合起来让"同一份数据、同一份代码"给出不同分数。
            # 这不是数据的性质，是装置的不确定性——而它会被写成"条件贡献"
            # 或"路径贡献"的差异。
            #
            # 用 tag 替换后，同一数据集任意运行给出同一顺序。
            tag_lists = {
                source: [tag_by_id.get(i, i) for i in ids]
                for source, ids in ranked_lists.items()
            }
            fused = rrf(tag_lists, k=60) if tag_lists else []
            # 融合后一律用 **tag** 作键，不再碰 store 的 uuid4。
            fused_order = [entry.item_id for entry in fused]
            recalled_count = len(fused_order)
            gold_tag = f"gold-{row['id']}"
            rank_fusion = (
                fused_order.index(gold_tag) + 1 if gold_tag in fused_order else None
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
                # 入参三元组是 (id, text, score)。
                # text 用 `_dedup_text`（含 condition 与 value），不是 id、不是 tag：
                # - 用 id/tag 会让判官没有任何语义可判
                # - 不含 condition 会让 `ruff/None` 与 `ruff/backend` 变成同文本，
                #   而这两条必须并存（BRANCH）
                texts = [
                    (tag, _dedup_text(store.get(id_by_tag[tag])), score_by_id[tag])
                    for tag in fused_order
                ]
                kept, _ = dedup(texts, judge=judge, top_k=k)
                dedup_input_tags = [e[0] for e in texts]
                dedup_input_scores = [float(e[2]) for e in texts]
                fused_after_dedup = [e[0] for e in kept]
            else:
                fused_after_dedup = fused_order

            candidates = []
            features_by_tag: dict[str, dict[str, float]] = {}
            condition_by_tag: dict[str, float] = {}
            for tag in fused_after_dedup:
                item = store.get(id_by_tag[tag])
                cond = condition_match(
                    str(query_condition) if query_condition else None,
                    item.condition,
                )
                base = rrf_norm(score_by_id[tag], max_score=max_score)
                authority = authority_score(item.authority)
                status = status_score(item.status)
                # 记整池（融合后、去重后的全部候选）的三项特征。
                # **必须记整池**：只记 gold 的分，无法复算"gold 排第几"——
                # 名次是相对于其他候选的，缺别人的分就无从比较。
                features_by_tag[tag] = {
                    "base": base,
                    "authority": authority,
                    "status": status,
                }
                condition_by_tag[tag] = cond
                candidates.append(
                    _RerankCandidate(
                        item_id=tag,
                        features=FeatureScores(
                            base=base,
                            condition=cond,
                            authority=authority,
                            status=status,
                        ),
                    )
                )

            ranked: list[Ranked] = rerank(candidates, weights=weights)

            # 并列时用**融合顺序**决定先后。
            #
            # `rerank` 的并列判据是 `item_id`，现在是 tag 的字典序——
            # 那会让 `d-<case>-0` 恒排在 `gold-<case>` 之前（"d" < "g"），
            # 于是每个并列都以 gold 输给干扰项告终：只是把随机换成固定偏向。
            # 融合顺序由 RRF 分数决定，确定且有语义，才是正确的次级判据。
            fused_position = {tag: i for i, tag in enumerate(fused_order)}
            ranked = sorted(
                ranked,
                key=lambda r: (-r.score, fused_position.get(r.item_id, len(fused_order))),
            )
        finally:
            store.close()

    order = [item.item_id for item in ranked]

    rank_rerank = order.index(gold_tag) + 1 if gold_tag in order else None

    # 并列参与度：有多少条的名次是被"破并列判据"决定的。
    #
    # **为什么按 top1 / K 边界分开**：一个 `tie_count` 无法区分三种情况——
    #   第 1、2 名并列 -> 影响 `SEH@1`
    #   第 5、6 名并列 -> 影响 `SEH@5`
    #   第 9、10 名并列 -> 不影响任何指标
    # 三者计数都是 1，但含义完全不同。
    #
    # **实测（`data/retrieval-v2/sample`）**：
    #
    # | 配置 | tie_at_top1 | tie_at_k_boundary |
    # |---|---|---|
    # | 真实（condition 未消融） | **0** | 0 |
    # | 消融（condition 抹平） | **1**（`ledger-q1`） | 0 |
    #
    # 真实配置 0 条，所以 `0.9000` 不含判据决定的成分；
    # 消融后的 `0.3000` 里有 1/10 由判据决定。
    # **这是消融实验的产物，不是数据常态**——抹平 condition 后，
    # `gold` 与 `d-0` 的四特征（base/condition/authority/status）逐位相同。
    score_by_tag = {item.item_id: item.score for item in ranked}
    tie_at_top1 = 0
    tie_at_k_boundary = 0
    if order:
        top_score = score_by_tag[order[0]]
        tie_at_top1 = sum(
            1 for tag in order[1:] if score_by_tag[tag] == top_score
        )
        if len(order) >= k:
            kth_score = score_by_tag[order[k - 1]]
            tie_at_k_boundary = sum(
                1
                for tag in order[k:]
                if score_by_tag[tag] == kth_score
            )

    attribution = attribute_failure(
        gold_in_pool=True,
        rank_after_fusion=rank_fusion,
        rank_after_rerank=rank_rerank,
        k=k,
    )

    # 轴的定义量：池中与 gold 同 relation 的候选数（不含 gold）。
    #
    # **必须进结果文件，不能只是中间变量**：`pool_tag_meta` + `rerank_order_tags`
    # 能算"竞争集内名次"，但算不出"每条查询面对几个同 relation 对手"。
    # 缺它则报告只能给"两轴同构/不同构"的结论，不能复算。
    #
    # 复用 `count_competitors`（与 `derive_axis` 同一实现），
    # 避免"结果里的 n"与"派生 axis 用的 n"是两份代码。
    n_competitors = count_competitors(
        pool=(
            {"memory_id": entry.id, "relation": str(entry.relation)}
            for entry in pool.items
        ),
        gold={
            "memory_id": gold_tag,
            "relation": str(gold_spec["relation"]),
        },
    )

    return {
        "case_id": row["id"],
        "has_gold": True,
        "pool_size": len(pool.items),
        "n_competitors": n_competitors,
        # 逐条派生轴（二元，用于报告分类）；subject 级合并由 `derive_axis_policy` 决定。
        "axis": "relation_within" if n_competitors > 0 else "relation_cross",
        # 排序用的三项特征（**只含参与加权的三项**）。
        # `condition` 不在这里——它不参与排序，见下方 condition_score。
        #
        # **gold 未被召回时是 `None`，不是 `{}`**：
        # `{}` 是一个"存在但没有键"的对象，与"不存在"无法区分；
        # 而 `features=None` 与 `features_by_tag` 里没有 gold tag 是**同一事实的两种表达**，
        # 两者必须同时成立（`test_unretrieved_gold_is_declared_by_both_sides`）。
        "features": features_by_tag.get(gold_tag),
        # 整池每条候选的三项特征。**必须整池**：只记 gold 的分无法复算名次。
        "features_by_tag": features_by_tag,
        # 查询侧无条件 -> `None`（null）；有条件但不匹配 -> `0.0`。
        #
        # **两者不可合并成 0.0**：`null` 是"这个量不存在"，
        # `0.0` 是"量存在且为零"。合并后无法回答
        # "条件为什么没起作用"——是查询没带条件，还是带了但没匹配上。
        "condition_score": (
            condition_by_tag.get(gold_tag) if query_condition else None
        ),
        "rank_after_fusion": rank_fusion,
        "rank_after_rerank": rank_rerank,
        # 以下两项用**稳定 tag**，不是 uuid4：A5 要做跨运行逐位比较，
        # 而 uuid 每次运行都不同（实测两次建库 id 完全不同）。
        "fusion_tags": [tag_by_id.get(item_id, item_id) for item_id in fused_order],
        "adjacency_tags": adjacency_tags,
        "dedup_input_tags": dedup_input_tags,
        "dedup_input_scores": dedup_input_scores,
        "rerank_top1_tag": tag_by_id.get(order[0], order[0]) if order else None,
        # 并列参与度（见上方注释）：名次有多少是被破并列判据决定的。
        "tie_at_top1": tie_at_top1,
        "tie_at_k_boundary": tie_at_k_boundary,
        "tie_resolved_by": "fusion_order",
        # 完整 rerank 顺序（tag 形式）。
        #
        # **为什么必须有**：只有 gold 的名次时，无法回答"gold 在竞争集内排第几"。
        # 竞争集是 A 轴的全部同 relation 分支，而整池还含其他 relation 的干扰项。
        # 缺这个字段就只能推断出范围（1..rank），不能给出确切值。
        #
        # 实测证据：`ledger-q4` 整池 rank=6，而竞争集只有 4 条——
        # 名次超过了竞争集容量，所以整池名次与竞争集名次必然不同口径。
        "rerank_order_tags": [tag_by_id.get(item_id, item_id) for item_id in order],
        # 池内每个 tag 的 (subject, relation)。
        # 与 `rerank_order_tags` 配合，可精确算出"竞争集内名次"。
        #
        # 不含 condition：竞争集判定只看 subject + relation，
        # 而多存一个字段会让 20 个 subject 的结果文件多出上万个小对象。
        "pool_tag_meta": {
            tag: {"subject": s, "relation": r}
            for tag, (s, r) in tag_meta.items()
        },
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
    # 缺陷 17：请求 vector 但不给 embedder 时必须抛错，不能静默跳过。
    #
    # 实测后果：同一数据同一代码，给 embedder 是 SEH@5=1.000，
    # 不给是 0.667，而 `path_returns["vector"]` 只是从 144 变成 None、
    # `paths_unwired` 一直是空——与"只开 lexical"完全无法区分。
    # 在测量工具里，静默降级比抛错危险得多。
    # 缺陷 17 的抛错检查必须用 active_paths，不能看原始 paths：
    # 否则"未接线"的 vector 会先被抛错拦住，机制本身测不到。
    if "vector" in active_paths(paths) and embedder is None:
        raise ValueError(
            "paths 含 'vector' 但没有提供 embedder：向量路径会被静默跳过，"
            "而结果看起来完全正常（path_returns['vector'] 记 None，"
            "paths_unwired 为空）。请注入 embedder，或把 'vector' 从 paths 里去掉。"
        )

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

    # subject 级轴判定：**按派生轴分组**，不按数据集标注（见函数 docstring）。
    axis_policy, axis_policy_evidence = axis_policy_from_per_case(per_case)

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
        # subject 级轴判定。报告必须逐 subject 报这个值；
        # `merged` 只报一个轴的分数，`single_axis` 要说明另一轴不存在。
        "axis_policy": axis_policy,
        "axis_policy_evidence": axis_policy_evidence,
        "paths_enabled": list(paths),
        # 只有"启用了但代码里还没有调用点"才算未接线。
        # 未启用的路径是"没开"，不是"没接上"——两者诊断方向不同。
        "paths_unwired": [name for name in paths if name not in active_paths(paths)],
        "path_returns": path_totals,
        "embedding_network_calls": (
            embedder.network_calls - calls_before if embedder is not None else 0
        ),
        **code_fingerprint(),
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


def assert_result_is_complete(result: dict[str, object]) -> None:
    """**写结果前**检查每条 case 的特征字段齐全；不齐则抛错、不写出。

    spec 承诺"缺字段时拒绝写结果"。没有这道检查时，某个诊断脚本或新分支
    构造 `per_case` 漏了 `features`，结果文件照样写出、所有形状检查照样绿——
    **缺的字段没人要，因为没人读它**。

    三种缺失各自报错，不合并成一条：

    | 缺失 | 为什么单独报 |
    |---|---|
    | 没有 `features` 键 | 构造时整个漏了 |
    | `features` 少一个子键 | 抄了一个不完整的三元组 |
    | 没有 `condition_score` 键 | 与"值为 null"不同——前者是漏，后者是事实 |

    `features` 为 `None` 是**合法**的（gold 未召回），不在此处报错；
    它与 `features_by_tag` 的一致性由测试约束。
    """
    cases = result.get("per_case")
    if not isinstance(cases, list):
        return

    required = ("base", "authority", "status")
    for case in cases:
        if not isinstance(case, dict):
            continue
        if not case.get("has_gold") or case.get("skipped"):
            continue
        case_id = case.get("case_id")

        if "features" not in case:
            raise ValueError(
                f"{case_id}: 缺 features 键。结果不得在缺字段的情况下写出——"
                "缺的字段没有读者，也就永远不会被发现。"
            )

        features = case["features"]
        if features is not None:
            if not isinstance(features, dict):
                raise ValueError(f"{case_id}: features 不是 dict")
            missing = [k for k in required if k not in features]
            if missing:
                raise ValueError(
                    f"{case_id}: features 缺 {missing}。"
                    "三项排序特征必须齐全，否则复算名次会静默少一项。"
                )

        if "condition_score" not in case:
            raise ValueError(
                f"{case_id}: 缺 condition_score 键。"
                "查询侧无条件时该字段应为 null，但字段本身必须存在——"
                "'没有这个键'与'值为 null'不是同一件事。"
            )


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
    """记录同一配置被跑了几次，使"test 只跑一次"可验证。

    **只统计 `results/` 下的正式输出**：诊断脚本常把结果写到临时目录，
    那些不该混进"这个配置跑了几次"的账本里——否则探针会污染计数。
    实测污染：三个探针往账本里写进了 `det-threeway.json` 之类的键。
    """
    counter = OUT_DIR / "retrieval-run-count.json"
    counts: dict[str, int] = {}
    if counter.exists():
        counts = json.loads(counter.read_text(encoding="utf-8"))
    key = out.name
    counts[key] = counts.get(key, 0) + 1
    if out.parent.resolve() != OUT_DIR.resolve():
        # 临时输出：计数但不落账，避免污染正式账本
        return counts[key]
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    counter.write_text(json.dumps(counts, ensure_ascii=False, indent=2), encoding="utf-8")
    return counts[key]


def _previous_provenance(out: Path) -> dict[str, object] | None:
    """读取被覆盖文件原有的 provenance，用于区分两种 `run_count=2`。

    **`run_count` 一个字段承载两个含义**：

    | 情形 | 是否作废旧结论 |
    |---|---|
    | 同一代码状态跑两次（比如验证确定性） | 否 |
    | 不同代码状态写进同一文件 | **是** |

    两者都表现为 `run_count=2`。加上 `supersedes` 才能分开：

    - 有 `supersedes` → 新版覆盖了旧版，旧结论作废
    - 无 `supersedes` → 同一状态跑了两次，结论不变

    判据是 `code_version` 与 `code_diff_hash` 是否相同。
    """
    if not out.exists():
        return None
    try:
        old = json.loads(out.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    return {
        "code_version": old.get("code_version"),
        "code_diff_hash": old.get("code_diff_hash"),
        "run_count": old.get("run_count"),
        # 必须带上已有的 supersedes，否则覆盖时会把历史抹掉：
        # 链条 A -> B -> B 里，第二次 B 覆盖 B 会丢掉"A 被作废"这条记录。
        "supersedes": old.get("supersedes"),
    }


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

    # v2 是一个**目录**（memories.jsonl + queries.jsonl），不是单文件。
    # 适配层只做字段映射；池构造仍走 build_pool，保证与 C4 可比。
    if path.is_dir():
        from evals.datasets.v2_adapter import load_rows

        rows = load_rows(path)
        print(f"v2 数据集：{path}（{len(rows)} 条查询）")
    else:
        rows = _rows(path)

    all_specs: list[dict[str, object]] = []
    if path.is_dir():
        # v2：干扰项只能来自**本数据集自己的**记忆库。
        # 若混入 conflict-set 的 gold，就是缺陷 9（池 100% 来自 dev）的复发。
        all_specs = [row["gold"] for row in rows if row.get("gold")]
    else:
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
    assert_result_is_complete(result)
    previous = _previous_provenance(out)
    run_count = _bump_run_count(out)
    result["run_count"] = run_count
    # 覆盖必须被记录，**且不能因为"这次状态没变"就丢掉历史**。
    #
    # 早先的实现只在"本次 vs 上次状态不同"时写 `supersedes`。
    # 于是链条 A -> B -> B 里，第二次 B 覆盖 B 会把 A 的记录抹掉，
    # 而 A 才是真正被作废的那次。
    #
    # 正确做法：**继承**已有的 `supersedes`；只有当前状态与该记录不同
    # 才把它补上。同一状态反复重跑不应产生新的作废声明。
    if previous is not None:
        inherited = previous.get("supersedes")
        same_as_previous = (
            previous.get("code_version") == result.get("code_version")
            and previous.get("code_diff_hash") == result.get("code_diff_hash")
        )
        if isinstance(inherited, dict):
            result["supersedes"] = inherited
        elif not same_as_previous:
            result["supersedes"] = {
                "code_version": previous.get("code_version"),
                "code_diff_hash": previous.get("code_diff_hash"),
                "run_count": previous.get("run_count"),
            }
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
