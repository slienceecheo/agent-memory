"""有效特征数必须从池里算出来，而不是从 `RerankWeights` 的字段数抄。

**缺陷**：报告原先写 A 轴 4 个有效特征、C 轴 3 个，来源是"`RerankWeights` 有四个字段"。
实测 `status` 在每条 case 的池内恒为 1.0（全部 `ACTIVE`），所以只有 3 / 2。

**为什么这条测试必须存在**：那三处数字（两份报告 + 协议）是手写的，
从来没有被算过。而 `test_rerank_variance.py` 断言的是 `counted >= 3`
且查的是 `data/conflict-set`（C4 旧数据），既不覆盖 v2，也不够严。

错误形状与下面三次同源——**用表示的形状代替它在具体语境下的取值**：

| 表述 | 形状 | 实际 |
|---|---|---|
| `SEH@5` 的 K=5 | 参数 K | 池只有 14 条，有效 K 更小 |
| 有效特征数 = 4 | 字段数 | 池内有方差的特征数 = 3 或 2 |
| F21b 的 20 个 subject | 总数 | 两档各 5 个，构造性不等 |
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from memory.retrieval.condition import condition_match
from memory.retrieval.rerank import authority_score, status_score
from memory.store.models import Authority, Status

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data" / "retrieval-v2"
REPORTS = {
    "v2-what-it-measures": ROOT / "docs" / "reports" / "v2-what-it-measures.md",
    "v2-axis-a": ROOT / "docs" / "reports" / "v2-axis-a-what-it-measures.md",
    "protocol": ROOT / "docs" / "requirements" / "retrieval-dataset-v2.md",
}


def _effective_feature_count(subject: str) -> dict[str, set[int]]:
    """对每个 case 用完整记忆池构造候选，数有几项特征有方差。

    返回 {axis: {有效特征数}}。
    """
    base = DATA / subject
    memories = [
        json.loads(line)
        for line in (base / "memories.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    queries = [
        json.loads(line)
        for line in (base / "queries.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]

    out: dict[str, set[int]] = {}
    for q in queries:
        qc = q.get("query_condition")
        cond = {
            condition_match(qc, m.get("condition")) for m in memories
        }
        auth = {
            authority_score(Authority(str(m.get("authority") or "user_direct")))
            for m in memories
        }
        status = {
            status_score(Status(str(m.get("status") or "active"))) for m in memories
        }
        # base 恒有方差（RRF 分数天然不同），计 1
        effective = 1 + (len(cond) > 1) + (len(auth) > 1) + (len(status) > 1)
        axis = str(q.get("axis") or "?")
        out.setdefault(axis, set()).add(effective)
    return out


@pytest.mark.skipif(not DATA.exists(), reason="缺 v2 数据集")
@pytest.mark.parametrize("subject", ["sample", "billing"])
def test_effective_feature_count_per_axis_is_3_and_2(subject: str) -> None:
    """A 轴 3 个、C 轴 2 个——不是 4 和 3。"""
    counts = _effective_feature_count(subject)

    assert counts.get("A") == {3}, f"{subject} A 轴有效特征数是 {counts.get('A')}"
    assert counts.get("C") == {2}, f"{subject} C 轴有效特征数是 {counts.get('C')}"


@pytest.mark.skipif(not DATA.exists(), reason="缺 v2 数据集")
@pytest.mark.parametrize("subject", ["sample", "billing"])
def test_status_feature_is_constant_within_every_pool(subject: str) -> None:
    """`status` 在每条 case 的池内恒为 1.0，所以它不是有效特征。

    这是"4 -> 3"的唯一原因。若哪天池里出现非 ACTIVE 记忆，这里会红，
    那时有效特征数要重算。
    """
    base = DATA / subject
    memories = [
        json.loads(line)
        for line in (base / "memories.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    values = {
        status_score(Status(str(m.get("status") or "active"))) for m in memories
    }

    assert values == {1.0}, f"{subject} 的 status 出现非恒等值 {values}"


@pytest.mark.skipif(not DATA.exists(), reason="缺 v2 数据集")
def test_reports_state_3_and_2_not_4_and_3() -> None:
    """三处文档的数字必须与实算一致。

    **这条是这次错误的直接防线**：那三处是手写的，从未被算过。
    """
    for name, path in REPORTS.items():
        if not path.exists():
            pytest.fail(f"{name} 不存在：{path}")
        text = path.read_text(encoding="utf-8")

        assert "| A | gold 1.00 / 兄弟 0.00 | **3** |" in text, (
            f"{name} 的 A 轴有效特征数不是 3"
        )
        # C 行必须整行匹配，否则 `| **2** |` 会命中文档里别处的表格
        assert "| C | **恒 0.50**" in text and "| **2** |" in text, (
            f"{name} 的 C 轴有效特征数不是 2"
        )
        c_line = next(
            (
                ln
                for ln in text.splitlines()
                if ln.startswith("| C |") and "**恒 0.50**" in ln
            ),
            None,
        )
        assert c_line is not None, f"{name} 找不到 C 行"
        assert c_line.rstrip().endswith("| **2** |"), (
            f"{name} 的 C 行结尾不是 **2**：{c_line.rstrip()}"
        )
        # 旧的 4/3 不得残留
        assert "| A | gold 1.00 / 兄弟 0.00 | **4** |" not in text, (
            f"{name} 仍写着 4"
        )


@pytest.mark.skipif(not DATA.exists(), reason="缺 v2 数据集")
def test_reports_record_the_correction() -> None:
    """三处都必须留下更正痕迹，否则读者会以为是笔误而非口径错误。"""
    for name, path in REPORTS.items():
        text = path.read_text(encoding="utf-8")
        assert "字段数 ≠ 有效特征数" in text, f"{name} 没有记录这个区分"
        assert "恒为" in text and "ACTIVE" in text, f"{name} 没有说明 status 为何无效"
