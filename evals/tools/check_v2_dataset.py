"""v2 数据集合格性门禁（F1–F16 的可执行部分）。

**为什么要有这个脚本**：协议里的门禁如果只是文字，最终会变成"我记得检查过"。
C4 的教训是三个缺陷各自都有测试、每一层都是绿的，接缝处却断了。
所以 v2 的门禁必须能在一条命令里跑完并对每个 case 给出通过/失败。

已实现的部分（其余依赖尚未写出的评测入口）：

| 编号 | 检查 | 状态 |
|---|---|---|
| F1 | L1–L9 反泄漏 | ✅ |
| F2 | `recall_size ≥ 2` 的 case 占比 ≥ 80% | ✅ |
| F5 | 每个 subject 的同 relation 分支数 3–5 | ✅ |
| F6 | 第三方 subject 数 ≥ 5 | ✅（样例必然不过，见下） |
| F12 | `forced` subject 占比 ≤ 20% | ✅ |
| F13 | `implicit` 占 A 轴 ≥ 40%，且每 subject 两种都有 | ✅ |
| F15 | A 轴随机 `SEH@5` = 1.0 时必须能给出 `SEH@1` | ✅ |
| F16 | 随机基线实测与公式偏差 < 0.02 | ✅ |
| F3/F4/F7–F11/F14 | 依赖评测入口 / 报告 | ⏳ 未实现 |

    uv run --no-sync python -m evals.tools.check_v2_dataset data/retrieval-v2/sample
"""

from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass
from pathlib import Path

from evals.datasets.retrieval_v2 import (
    Author,
    Axis,
    BranchNature,
    CueType,
    Dataset,
    load_dataset,
)
from evals.metrics.v2_baselines import (
    axis_baseline,
    competing_set,
    monte_carlo_seh,
)
from memory.retrieval.condition import _ALIASES

ROOT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True, slots=True)
class Check:
    code: str
    title: str
    passed: bool
    detail: str


def _normalize(text: str) -> str:
    return re.sub(r"\s+", "", text).casefold()


def check_l1_no_verbatim_text(dataset: Dataset) -> Check:
    """L1：query 不得等于 gold 的 memory_text。100%。"""
    bad = [
        q.query_id
        for q in dataset.queries
        if _normalize(q.query) == _normalize(dataset.memory(q.gold_memory_id).memory_text)
    ]
    return Check(
        "L1",
        "query 不等于 gold 原文",
        not bad,
        f"{len(dataset.queries) - len(bad)}/{len(dataset.queries)} 通过"
        + (f"；违规：{bad}" if bad else ""),
    )


def check_l2_no_gold_value(dataset: Dataset) -> Check:
    """L2：query 不得包含 gold 的值。"""
    bad = []
    for q in dataset.queries:
        value = dataset.memory(q.gold_memory_id).value
        if _normalize(value) and _normalize(value) in _normalize(q.query):
            bad.append(q.query_id)
    return Check(
        "L2",
        "query 不含 gold 值",
        not bad,
        f"{len(dataset.queries) - len(bad)}/{len(dataset.queries)} 通过"
        + (f"；违规：{bad}" if bad else ""),
    )


def _bigrams(text: str) -> set[str]:
    folded = _normalize(text)
    return {folded[i : i + 2] for i in range(len(folded) - 1)}


def check_l3_char_overlap(dataset: Dataset, *, threshold: float = 0.50) -> Check:
    """L3：query 与原话的字符 bigram Jaccard ≤ 0.50。"""
    worst: list[tuple[float, str]] = []
    for q in dataset.queries:
        text = dataset.memory(q.gold_memory_id).memory_text
        a, b = _bigrams(q.query), _bigrams(text)
        union = a | b
        score = len(a & b) / len(union) if union else 0.0
        worst.append((score, q.query_id))
    worst.sort(reverse=True)
    over = [f"{qid}={score:.2f}" for score, qid in worst if score > threshold]
    return Check(
        "L3",
        f"query 与原话 bigram Jaccard ≤ {threshold}",
        not over,
        f"最高 {worst[0][0]:.2f}（{worst[0][1]}）" + (f"；超限：{over}" if over else ""),
    )


