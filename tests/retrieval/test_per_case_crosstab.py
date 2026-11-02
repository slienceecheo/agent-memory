"""`per_case` 记录格式的交叉表：从数据算，与文档比对。

**为什么必须从数据算**：这张表的十条组合和其中的数字，
是这一轮唯一一次"跑出交叉表才发现模型错"的产物。
而它之前的三条说法（短缺=skipped、无 gold 一律 8 键、三个变量正交）
都是**从少量观测推出来的**。

所以这条测试的作用是：让交叉表本身成为判据，
而不是让文档里的表成为"最后一版手写"。
"""

from __future__ import annotations

import itertools
import json
from collections import defaultdict
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
RESULTS = ROOT / "results"
HANDOFF = ROOT / "docs" / "HANDOFF.md"


def crosstab() -> dict[tuple[str, str, int], dict]:
    """返回 {(has_gold, skipped, 键数): {records, files}}。

    has_gold / skipped 取值：'True' / 'False' / 'missing'。
    """
    rows: dict[tuple[str, str, int], dict] = defaultdict(
        lambda: {"records": 0, "files": set()}
    )

    for p in sorted(RESULTS.glob("*.json")):
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        if not isinstance(d, dict):
            continue
        pc = d.get("per_case")
        if not isinstance(pc, list):
            continue
        for r in pc:
            if not isinstance(r, dict):
                continue
            hg = str(r["has_gold"]) if "has_gold" in r else "missing"
            sk = str(r["skipped"]) if "skipped" in r else "missing"
            key = (hg, sk, len(r))
            rows[key]["records"] += 1
            rows[key]["files"].add(p.name)

    return dict(rows)


def test_crosstab_has_ten_combinations() -> None:
    """交叉表恰好十条组合。多一条或少一条都说明记录格式变了。"""
    table = crosstab()
    combos = sorted(table, key=lambda x: (x[0], x[1], x[2]))
    assert len(combos) == 10, (
        f"组合数变成 {len(combos)}：\n"
        + "\n".join(f"  {c}: {table[c]['records']} 条" for c in combos)
    )


def test_crosstab_matches_documented_numbers() -> None:
    """每条的记录数与文件数必须与文档一致。

    **两个方向都要检查**：
      1. 从数据算出的表 == 期望值
      2. 文档里的表 == 期望值

    只写第一条，文档改了测试不会红——这是本轮第四次同类疏漏
    （前三次：locked_defect 计数、算术可复算、五类分布）。
    """
    table = crosstab()

    expected = {
        ("True", "missing", 25): (132, 11),
        ("True", "missing", 20): (222, 8),
        ("True", "missing", 13): (33, 1),
        ("True", "missing", 8): (206, 8),
        ("True", "missing", 7): (26, 1),
        ("True", "True", 10): (52, 2),
        ("False", "missing", 8): (91, 17),
        ("False", "missing", 7): (4, 1),
        ("missing", "missing", 12): (30, 1),
        ("missing", "missing", 6): (120, 4),
    }

    actual = {k: (v["records"], len(v["files"])) for k, v in table.items()}
    assert actual == expected, (
        f"交叉表变了：\n实际 {actual}\n文档 {expected}"
    )

    # 方向 2：文档里的十行必须与算出来的一致
    text = HANDOFF.read_text(encoding="utf-8")
    marker = "#### `per_case` 的记录格式：交叉表推翻了链条模型"
    assert marker in text
    section = text.split(marker)[1].split("\n#### ")[0]

    def _clean(cell: str) -> str:
        return cell.replace("`", "").replace("*", "").strip()

    doc_by_records: dict[tuple[str, str, int], tuple[int, int]] = {}
    for line in section.splitlines():
        if not line.startswith("|"):
            continue
        cells = [_clean(c) for c in line.strip().strip("|").split("|")]
        if len(cells) != 5:
            continue
        hg, sk, k, rec, files = cells
        if hg not in ("True", "False", "缺"):
            continue
        if not k.isdigit():
            continue
        # 文档用"缺"表示 missing
        hg_norm = "missing" if hg == "缺" else hg
        sk_norm = "missing" if sk == "缺" else sk
        doc_by_records[(hg_norm, sk_norm, int(k))] = (int(rec), int(files))

    assert len(doc_by_records) == 10, (
        f"文档表格行数变成 {len(doc_by_records)}：{sorted(doc_by_records)}"
    )
    assert doc_by_records == expected, (
        f"文档表格与算出的不一致：\n文档 {doc_by_records}\n应为 {expected}"
    )


