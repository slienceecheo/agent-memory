"""C4 读数缺陷的一致性检查。

**为什么需要这个文件**：C4 报告原先写"这些不是实现缺陷，是数据表达能力的上限"。
事后查明 1.000 是测量装置缺陷。若只改报告、不加测试，下一次有人改数据或改池构造，
这些缺陷会静默回来，而报告仍是那份报告。

本文件锁四件事：

1. 泄漏消融的数字（0.606 / 0.412 / 0.500）可复算
2. 排名确实从未在 independent 上发生（26/26 只有一个候选）
3. 干扰项不是随机采样，而是固定前缀（15 种组合，一种用了 36 次）
4. 报告正文与 HANDOFF 都写明了这件事，不许被删掉

**带 `locked_defect` 标记的测试断言的是"现状是坏的"。**
修复对应缺陷时它们会变红——那是预期的，请同步更新报告第 0.1 节。
冻结前用 `pytest -m locked_defect -q` 核对数量与报告缺陷数一致。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
RESULTS = ROOT / "results"
REPORT = ROOT / "docs" / "reports" / "c4-retrieval.md"
HANDOFF = ROOT / "docs" / "HANDOFF.md"
LEAK = RESULTS / "c4-query-leak-ablation.json"


def _leak() -> dict[str, object]:
    if not LEAK.exists():
        pytest.skip("泄漏消融结果缺失，先跑 evals.tools.diagnose_c4_leak")
    return json.loads(LEAK.read_text(encoding="utf-8"))


@pytest.mark.parametrize(
    ("split", "expected"),
    [("dev", 0.606), ("test", 0.412), ("independent", 0.500)],
)
def test_masking_gold_text_collapses_the_score(split: str, expected: float) -> None:
    """抹掉 gold 原文后 SEH@5 必须掉到报告里写的那个数。

    这三个数字是整份报告的重点。若它们变化，说明数据、池构造或召回被改动了，
    报告里的结论需要重新推导——而不是让测试跟着数字改。
    """
    payload = _leak()
    variants = payload["variants"][split]  # type: ignore[index]

    assert variants["V0"]["seh_at_k"] == pytest.approx(1.0)
    assert variants["V1"]["seh_at_k"] == pytest.approx(expected, abs=0.001)


@pytest.mark.locked_defect
def test_query_is_verbatim_the_gold_document() -> None:
    """C4 的根本缺陷：gold 的索引原文就是 query 本身。

    这条断言锁的是**缺陷的存在**，不是期望的行为。它应当一直失败到 v2 数据集
    替换掉旧集；在那之前，它是"不要用旧集下结论"的机器可读提醒。
    """
    data = ROOT / "data" / "conflict-set"
    identical = 0
    total = 0
    for name in ("dev.jsonl", "test.jsonl", "independent.jsonl"):
        for line in (data / name).read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            if not row.get("gold"):
                continue
            total += 1
            if row["query"].strip() == row["text"].strip():
                identical += 1

    assert total > 0
    assert identical == total, (
        f"只有 {identical}/{total} 条 query 与原文逐字相同；"
        "若旧集被修复，本测试与报告第 0.1 节都应更新"
    )


@pytest.mark.locked_defect
def test_ranking_never_happened_on_independent() -> None:
    """independent 上每条 case 的召回集都只有 1 条候选。

    这是"SEH 恒为 1 是空操作"的机器可读证据。
    """
    payload = _leak()
    histogram = payload["variants"]["independent"]["V0"]["recall_size_histogram"]

    assert histogram == {"1": 26}


@pytest.mark.locked_defect
@pytest.mark.parametrize("split", ["dev", "test", "independent"])
def test_authority_and_status_have_no_variance_in_pool(split: str) -> None:
    """四个特征里有两个在真实候选池上恒为常数。

    `test_rerank_variance.py` 查的是数据集字段，所以它一直是绿的。
    这条查的是**候选池内的候选**，才是重排真正看到的输入。
    """
    payload = _leak()
    with_variance = payload["feature_variance_v0"][split]["with_variance"]  # type: ignore[index]

    assert with_variance["authority"] == 0
    assert with_variance["status"] == 0


@pytest.mark.locked_defect
def test_distractors_are_a_fixed_prefix_not_a_sample() -> None:
    """干扰项用 `others[:limit]`，不是随机采样。

    76 条场景只有 15 种组合，其中一种被复用了 36 次。
    """
    payload = _leak()
    sampling = payload["distractor_sampling"]

    assert sampling["distinct_compositions"] == 15
    assert sampling["most_reused_composition_count"] == 36


def test_report_documents_the_leak() -> None:
    """报告必须写出缺陷，且写明"查询就是答案"。

    否则读者只会看到"满分不能证明能力"，而不知道满分是怎么来的。
    """
    text = REPORT.read_text(encoding="utf-8")

    # 标题在报告重构成 0.1/0.2/0.3/0.4/0.5 时改过名。
    # 断言改按内容而不是按旧标题，否则每次重构都要改测试。
    assert "0.1 最早发现的八个缺陷" in text
    assert "0.4 缺陷总表（十三条）" in text
    assert "查询就是答案" in text
    assert "0.606" in text
    assert "0.412" in text
    assert "0.500" in text
    assert "排名从未发生" in text


def test_report_separates_unit_tested_from_end_to_end() -> None:
    """第 5 节必须区分"单元测试通过"与"端到端验证过"。

    原表把两者合成一列"验证方式"，读者会以为三路召回、RRF、重排、
    语义去重都跑过联合评测。实际只有词面一路进过评测入口。
    """
    text = REPORT.read_text(encoding="utf-8")

    assert "单元测试" in text
    assert "端到端验证过" in text
    assert "从未联合跑过" in text
    # 关键：不得再暗示三路都被端到端验证
    table = text.split("## 5. 已建成的能力")[1].split("## 6.")[0]
    assert table.count("❌") >= 3, "第 5 节应有多项标为未端到端验证"


def test_report_documents_dedup_id_defect() -> None:
    """缺陷 8 必须写明：dedup 收到 UUID，排序退化为字典序。"""
    text = REPORT.read_text(encoding="utf-8")

    assert "UUID" in text
    assert "字典序" in text
    assert "缺陷 7 掩盖了缺陷 8" in text


def test_report_no_longer_claims_all_capabilities_built() -> None:
    """第 5 节的表头不得再用单一"验证方式"列掩盖差距。"""
    text = REPORT.read_text(encoding="utf-8")
    section = text.split("## 5. 已建成的能力")[1].split("## 6.")[0]

    assert "| 能力 | 单元测试 | 端到端验证过 |" in section
    assert "| 能力 | 验证方式 |" not in section


def test_report_no_longer_blames_only_the_data() -> None:
    """不得再说"这不是实现缺陷"——1.000 本身就是实现缺陷。"""
    text = REPORT.read_text(encoding="utf-8")

    assert "目前的实现没有缺陷" not in text
    assert "这个判断错了一半" in text


def test_handoff_carries_the_warning() -> None:
    """交接文档必须让人在读到 1.000 时先看到警告。"""
    text = HANDOFF.read_text(encoding="utf-8")

    assert "不可用" in text
    assert "不要把这个 1.000 当作优点介绍" in text
    assert "c4-query-leak-ablation.json" in text


def test_retrieval_entry_now_runs_lexical_and_vector() -> None:
    """缺陷 7 的一半已修复：评测入口接上了词面与向量两路。

    **原先这条是 `locked_defect`，断言"只调用 lexical"。**
    现在改成正向断言：修复提交就是它该翻面的时机。

    仍未接的是 adjacency（第 3 组），所以这里只断言两路——
    等邻接接上后，本断言应扩展为三路，并在那时更新 C4 报告。

    **判定必须看调用位置，不能 `grep -c "recall_by_"`**：
    import 行里就含这些名字，按字符串计数会误报。
    """
    source = (ROOT / "evals" / "run_retrieval.py").read_text(encoding="utf-8")

    called = {
        name
        for name in ("lexical", "vector", "adjacency")
        if f"recall_by_{name}(" in source
    }

    assert {"lexical", "vector"} <= called, f"应至少调用词面与向量，实际 {sorted(called)}"


def test_embedding_is_written_into_the_pool() -> None:
    """L6b 已修复：建池时确实写入向量。

    **原先这条是 `locked_defect`，断言 `embedding=` 一次都不出现。**
    现在改成正向断言。"调用了"与"有东西可召回"是两件事，
    所以必须检查写入动作本身，而不只是 import。
    """
    source = (ROOT / "evals" / "run_retrieval.py").read_text(encoding="utf-8")

    assert "embedding=embedding" in source, (
        "建池时应把生成的向量传给 store.insert；若改法变了，请更新这条断言"
    )
    assert 'text_type="document"' in source, "池内条目必须用 document 侧向量"


def test_dedup_receives_text_and_real_scores() -> None:
    """缺陷 8 已修复：dedup 收到原文与真实融合分。

    **原先这条是 `locked_defect`，断言"仍是 `(item_id, item_id, 1.0)`"。**
    现在改成正向断言。

    **为什么不从结果文件判 L7**：`a3-with-dedup.json` 里的
    `dedup_input_tags` 记的是"哪几条进了 dedup"（稳定 tag），
    不是"传了什么文本"。用它判 L7 会判错对象——
    这正是 L7 此前"通过但没测到"的根源（tag 不是 uuid，断言就过了）。

    所以 L7 只能从两处验：
    1. 本测试：源码形态（`_dedup_text(` 被调用、不再是 `(id, id, 1.0)`）
    2. `tests/retrieval/test_dedup_text.py`：`_dedup_text` 的构造规则

    L8（分数有方差）则**可以**从结果文件判，见
    `evals/tools/check_v2_dataset.py::check_l8_dedup_scores_have_variance`。
    两条证据源不同，不能合并成一个门禁。
    """
    text = (ROOT / "evals" / "run_retrieval.py").read_text(encoding="utf-8")

    assert "texts = [(item_id, item_id, 1.0) for item_id in order]" not in text, (
        "又回到传 id 与常数分了"
    )
    assert "score_by_id[item_id]" in text, "去重分数应取自融合分"
    # 文本不再从 `source_text` 读：那是候选值/新声明的话，不是本条记忆的话。
    # 用 `_dedup_text`（subject + relation + value + condition）才既含定位字段
    # 又含条件分支，见 `tests/retrieval/test_dedup_text.py`。
    assert "_dedup_text(" in text, "去重文本应由 `_dedup_text` 构造"


@pytest.mark.locked_defect
def test_constant_scores_turn_dedup_into_a_lexical_sort() -> None:
    """常数分数 + "全判无关" 也会把顺序反转。

    这是缺陷 8 的**局部可验证证据**，不依赖数据集：
    `dedup` 内部按 `(-score, id)` 排序，score 全等时退化为 id 字典序。
    """
    from memory.retrieval.dedup import dedup
    from memory.retrieval.equivalence import Equivalence

    class AlwaysUnrelated:
        enabled = True

        def judge(self, left: str, right: str) -> object:
            return type("R", (), {"equivalence": Equivalence.UNRELATED})()

    order = ["zzz", "mmm", "aaa", "bbb"]
    texts = [(item_id, item_id, 1.0) for item_id in order]

    kept, stats = dedup(texts, judge=AlwaysUnrelated(), top_k=5)  # type: ignore[arg-type]

    assert stats.merged == 0, "本该一条都不合并"
    assert [entry[0] for entry in kept] == ["aaa", "bbb", "mmm", "zzz"], (
        "顺序不再是字典序了；说明 dedup 的排序键被改动，请复核报告缺陷 8"
    )