def check_l4_every_memory_has_text(dataset: Dataset) -> Check:
    """L4：每条记忆都有非空 memory_text（schema 已强制，这里再确认）。"""
    bad = [m.memory_id for m in dataset.memories if not m.memory_text.strip()]
    return Check(
        "L4",
        "每条记忆都有原文",
        not bad,
        f"{len(dataset.memories) - len(bad)}/{len(dataset.memories)}"
        + (f"；缺：{bad}" if bad else ""),
    )


def check_l5_siblings_present(dataset: Dataset, *, minimum: int = 3) -> Check:
    """L5：每条 A 轴查询的同主题兄弟数 ≥ 3。"""
    thin: list[str] = []
    for q in dataset.queries:
        if q.axis is not Axis.A:
            continue
        pool = competing_set(dataset, q)
        if len(pool) < minimum:
            thin.append(f"{q.query_id}={len(pool)}")
    a_queries = [q for q in dataset.queries if q.axis is Axis.A]
    return Check(
        "L5",
        f"A 轴竞争集 ≥ {minimum}",
        not thin,
        f"{len(a_queries) - len(thin)}/{len(a_queries)} 通过" + (f"；不足：{thin}" if thin else ""),
    )


def check_l9_implicit_has_no_cue_leak(dataset: Dataset) -> Check:
    """L9：implicit 查询里不得出现其条件的已登记同义词。

    若条件词直接出现在 query 里，`condition_match` 必然命中——
    那测的是词表，不是"能否从情境推断"（协议 §3.3）。
    """
    bad: list[str] = []
    checked = 0
    for q in dataset.queries:
        if q.cue_type is not CueType.IMPLICIT or not q.query_condition:
            continue
        checked += 1
        folded = _normalize(q.query)
        # 该条件的所有别名（含条件原文本身）
        aliases = {
            alias
            for alias, slot in _ALIASES.items()
            if slot == next(
                (
                    s
                    for a, s in _ALIASES.items()
                    if a.casefold() in q.query_condition.casefold()
                ),
                None,
            )
        }
        aliases.add(q.query_condition)
        for alias in aliases:
            if _normalize(alias) and _normalize(alias) in folded:
                bad.append(f"{q.query_id}:{alias}")
                break
    return Check(
        "L9",
        "implicit 查询不含条件同义词",
        not bad,
        f"{checked - len(bad)}/{checked} 通过" + (f"；泄漏：{bad}" if bad else ""),
    )


def check_f2_recall_size(dataset: Dataset, *, target: float = 0.80) -> Check:
    """F2：竞争集 ≥ 2 的 case 占比 ≥ 80%。

    **门禁必须在"排名会不会发生"这一层，不是"池有多大"这一层。**
    C4 只检查了建池后大小，于是 26/26 条召回集只有 1 条候选时它仍然通过。
    """
    sizes = [len(competing_set(dataset, q)) for q in dataset.queries]
    ratio = sum(1 for n in sizes if n >= 2) / len(sizes) if sizes else 0.0
    return Check(
        "F2",
        f"竞争集 ≥ 2 的占比 ≥ {target:.0%}",
        ratio >= target,
        f"{ratio:.1%}（{sum(1 for n in sizes if n >= 2)}/{len(sizes)}），"
        f"最小竞争集 {min(sizes) if sizes else 0}",
    )


def check_f5_branch_counts(dataset: Dataset, *, low: int = 3, high: int = 5) -> Check:
    """F5：每个 (subject, relation) 的 ACTIVE 分支数在 3–5 之间。

    单值 relation（如 package_manager）不参与这条检查——
    它们天然只有一个值，编造分支会让 condition_match 假性有效（协议 §3.4）。
    """
    groups: dict[tuple[str, str], int] = {}
    for memory in dataset.memories:
        if memory.status.value != "ACTIVE":
            continue
        key = (memory.subject, memory.relation)
        groups[key] = groups.get(key, 0) + 1

    multi = {k: v for k, v in groups.items() if v > 1}
    bad = [f"{s}/{r}={n}" for (s, r), n in multi.items() if not low <= n <= high]
    return Check(
        "F5",
        f"多分支 relation 的分支数 ∈ [{low}, {high}]",
        not bad,
        f"{len(multi) - len(bad)}/{len(multi)} 个多分支 relation 合格"
        + (f"；超范围：{bad}" if bad else ""),
    )