def test_no_gold_never_carries_skipped() -> None:
    """**无 gold 与 skipped 互斥**——实测这一条推翻了"短缺=被跳过"的猜测。"""
    table = crosstab()
    bad = [k for k in table if k[0] == "False" and k[1] != "missing"]
    assert not bad, f"出现 has_gold=False 且带 skipped 的组合：{bad}"


def test_no_gold_key_count_follows_file_version() -> None:
    """**`has_gold=False` 不一律是 8 键**——有 4 条是 7 键。

    这一条推翻了"无 gold = 8 键"的说法。正确规律是：
    无 gold 记录的键数跟它所在文件的版本走。
    """
    table = crosstab()
    counts = sorted(k[2] for k in table if k[0] == "False")

    assert counts == [7, 8], f"无 gold 的键数分布变成 {counts}"
    # 4 条 7 键、91 条 8 键
    assert table[("False", "missing", 7)]["records"] == 4
    assert table[("False", "missing", 8)]["records"] == 91


def test_skipped_only_appears_at_ten_keys() -> None:
    """`skipped=True` 只出现在 10 键，且只在两个池模式文件。"""
    table = crosstab()
    skipped_rows = [k for k in table if k[1] == "True"]

    assert len(skipped_rows) == 1, f"skipped=True 出现在多个键数：{skipped_rows}"
    assert skipped_rows[0][2] == 10

    files = table[skipped_rows[0]]["files"]
    assert files == {
        "retrieval-independent-uniform-nodedup-pooladversarial.json",
        "retrieval-independent-uniform-nodedup-poolsame_relation.json",
    }, f"skipped 出现的文件变了：{sorted(files)}"


def test_eight_keys_has_two_sources() -> None:
    """**8 键有两个来源**：完整记录（has_gold=True）与无 gold 记录。

    这是"两个来源产生同一个形状"，而形状检查永远不红。
    """
    table = crosstab()
    eight = {k: v for k, v in table.items() if k[2] == 8}

    assert set(eight) == {("True", "missing", 8), ("False", "missing", 8)}, (
        f"8 键的来源变了：{sorted(eight)}"
    )

    with_gold = eight[("True", "missing", 8)]
    without_gold = eight[("False", "missing", 8)]

    assert with_gold["records"] == 206 and len(with_gold["files"]) == 8
    assert without_gold["records"] == 91 and len(without_gold["files"]) == 17

    # **关键**：有 gold 的那 8 个文件，全部包含在无 gold 的 17 个里
    assert with_gold["files"] <= without_gold["files"], (
        "两者不再是子集关系——8 键的两个来源不再重叠于同一批文件"
    )


def test_backbone_is_subset_chain() -> None:
    """主干 7 ⊂ 8 ⊂ 13 ⊂ 20 ⊂ 25，旁支 8 ⊂ 10 且 10 ⊄ 13。"""
    keysets: dict[int, set[str]] = {}

    # 取每个"主干"键数的实际键集合（用一条记录还原）
    for p in sorted(RESULTS.glob("*.json")):
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        if not isinstance(d, dict):
            continue
        for r in d.get("per_case") or []:
            if not isinstance(r, dict):
                continue
            if "skipped" in r:
                continue
            n = len(r)
            if n in (7, 8, 13, 20, 25):
                keysets.setdefault(n, set(r.keys()))

    chain = [7, 8, 13, 20, 25]
    for a, b in itertools.pairwise(chain):
        assert keysets[a] <= keysets[b], f"{a} 不是 {b} 的子集"

    # 旁支：8 ⊂ 10
    ten = None
    for p in sorted(RESULTS.glob("*.json")):
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        if not isinstance(d, dict):
            continue
        for r in d.get("per_case") or []:
            if isinstance(r, dict) and "skipped" in r:
                ten = set(r.keys())
                break
        if ten:
            break
    assert ten is not None, "找不到 10 键记录"
    assert keysets[8] <= ten, "8 键不是 10 键的子集"
    assert not (ten <= keysets[13]), "10 键是 13 键的子集——旁支判断失效"


