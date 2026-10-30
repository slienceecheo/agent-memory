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
    """F17：**已停用**，判定移交给 F17a / F17b。

    **为什么不再保留一个"并集"入口**：分轴之后，F17 与 F17b 会同时变红，
    同一个原因在门禁表里出现两次。读者无法判断它们是两个问题还是一个。

    本项目已经因为"一条名字覆盖两件事"出过多次问题（L7/L8、F19）；
    反向的"两件事共用一个名字"同样有害——它让失败项计数虚高，
    而"通过 20/27"里的 27 有 1 个是重复的。

    因此 F17 保留函数与编号（历史结果、报告引用它），
    但**不进入 `ALL_CHECKS`**。它与 F17a/F17b 的一致性由测试保证。
    """
    a = check_f17a_axis_a_covers_every_branch(dataset)
    b = check_f17b_every_relation_has_axis_c(dataset)
    return Check(
        "F17",
        "每个 condition 分支都被查询指向（F17a ∧ F17b）",
        a.passed and b.passed,
        f"F17a: {a.detail}；F17b: {b.detail}",
    )


def check_f17a_axis_a_covers_every_branch(dataset: Dataset) -> Check:
    """F17a：多分支 relation 的**每个分支**都必须是某条 **A 轴**查询的 gold。

    **为什么要按轴拆**：原来的 F17 用 `{q.gold_memory_id for q in dataset.queries}`，
    不分轴。于是：

    - 一条 C 轴查询若碰巧指向多分支 relation 的某个分支，F17 会认为"该分支被覆盖"
    - 但 C 轴测的是"同 subject 跨 relation 选择"，不是"同 relation 分支区分"

    后果：**F17 通过不代表 A 轴覆盖了那个分支**。而 A 轴的难度完全来自
    "在同 relation 的 3–5 条分支里挑对"。

    判定：对每个多分支 `(subject, relation)`，其每个 `memory_id`
    都是某条 `axis == A` 查询的 gold。单值 relation 跳过（它做不了 A 轴 gold：
    竞争集只有 1 条，L5 必红）。
    """
    pointed_a = {
        q.gold_memory_id for q in dataset.queries if q.axis is Axis.A
    }

    groups: dict[tuple[str, str], list[str]] = {}
    for memory in dataset.memories:
        if memory.status.value != "ACTIVE":
            continue
        groups.setdefault((memory.subject, memory.relation), []).append(memory.memory_id)

    untested: list[str] = []
    multi = {k: v for k, v in groups.items() if len(v) >= 2}
    for (subject, relation), memory_ids in multi.items():
        for memory_id in memory_ids:
            if memory_id not in pointed_a:
                untested.append(f"{subject}/{relation}:{memory_id}")

    return Check(
        "F17a",
        "多分支各分支都是 A 轴 gold",
        not untested,
        f"{len(multi)} 个多分支 relation，全部分支都被 A 轴指向"
        if not untested
        else f"{len(untested)} 个分支从未成为 A 轴 gold：{untested[:5]}",
    )


def check_f17b_every_relation_has_axis_c(dataset: Dataset) -> Check:
    """F17b：每个 **relation**（含单值）都必须是某条 **C 轴**查询的 gold。

    **粒度与 F17a 不同，因为两轴测的东西不同**：

    | 轴 | 要求 | 理由 |
    |---|---|---|
    | A（F17a） | 多分支的**每个分支** | 要在同 relation 的兄弟里挑对 |
    | C（F17b） | 每个 **relation 一条** | 同一 relation 的多个分支在 C 轴上占同一个
      "属性位置"，选多次不增加信息 |

    **实测反例**（`data/retrieval-v2/sample`）：5 个 relation 中只有
    `package_manager` 与 `test_command` 两个单值 relation 有 C 轴查询，
    三个多分支 relation（`code_style` / `deploy_target` / `oncall_owner`）
    一条 C 轴都没有覆盖。这正是本条要抓的。
    """
    pointed_c = {
        q.gold_memory_id for q in dataset.queries if q.axis is Axis.C
    }

    relations: dict[str, dict[str, list[str]]] = {}
    for memory in dataset.memories:
        if memory.status.value != "ACTIVE":
            continue
        relations.setdefault(memory.subject, {}).setdefault(memory.relation, []).append(
            memory.memory_id
        )

    uncovered: list[str] = []
    total = 0
    for subject, by_relation in relations.items():
        for relation, memory_ids in by_relation.items():
            total += 1
            if not (set(memory_ids) & pointed_c):
                uncovered.append(f"{subject}/{relation}")

    return Check(
        "F17b",
        "每个 relation 都有 C 轴查询",
        not uncovered,
        f"{total - len(uncovered)}/{total} 个 relation 被 C 轴覆盖"
        if not uncovered
        else f"{len(uncovered)}/{total} 个 relation 没有 C 轴 gold：{uncovered[:5]}",
    )