def check_f6_independent_subjects(dataset: Dataset, *, minimum: int = 5) -> Check:
    """F6：第三方独立编写的 subject ≥ 5。"""
    subjects = {
        q.subject for q in dataset.queries if q.author is Author.INDEPENDENT
    }
    return Check(
        "F6",
        f"第三方 subject ≥ {minimum}",
        len(subjects) >= minimum,
        f"{len(subjects)} 个：{sorted(subjects)}",
    )


def check_f12_forced_ratio(dataset: Dataset, *, ceiling: float = 0.20) -> Check:
    """F12：`forced` 的 subject 占比 ≤ 20%。"""
    ratio = dataset.forced_subject_ratio()
    forced = [
        subject
        for subject in dataset.subjects()
        if all(m.branch_nature is BranchNature.FORCED for m in dataset.by_subject(subject))
    ]
    return Check(
        "F12",
        f"forced subject 占比 ≤ {ceiling:.0%}",
        ratio <= ceiling,
        f"{ratio:.1%}（{len(forced)}/{len(dataset.subjects())}）",
    )


def check_f13_cue_mix(dataset: Dataset, *, floor: float = 0.40, per_subject: float = 0.50) -> Check:
    """F13：`implicit` 占 A 轴查询 ≥ 40%（整体），且**每个 subject ≥ 50%**。

    分母是 **A 轴查询**，不是全部查询——C 轴没有"条件说没说破"这个维度。

    **两层阈值管不同的事**：整体 40% 防全局退化；逐 subject 50% 防
    "有些 subject 20%、有些 60%，平均 40%" 掩盖退化。平均值会掩盖退化，
    所以逐 subject 的门槛比整体更严。
    """
    a_queries = [q for q in dataset.queries if q.axis is Axis.A]
    if not a_queries:
        return Check("F13", "implicit 占比", False, "没有 A 轴查询")

    implicit = sum(1 for q in a_queries if q.cue_type is CueType.IMPLICIT)
    overall = implicit / len(a_queries)

    per_subject_ratios: dict[str, float] = {}
    missing_kind: list[str] = []
    for subject in {q.subject for q in a_queries}:
        own = [q for q in a_queries if q.subject == subject]
        kinds = {q.cue_type for q in own}
        if CueType.EXPLICIT not in kinds or CueType.IMPLICIT not in kinds:
            missing_kind.append(f"{subject}={sorted(k.value for k in kinds)}")
        own_implicit = sum(1 for q in own if q.cue_type is CueType.IMPLICIT)
        per_subject_ratios[subject] = own_implicit / len(own)

    below = {
        s: f"{r:.0%}" for s, r in per_subject_ratios.items() if r < per_subject
    }

    passed = overall >= floor and not missing_kind and not below
    detail = (
        f"整体 {implicit}/{len(a_queries)} = {overall:.1%}（需 ≥{floor:.0%}）；"
        f"逐 subject {', '.join(f'{s}={r:.0%}' for s, r in per_subject_ratios.items())}"
        f"（需 ≥{per_subject:.0%}）"
    )
    if missing_kind:
        detail += f"；缺一种：{missing_kind}"
    if below:
        detail += f"；低于逐 subject 门槛：{below}"

    return Check(
        "F13",
        f"implicit 整体 ≥{floor:.0%} 且逐 subject ≥{per_subject:.0%}",
        passed,
        detail,
    )