def test_handoff_records_the_overturned_claims() -> None:
    """文档必须写明被推翻的三条，以及成立的三条。"""
    text = HANDOFF.read_text(encoding="utf-8")

    marker = "#### `per_case` 的记录格式：交叉表推翻了链条模型"
    assert marker in text, "找不到交叉表小节"
    # 该小节后面还有若干 #### 子节，所以要截到下一个 **###**（同级或更高级）
    import re

    rest = text.split(marker)[1]
    m = re.search(r"^#{2,3} ", rest, re.M)
    section = rest[: m.start()] if m else rest

    # 被推翻的三条
    assert "三条被推翻的说法" in section
    assert "短缺记录是 `skipped` 的" in section
    assert "一律 8 键" in section
    assert "三个变量正交" in section

    # 成立的三条
    assert "无 gold 与 skipped 互斥" in section
    assert "只出现在 10 键" in section
    assert "10 ⊄ 13" in section

    # 8 键双来源
    assert "8 键有两个来源" in section
    assert "两个来源产生同一个形状" in section


def _per_file_kind() -> dict[str, str]:
    """每个有 per_case 的文件 -> full_fp / version_only / none。"""
    out: dict[str, str] = {}
    for p in sorted(RESULTS.glob("*.json")):
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        if not isinstance(d, dict):
            continue
        if not isinstance(d.get("per_case"), list):
            continue
        ver, h = d.get("code_version"), d.get("code_diff_hash")
        if ver is not None and h is not None:
            out[p.name] = "full_fp"
        elif ver is not None or h is not None:
            out[p.name] = "version_only"
        else:
            out[p.name] = "none"
    return out


def test_two_coverage_rates() -> None:
    """**格式分析 18/36 = 50%，数字复算 17/36 = 47%。**

    差异只有 1 个文件（有 version 无 hash）——它能证明 commit，不能证明工作区干净。
    """
    kinds = _per_file_kind()
    total = len(kinds)
    assert total == 36, f"有 per_case 的文件数变成 {total}"

    from collections import Counter

    c = Counter(kinds.values())
    assert c["full_fp"] == 17, f"full_fp 变成 {c['full_fp']}"
    assert c["version_only"] == 1
    assert c["none"] == 18

    # 两个覆盖率
    format_cov = (c["full_fp"] + c["version_only"]) / total
    numeric_cov = c["full_fp"] / total
    assert format_cov == pytest.approx(0.50, abs=0.01)
    assert numeric_cov == pytest.approx(0.472, abs=0.01)


def test_equation_is_one_to_one_on_fingerprinted_files() -> None:
    """`(code_version, branch) -> 键数` 在指纹可用文件上必须 1:1（0 例外）。"""
    kinds = _per_file_kind()
    table: dict[tuple[str, str], dict[int, int]] = defaultdict(lambda: defaultdict(int))

    for p in sorted(RESULTS.glob("*.json")):
        if kinds.get(p.name) not in ("full_fp", "version_only"):
            continue
        d = json.loads(p.read_text(encoding="utf-8"))
        ver = d["code_version"]
        for r in d["per_case"]:
            if not isinstance(r, dict):
                continue
            hg, sk = r.get("has_gold"), r.get("skipped")
            br = "no_gold" if hg is False else ("skipped" if sk is True else "normal")
            table[(ver, br)][len(r)] += 1

    multi = {k: dict(v) for k, v in table.items() if len(v) != 1}
    assert not multi, f"出现多值组合：{multi}"

    # 六个组合：**含 `5e8a3d6`（version_only）**——
    # 键数只依赖 commit，所以它能为格式分析作证，分 2 个分支。
    assert set(table) == {
        ("47e4785-dirty", "normal"),
        ("5e8a3d6", "no_gold"),
        ("5e8a3d6", "normal"),
        ("899e2b6-dirty", "no_gold"),
        ("899e2b6-dirty", "normal"),
        ("8b1b600-dirty", "normal"),
    }, f"组合集变了：{sorted(table)}"

    # 而"数字复算"口径（只算 full_fp）是 4 个组合
    full_only = {k for k in table if k[0] != "5e8a3d6"}
    assert len(full_only) == 4, f"full_fp 下的组合数变成 {len(full_only)}"