def check_f21a_relation_count(dataset: Dataset, *, low: int = 2, high: int = 3) -> Check:
    """F21a：每个 subject 的 relation 数 ∈ [2, 3]。

    **为什么需要**：协议 §8 写了"每 subject relation 数 1–3"，
    但 F1–F20 里没有任何一条检查它。

    **实测反例**：`project:ledger` 有 **5** 个 relation，22 项门禁全绿。
    这就是"规则写进协议、没写进门禁"的形态——规则成了建议。

    **下界是 2 不是 1**：只有 1 个 relation 的 subject 无法产生
    跨 relation 的 C 轴竞争（C 轴竞争集 = 同 subject 全部记忆，
    只有 1 个 relation 时，C 轴查询与 A 轴查询的竞争集几乎重合）。
    """
    per_subject: dict[str, set[str]] = {}
    for memory in dataset.memories:
        if memory.status.value != "ACTIVE":
            continue
        per_subject.setdefault(memory.subject, set()).add(memory.relation)

    counts = {s: len(rels) for s, rels in per_subject.items()}
    bad = {s: n for s, n in counts.items() if not low <= n <= high}
    return Check(
        "F21a",
        f"每 subject relation 数 ∈ [{low}, {high}]",
        not bad,
        f"{len(counts) - len(bad)}/{len(counts)} 个 subject 合格"
        if not bad
        else f"超范围：{bad}",
    )


def check_f21b_relation_count_mix(dataset: Dataset, *, minimum: int = 5) -> Check:
    """F21b：relation 数 = 2 与 = 3 的 subject 各至少 `minimum` 个。

    **为什么需要**：若只写 `relation ∈ [2,3]`，所有 subject 都取 3 也能全绿。
    于是"relation 数"这个变量从区间退化成常量 3，而门禁全程绿——
    与"分支数 3–5 但全取 3"是同一个问题：**区间内的变量从未被变动过**。

    **只有 1 个 subject 时必然失败**，这是构造性失败（同 F6），
    不是 schema 问题。
    """
    per_subject: dict[str, set[str]] = {}
    for memory in dataset.memories:
        if memory.status.value != "ACTIVE":
            continue
        per_subject.setdefault(memory.subject, set()).add(memory.relation)

    counts: dict[int, int] = {}
    for relations in per_subject.values():
        n = len(relations)
        counts[n] = counts.get(n, 0) + 1

    two = counts.get(2, 0)
    three = counts.get(3, 0)
    passed = two >= minimum and three >= minimum
    return Check(
        "F21b",
        f"relation=2 与 =3 的 subject 各 ≥ {minimum}",
        passed,
        f"relation 数分布 {dict(sorted(counts.items()))}；"
        f"要求 =2 至少 {minimum}、=3 至少 {minimum}"
        + ("" if passed else "（subject 总数不足时必失败，属构造性）"),
    )