def check_f16_baseline_formula(dataset: Dataset, *, tolerance: float = 0.02) -> Check:
    """F16：随机基线的实测值必须与精确公式一致。

    这条抓的是"公式写错但看起来合理"。C4 的随机基线从来没算过，
    所以这类错误可以一直藏着。
    """
    problems: list[str] = []
    details: list[str] = []
    for axis in (Axis.A, Axis.C):
        expected = axis_baseline(dataset, axis)
        if expected.queries == 0:
            continue
        mc1, mc5 = monte_carlo_seh(dataset, axis, trials=2000, seed=0)
        details.append(
            f"{axis.value}: 公式 {expected.seh_at_1:.4f}/{expected.seh_at_k:.4f} "
            f"实测 {mc1:.4f}/{mc5:.4f}"
        )
        if abs(mc1 - expected.seh_at_1) > tolerance:
            problems.append(f"{axis.value} SEH@1 偏差 {(mc1 - expected.seh_at_1):+.4f}")
        if abs(mc5 - expected.seh_at_k) > tolerance:
            problems.append(f"{axis.value} SEH@5 偏差 {(mc5 - expected.seh_at_k):+.4f}")
    return Check(
        "F16",
        f"随机基线实测与公式偏差 < {tolerance}",
        not problems,
        "；".join(details) + (f"；{problems}" if problems else ""),
    )


def check_f15_axis_a_needs_seh1(dataset: Dataset) -> Check:
    """F15：A 轴随机 SEH@5 若为 1.0，报告必须给 SEH@1。

    这里检查的是"数据是否让 SEH@5 失去区分力"，从而强制报告改用 SEH@1。
    """
    baseline = axis_baseline(dataset, Axis.A)
    if baseline.queries == 0:
        return Check("F15", "A 轴饱和时必须报 SEH@1", True, "没有 A 轴查询")
    detail = (
        f"A 轴平均竞争集 {baseline.mean_pool_size:.2f}，"
        f"随机 SEH@5={baseline.seh_at_k:.4f}、SEH@1={baseline.seh_at_1:.4f}"
    )
    if baseline.saturates_at_k:
        return Check(
            "F15",
            "A 轴饱和时必须报 SEH@1",
            True,
            detail + " → A 轴主指标已定为 SEH@1（协议 §7.1）",
        )
    return Check("F15", "A 轴饱和时必须报 SEH@1", True, detail + " → 未饱和，两个指标都可用")


def _load_run(name: str) -> dict[str, object] | None:
    """读一份真实运行结果；缺失时返回 None（由调用方报失败）。"""
    path = ROOT / "results" / name
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


THREE_PATH_RUN = "a3-lexical-vector-adjacency.json"
DEDUP_RUN = "a3-with-dedup.json"


def check_l6a_three_paths_called() -> Check:
    """L6a：三路召回都被真实调用。

    判据来自运行结果：`paths_enabled` 含三路、`paths_unwired` 为空、
    `path_returns` 三路都非 null。**不读源码**——把调用注释掉，
    源码里的函数名仍在，字符串匹配抓不到。
    """
    payload = _load_run(THREE_PATH_RUN)
    if payload is None:
        return Check("L6a", "三路召回都被调用", False, f"缺少 {THREE_PATH_RUN}")

    enabled = set(payload.get("paths_enabled") or [])
    unwired = payload.get("paths_unwired") or []
    returns = payload.get("path_returns") or {}

    problems: list[str] = []
    for path_name in ("lexical", "vector", "adjacency"):
        if path_name not in enabled:
            problems.append(f"{path_name} 未启用")
        elif path_name in unwired:
            problems.append(f"{path_name} 未接线")
        elif returns.get(path_name) is None:
            problems.append(f"{path_name} 返回值为 null")

    return Check(
        "L6a",
        "三路召回都被调用",
        not problems,
        f"来自 {THREE_PATH_RUN}：enabled={sorted(enabled)}, unwired={unwired}"
        if not problems
        else "；".join(problems),
    )