def test_skipped_is_attributable_even_without_fingerprint() -> None:
    """**`skipped` 分支在 `<none>` 下仍是单一键数**——因为它是硬编码的。

    所以"无指纹 = 不可归因"过强：只有依赖版本的属性才失去归因能力。
    """
    kinds = _per_file_kind()
    by_branch: dict[str, dict[int, int]] = defaultdict(lambda: defaultdict(int))

    for p in sorted(RESULTS.glob("*.json")):
        if kinds.get(p.name) != "none":
            continue
        d = json.loads(p.read_text(encoding="utf-8"))
        for r in d["per_case"]:
            if not isinstance(r, dict):
                continue
            hg, sk = r.get("has_gold"), r.get("skipped")
            br = "no_gold" if hg is False else ("skipped" if sk is True else "normal")
            by_branch[br][len(r)] += 1

    assert dict(by_branch["skipped"]) == {10: 52}, (
        f"skipped 不再单一：{dict(by_branch['skipped'])}"
    )
    # 另两个分支是多值
    assert len(by_branch["no_gold"]) > 1, "no_gold 变成单一了，结论要更新"
    assert len(by_branch["normal"]) > 1, "normal 变成单一了，结论要更新"

    # 具体分布（这一轮我报错过一次：8 键 63 / 20 键 66 是错的）
    assert dict(by_branch["no_gold"]) == {7: 4, 8: 56}
    assert dict(by_branch["normal"]) == {
        6: 120, 7: 26, 8: 206, 12: 30, 13: 33, 20: 33
    }


def test_handoff_records_two_coverage_rates() -> None:
    """文档必须写两个覆盖率，并说明差异只有 1 个文件。"""
    text = HANDOFF.read_text(encoding="utf-8")
    marker = "#### 键数的等式"
    assert marker in text
    section = text.split(marker)[1].split("\n#### ")[0]

    assert "**18**" in section and "**17**" in section
    assert "50%" in section and "47%" in section
    assert "`5e8a3d6`" in section
    # 用途区分——整行匹配，避免只命中数字
    assert "| **格式分析**（键数） | 只需 commit | **18** | **50%** |" in section
    numeric_row = "| **数字复算**（指标准确） | commit **+** 工作区是否干净 | **17** | **47%** |"
    assert numeric_row in section
    # 六个组合（含 5e8a3d6 的两行）
    assert "**6 个组合，0 例外**" in section
    assert "| `5e8a3d6` | `no_gold` | 8 | 7 | **仅格式分析** |" in section
    assert "| `5e8a3d6` | `normal` | 20 | 33 | **仅格式分析** |" in section
    assert "**6 个组合里有 2 个只对\"格式分析\"可归因**" in section


def test_handoff_records_attributability_depends_on_constant() -> None:
    """必须写明"可归因取决于是否常量"，并给出 skipped 的反例。"""
    text = HANDOFF.read_text(encoding="utf-8")
    marker = "#### 键数的等式"
    section = text.split(marker)[1].split("\n#### ")[0]

    assert "无指纹" in section and "不可归因" in section
    assert "**硬编码 10**" in section
    assert "`{10: 52}` 单一" in section


@pytest.mark.parametrize("key_count", [7, 8, 13, 20, 25])
def test_backbone_key_counts_have_records(key_count: int) -> None:
    """主干每个键数都必须至少有一条记录。"""
    table = crosstab()
    hits = [k for k in table if k[2] == key_count and k[1] == "missing"]
    assert hits, f"主干键数 {key_count} 没有任何记录"