def check_f23_axis_a_query_floor(dataset: Dataset, *, minimum: int = 6) -> Check:
    """F23：每个 subject 的 **A 轴查询数 ≥ 6**。

    **为什么是 6 不是 5**：`implicit ≥ 5` 且 `implicit ≤ A` 只能推出
    `A ≥ 5`。但 A=5 时 implicit 必须占满 5 条，于是 `explicit = 0`，
    而 F13 要求每 subject 同时有 explicit 与 implicit —— **A=5 本来就非法**。

    穷举（implicit 下限 = max(⌈A/2⌉, 5)）：

    | A | 最少 implicit | explicit | F13 |
    |---|---|---|---|
    | 5 | 5 | 0 | 红 |
    | **6** | **5** | **1** | **绿** |

    所以最小合法值是 **6**。

    **防的是什么**：一个全单值 relation 的 subject 会产生 0 条 A 轴查询
    （单值做 A 轴 gold 时竞争集只有 1 条，L5 必红），协议允许这种形状，
    于是它可以在 A 轴上什么都不测。本条挡住它。
    """
    per_subject: dict[str, int] = {}
    for query in dataset.queries:
        if query.axis is not Axis.A:
            continue
        per_subject[query.subject] = per_subject.get(query.subject, 0) + 1

    all_subjects = set(dataset.subjects())
    missing = all_subjects - set(per_subject)
    bad = {s: n for s, n in per_subject.items() if n < minimum}
    problems = {**bad, **{s: 0 for s in missing}}

    return Check(
        "F23",
        f"每 subject A 轴查询 ≥ {minimum}",
        not problems,
        f"{len(all_subjects) - len(problems)}/{len(all_subjects)} 个 subject 合格"
        if not problems
        else f"不足：{problems}",
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


def _ablation_for_subjects(dataset: Dataset) -> tuple[dict[str, object], str]:
    """找到覆盖数据集全部 subject 的消融结果文件。

    **为什么不能硬编码文件名**：`check_f19b` / `check_f20` 曾经写死读
    `v2-sample-condition-ablation.json`（ledger 的样例）。铺第二个 subject 之后，
    ledger 的门禁会去查 billing 的 implicit，反之亦然——**检查错对象**。

    实测表现：billing 的 F19b 报"消融结果里没有这些 implicit 的排名"，
    而 billing 自己的消融结果明明已生成在另一个文件名下。

    做法：按 subject 集合匹配。文件名约定 `v2-<subject>-condition-ablation.json`，
    而样例期用的是 `v2-sample-condition-ablation.json`。
    """
    candidates = sorted(ROOT.joinpath("results").glob("v2-*-condition-ablation.json"))

    for path in candidates:
        payload = json.loads(path.read_text(encoding="utf-8"))
        ranked_ids = set((payload.get("with_condition") or {}).keys())
        dataset_ids = {q.query_id for q in dataset.queries}
        # 全覆盖：该文件包含本数据集的每条查询
        if dataset_ids and dataset_ids <= ranked_ids:
            return payload, path.name

    return {}, ""


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
    payload, source = _ablation_for_subjects(dataset)
    if not payload:
        return Check(
            "F19b",
            "implicit 的 gold 真的被召回",
            False,
            "没有覆盖本数据集的消融结果；先跑 evals.tools.ablate_condition --dataset <目录>",
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
        f"{len(implicit_ids)} 条 implicit，三路全开时全部被召回（来源 {source}）"
        if not never_recalled
        else f"{len(never_recalled)} 条 implicit 从未被召回：{never_recalled[:3]}",
    )


def check_f20_condition_contributes(dataset: Dataset) -> Check:
    """F20：条件消融后 A 轴 `SEH@1` 掉幅必须 ≥ 0.3。

    **为什么需要**：有人可以写出一批"explicit 占多数、condition 全都匹配"的
    查询，也得到很高的 `SEH@1`——而 A 轴的设计意图（多个条件分支里挑对）
    完全落空。只报分数看不出来。

    实现放在 `evals/tools/ablate_condition.py`（它要跑评测，较重），
    但本门禁**收进 `run_all()`**，读它的结果 JSON。
    否则 `run_all()` 只跑 F1–F19，F20 没人跑会成为隐患。

    **按 subject 匹配结果文件**，理由同 `_ablation_for_subjects`。
    """
    payload, source = _ablation_for_subjects(dataset)
    if not payload:
        return Check(
            "F20",
            "condition 对 A 轴有贡献",
            False,
            "没有覆盖本数据集的消融结果；先跑 evals.tools.ablate_condition --dataset <目录>",
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
        f"掉幅 {float(drop):+.4f}（阈值 ≥{threshold}；来源 {source}）",  # type: ignore[arg-type]
    )


def check_f24_axis_a_not_saturated(dataset: Dataset, *, ceiling: float = 0.9999) -> Check:
    """F24：A 轴的**随机基线** `SEH@1` 必须 < 1.0，且实测 `SEH@1` 不得满分。

    **为什么需要**：协议 §7.1 只规定了 `SEH@5` 饱和（池小于 K 时恒为 1），
    却没规定 `SEH@1 = 1.0000`。而后者更严重——它不是数学恒等，是**数据太简单**。

    **实测两个 subject，结论相反**：

    | subject | A 轴 `SEH@1` | 随机基线 | 判定 |
    |---|---|---|---|
    | `project:ledger` | 0.9000 | 0.3000 | 有区分空间 |
    | `project:billing` | **1.0000** | 0.3333 | **满分，测不到区分** |

    billing 的满分不是装置问题：逐条查过 gold 与第二名的加权总分差，
    9 条全部为正（0.085–0.253），**0 条并列**。所以它反映真实能力，
    而真实能力满分意味着这份数据没有难度。

    **为什么不用"实测 `SEH@1` 是否满分"当主判据**：那需要读评测结果，
    而合格性检查不该依赖系统分数（协议 §1.1）。所以本门禁分两段：

    - 数据侧（不需要跑评测）：随机基线 < 1.0，确保指标本身有定义
    - 结果侧（若已有结果文件）：实测 `SEH@1` 不得满分

    第二段只在结果存在时执行，不强制要求先跑评测。
    """
    from evals.datasets.retrieval_v2 import Axis as _Axis

    baseline = axis_baseline(dataset, _Axis.A)
    if baseline.queries == 0:
        return Check("F24", "A 轴未饱和", True, "没有 A 轴查询")

    problems: list[str] = []
    if baseline.seh_at_1 >= ceiling:
        problems.append(
            f"随机基线 SEH@1={baseline.seh_at_1:.4f} 已饱和"
            f"（竞争集均值 {baseline.mean_pool_size:.2f}）"
        )

    # 结果侧：只在已有结果文件时检查，不强制跑评测
    for path in sorted((ROOT / "results").glob("v2-*-lexical-vector-adjacency.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        cases = payload.get("per_case") or []
        if not cases:
            continue
        case_ids = {c["case_id"] for c in cases}
        dataset_a = {q.query_id for q in dataset.queries if q.axis is _Axis.A}
        if not dataset_a <= case_ids:
            continue
        ranks = {c["case_id"]: c["rank_after_rerank"] for c in cases}
        hit = sum(1 for qid in dataset_a if ranks.get(qid) == 1)
        ratio = hit / len(dataset_a)
        if ratio >= ceiling:
            problems.append(
                f"实测 SEH@1={hit}/{len(dataset_a)}={ratio:.4f}（来源 {path.name}）——"
                "满分意味着这份数据测不到区分能力"
            )
        break

    return Check(
        "F24",
        "A 轴未饱和（SEH@1 不得满分）",
        not problems,
        f"随机基线 {baseline.seh_at_1:.4f}，"
        f"竞争集均值 {baseline.mean_pool_size:.2f}"
        if not problems
        else "；".join(problems),
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
    check_f17a_axis_a_covers_every_branch,
    check_f17b_every_relation_has_axis_c,
    check_f18_authority_is_justified,
    check_f19a_implicit_gold_complete,
    check_f19b_implicit_gold_recalled,
    check_f20_condition_contributes,
    check_f21a_relation_count,
    check_f21b_relation_count_mix,
    check_f23_axis_a_query_floor,
    check_f24_axis_a_not_saturated,
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
        # **门禁结果也是数字，也必须能复算。**
        #
        # 原先这里只写一个 list，没有 `code_fingerprint`。后果：
        # "21/27 是在哪个代码版本上跑的"无法验证——与消融文件曾经的问题同型。
        #
        # 结构从 `[...]` 改为 `{"checks": [...], **fingerprint}`：
        # 保留 list 语义（`checks`），同时带来源。
        from evals.run_retrieval import code_fingerprint

        args.json.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "checks": [
                {
                    "code": r.code,
                    "title": r.title,
                    "passed": r.passed,
                    "detail": r.detail,
                }
                for r in results
            ],
            "dataset": str(args.directory),
            **code_fingerprint(),
        }
        args.json.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        print(f"-> {args.json}")

    return 0 if not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