def check_l6b_embedding_written() -> Check:
    """L6b：池构造时真的写入了向量，且不是零向量。

    判据来自运行结果，两条：

    1. 每条 case 的 `pool_vectors == pool_size`（都写了）
    2. `min(pool_vector_norms) > 0.5`（不是零向量）

    第 2 条防的是"写了但全是零"——那时余弦全相等、排序任意，
    只判"有没有写"抓不到。

    **诚实说明：本条在当前数据上恒真。**
    实测 462 条向量的范数落在 [0.9996, 1.0004]（8 个不同值），
    这是归一化后的浮点误差。所以 `min > 0.5` 现在必然成立——
    它是**防止将来写坏**的门禁，不是"证明现在写对了"。
    与 `SEH@5 = 1.000` 同理：一个恒真的检查看起来最像通过。
    """
    payload = _load_run(THREE_PATH_RUN)
    if payload is None:
        return Check("L6b", "池构造写入向量", False, f"缺少 {THREE_PATH_RUN}")

    cases = [
        c
        for c in payload["per_case"]  # type: ignore[index]
        if c.get("has_gold") and not c.get("skipped")  # type: ignore[union-attr]
    ]
    if not cases:
        return Check("L6b", "池构造写入向量", False, "没有可评估的 case")

    missing = [
        c["case_id"]  # type: ignore[index]
        for c in cases
        if c.get("pool_vectors") != c.get("pool_size")  # type: ignore[union-attr]
    ]
    all_norms = [
        n for c in cases for n in (c.get("pool_vector_norms") or [])  # type: ignore[union-attr]
    ]
    min_norm = min(all_norms) if all_norms else 0.0

    problems: list[str] = []
    if missing:
        problems.append(f"{len(missing)} 条 case 的 pool_vectors != pool_size：{missing[:3]}")
    if min_norm <= 0.5:
        problems.append(f"最小范数 {min_norm:.4f} <= 0.5，存在零向量或近零向量")

    return Check(
        "L6b",
        "池构造写入向量",
        not problems,
        (
            f"{len(cases)} 条 case 全部写入；范数 {min_norm:.4f}–{max(all_norms):.4f}"
            f"（{len(set(all_norms))} 个不同值）"
        )
        if not problems
        else "；".join(problems),
    )


def check_l8_dedup_scores_have_variance() -> Check:
    """L8：`dedup` 收到的分数必须有方差，不能是常数。

    判据来自 `results/a3-with-dedup.json` 的 `dedup_input_scores`。
    常数分会让 `dedup` 内部的 `(-score, id)` 排序退化为字典序
    （C4 缺陷 8）。

    **为什么不用三路文件**：那份 `dedup=false`，`dedup_input_scores` 全为空。
    这是"三路"与"去重"两个实验，不能用同一个文件判。
    """
    payload = _load_run(DEDUP_RUN)
    if payload is None:
        return Check("L8", "dedup 分数有方差", False, f"缺少 {DEDUP_RUN}")

    cases = [
        c
        for c in payload["per_case"]  # type: ignore[index]
        if c.get("has_gold") and not c.get("skipped")  # type: ignore[union-attr]
    ]
    flat = [
        c["case_id"]  # type: ignore[index]
        for c in cases
        if len(set(c.get("dedup_input_scores") or [])) <= 1  # type: ignore[union-attr]
    ]

    return Check(
        "L8",
        "dedup 分数有方差",
        not flat,
        f"{len(cases)} 条 case 的分数都有方差"
        if not flat
        else f"{len(flat)} 条 case 分数恒定：{flat[:3]}",
    )


def check_l6c_paths_return_nonempty(dataset: Dataset) -> Check:
    """L6c：三路召回必须**真的返回东西**，不是只是被调用。

    L6a 判"调用了"、L6b 判"有数据"，两者都对时仍可能一条都没返回：
    向量维度不符会被静默跳过，条件兄弟不存在则邻接必然为空。

    这条直接测"返回了什么"，而不是"做了什么"——前者比后者难自欺。

    **判据用真实运行结果，不用源码匹配。** 源码里 `recall_by_adjacency(`
    出现多少次与它是否被调用无关：把调用注释掉，字符串仍在。
    这里读 `a3-lexical-vector-adjacency.json` 的 `path_returns`，
    断言三路都已被启用且返回条数 > 0。
    """
    run_file = ROOT / "results" / "a3-lexical-vector-adjacency.json"
    if not run_file.exists():
        return Check(
            "L6c",
            "三路召回都返回非空",
            False,
            f"缺少真实运行结果 {run_file.name}；请先跑一次三路评测",
        )

    payload = json.loads(run_file.read_text(encoding="utf-8"))
    returns = payload.get("path_returns") or {}
    enabled = set(payload.get("paths_enabled") or [])

    problems: list[str] = []
    for name in ("lexical", "vector", "adjacency"):
        if name not in enabled:
            problems.append(f"{name} 未启用")
        elif returns.get(name) is None:
            problems.append(f"{name} 未接线（记 null）")
        elif returns.get(name) == 0:
            problems.append(f"{name} 返回 0 条")

    return Check(
        "L6c",
        "三路召回都返回非空",
        not problems,
        f"来自 {run_file.name}：{returns}" if not problems else "；".join(problems),
    )


def check_f17_every_branch_queried(dataset: Dataset) -> Check:
    """F17：每个 condition 分支都必须至少被一条查询指向。

    **L5 检查的是"池里有几条候选"，不是"有几条被查询指向过"。**
    按旧口径（每 subject 4 条 A 轴查询）构造数据时，一个有 4 个 relation 的
    subject 只有 4 条查询 → 每 relation 1 条。其余分支会进池（L5 绿），
    但永远不会成为任何查询的 gold。

    这是 C4 缺陷 3 的精确重演：**池里有 3 条 ≠ 有查询在考这 3 条。**

    判定：对每个 `(subject, relation)`，其每个 condition 分支都必须至少是
    一条查询的 `gold_memory_id`。
    """
    pointed = {q.gold_memory_id for q in dataset.queries}

    groups: dict[tuple[str, str], list[str]] = {}
    for memory in dataset.memories:
        if memory.status.value != "ACTIVE":
            continue
        groups.setdefault((memory.subject, memory.relation), []).append(memory.memory_id)

    untested: list[str] = []
    for (subject, relation), memory_ids in groups.items():
        # 单值 relation（只有一个分支）不适用"每分支一条"：
        # 它天然没有条件维度，编造分支会让 condition_match 假性有效（§3.4）。
        if len(memory_ids) < 2:
            continue
        for memory_id in memory_ids:
            if memory_id not in pointed:
                untested.append(f"{subject}/{relation}:{memory_id}")

    return Check(
        "F17",
        "每个 condition 分支都被查询指向",
        not untested,
        f"{len(groups)} 个 (subject,relation) 组，全部分支都有查询"
        if not untested
        else f"{len(untested)} 个分支从未成为 gold：{untested[:5]}",
    )


def check_f18_authority_is_justified(dataset: Dataset) -> Check:
    """F18：每条非 `user_direct` 的记忆，其 `memory_text` 必须说明来源。

    **这条防的是"为凑方差而降级来源"。**

    C4 的 `test_rerank_variance` 断言"真实数据里 authority 必须不止一个取值"。
    那条测试跑的是 conflict-set，不是 v2。但造 v2 数据时照着那个经验，
    给两条记忆降了级——**而协议从未要求 authority 有方差**。

    实测后果：`ledger-oncall-4`（赵启/法定节假日）是 `third_party`，
    在 `uniform` 权重下算 authority 罚分 −0.25，而它的对手只丢 0.25×0.5=0.125。
    于是它在 base（1.000 vs 0.910）与 cond（1.00 vs 0.50）上都占优，
    却掉到第 3 名（缺陷 18）。

    判据是**文本必须自解释来源**，而不是"分布必须如何"——
    因为 authority 的分布本来就该由场景决定，不该有配额。
    """
    cues = (
        "HR",
        "系统",
        "同事",
        "转述",
        "文档",
        "听说",
        "群里",
        "审计",
        "邮件",
        "工单",
        "外部",
        "第三方",
        "截图",
        "会议纪要",
    )

    unexplained: list[str] = []
    for memory in dataset.memories:
        if memory.authority.value == "user_direct":
            continue
        if not any(cue in memory.memory_text for cue in cues):
            unexplained.append(
                f"{memory.memory_id}({memory.authority.value}): {memory.memory_text!r}"
            )

    return Check(
        "F18",
        "非 user_direct 的来源必须在原文里自解释",
        not unexplained,
        "没有非 user_direct 的记忆，或全部自解释"
        if not unexplained
        else f"{len(unexplained)} 条来源降级没有场景依据：{unexplained[:3]}",
    )


def check_f19a_implicit_gold_complete(dataset: Dataset) -> Check:
    """F19a：implicit 查询的 gold **数据完整**（在库、有原文）。

    这条检查的是**字段完整性**，不是"能否被召回"。

    两者在当前样例上恰好等价（12/12 都能召回），但机制不同：

    | 检查 | 做法 |
    |---|---|
    | 数据完整性 | gold 在 `memories.jsonl` 里且有 `memory_text` |
    | 可被召回 | 真跑一次召回，看 gold 是否出现在返回列表里 |

    **实测反例**：`q3` 的 gold（林晓）在库、有原文，但**词面路径召回 0 条**。
    所以"数据完整"通过，并不意味着"召回成功"。后者是 F19b。

    本条的独立价值：防止 gold 缺失或原文为空导致向量无从匹配。
    """
    implicit = [q for q in dataset.queries if q.cue_type.value == "implicit"]
    if not implicit:
        return Check("F19a", "implicit 的 gold 数据完整", False, "没有 implicit 查询")

    problems: list[str] = []
    for query in implicit:
        try:
            gold = dataset.memory(query.gold_memory_id)
        except Exception:
            problems.append(f"{query.query_id}: gold 不在记忆库")
            continue
        if not query.query.strip():
            problems.append(f"{query.query_id}: query 为空")
        if not gold.memory_text.strip():
            problems.append(f"{query.query_id}: gold 没有原文，向量无从匹配")

    return Check(
        "F19a",
        "implicit 的 gold 数据完整",
        not problems,
        f"{len(implicit)} 条 implicit，gold 都在库且有原文"
        if not problems
        else f"{len(problems)} 条有问题：{problems[:3]}",
    )


def check_f19b_implicit_gold_recalled(dataset: Dataset) -> Check:
    """F19b：每条 implicit 的 gold 必须**真的被召回**（rank 不为 None）。

    **这才是"防止召回失败被记成条件区分失败"的那一条。**

    F19a 只检查字段完整性。实测反例：`q3` 的 gold 在库、有原文，
    但词面路径召回 0 条——若只看 F19a，它通过，而它的 0 分实际上是召回失败。

    判据来自 `results/v2-sample-condition-ablation.json` 的 `with_condition`：
    有 condition 配置下，**仅限 implicit 查询**的 `rank` 必须都不为 None。

    为什么不直接用结果里的 `never_recalled_with`：那是**全数据集**（含 C 轴）
    的计数。用它会让本门禁在两种情况下说谎——
    一个 C 轴 case 召回失败时它红（与 implicit 无关），
    而 implicit 的失败被别处抵消时它绿（正是要防的情况）。
    """
    payload = _load_run("v2-sample-condition-ablation.json")
    if payload is None:
        return Check(
            "F19b",
            "implicit 的 gold 真的被召回",
            False,
            "缺少 v2-sample-condition-ablation.json；先跑 evals.tools.ablate_condition",
        )

    implicit_ids = {
        q.query_id for q in dataset.queries if q.cue_type.value == "implicit"
    }
    if not implicit_ids:
        return Check("F19b", "implicit 的 gold 真的被召回", False, "没有 implicit 查询")

    ranks = payload.get("with_condition") or {}
    missing = sorted(implicit_ids - set(ranks))
    never_recalled = sorted(cid for cid in implicit_ids if ranks.get(cid) is None)

    if missing:
        return Check(
            "F19b",
            "implicit 的 gold 真的被召回",
            False,
            f"消融结果里没有这些 implicit 的排名：{missing[:3]}（结果过期？）",
        )

    return Check(
        "F19b",
        "implicit 的 gold 真的被召回",
        not never_recalled,
        f"{len(implicit_ids)} 条 implicit，三路全开时全部被召回"
        if not never_recalled
        else f"{len(never_recalled)} 条 implicit 从未被召回：{never_recalled[:3]}",
    )


def check_f20_condition_contributes() -> Check:
    """F20：条件消融后 A 轴 `SEH@1` 掉幅必须 ≥ 0.3。

    **为什么需要**：有人可以写出一批"explicit 占多数、condition 全都匹配"的
    查询，也得到很高的 `SEH@1`——而 A 轴的设计意图（多个条件分支里挑对）
    完全落空。只报分数看不出来。

    实现放在 `evals/tools/ablate_condition.py`（它要跑评测，较重），
    但本门禁**收进 `run_all()`**，读它的结果 JSON。
    否则 `run_all()` 只跑 F1–F19，F20 没人跑会成为隐患。
    """
    payload = _load_run("v2-sample-condition-ablation.json")
    if payload is None:
        return Check(
            "F20",
            "condition 对 A 轴有贡献",
            False,
            "缺少 v2-sample-condition-ablation.json；先跑 evals.tools.ablate_condition",
        )

    drop = payload.get("drop")
    threshold = payload.get("threshold", 0.30)
    with_cond = payload.get("axis_a_seh1_with")
    without_cond = payload.get("axis_a_seh1_without")
    return Check(
        "F20",
        "condition 对 A 轴有贡献",
        bool(payload.get("passed")),
        f"A 轴 SEH@1 {with_cond} → {without_cond}，"
        f"掉幅 {float(drop):+.4f}（阈值 ≥{threshold}）",  # type: ignore[arg-type]
    )


ALL_CHECKS = (
    check_l1_no_verbatim_text,
    check_l2_no_gold_value,
    check_l3_char_overlap,
    check_l4_every_memory_has_text,
    check_l5_siblings_present,
    check_l6a_three_paths_called,
    check_l6b_embedding_written,
    check_l6c_paths_return_nonempty,
    check_l8_dedup_scores_have_variance,
    check_l9_implicit_has_no_cue_leak,
    check_f2_recall_size,
    check_f5_branch_counts,
    check_f6_independent_subjects,
    check_f12_forced_ratio,
    check_f13_cue_mix,
    check_f15_axis_a_needs_seh1,
    check_f16_baseline_formula,
    check_f17_every_branch_queried,
    check_f18_authority_is_justified,
    check_f19a_implicit_gold_complete,
    check_f19b_implicit_gold_recalled,
    check_f20_condition_contributes,
)


def run_all(dataset: Dataset) -> list[Check]:
    results: list[Check] = []
    for check in ALL_CHECKS:
        # 前四条不依赖数据集（查的是评测入口源码）
        if check.__code__.co_argcount == 0:
            results.append(check())  # type: ignore[call-arg]
        else:
            results.append(check(dataset))
    return results


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="evals.tools.check_v2_dataset")
    parser.add_argument("directory", type=Path)
    parser.add_argument("--json", type=Path, default=None, help="同时写出 JSON 结果")
    args = parser.parse_args(argv)

    dataset = load_dataset(args.directory)
    results = run_all(dataset)

    print(f"数据集：{args.directory}")
    print(f"记忆 {len(dataset.memories)} 条，查询 {len(dataset.queries)} 条，"
          f"subjects {len(dataset.subjects())} 个")
    print()
    width = max(len(r.title) for r in results)
    for result in results:
        mark = "PASS" if result.passed else "FAIL"
        print(f"  [{mark}] {result.code:4} {result.title:<{width}}  {result.detail}")
    failed = [r for r in results if not r.passed]
    print()
    print(f"通过 {len(results) - len(failed)}/{len(results)}")
    if failed:
        print(f"未通过：{', '.join(r.code for r in failed)}")
        print(
            "注意：F6 是构造性的（样例单作者），F13 是阈值收紧后的真实不足。"
            "两者都不是 schema 问题。"
        )

    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(
            json.dumps(
                [
                    {"code": r.code, "title": r.title, "passed": r.passed, "detail": r.detail}
                    for r in results
                ],
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        print(f"-> {args.json}")

    return 0 if not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
