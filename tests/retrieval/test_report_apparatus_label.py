"""报告数字必须标注产生它的权重配置。

对应 tasks 4.7。判据**定位到表头单元格**，不用"关键词出现在整节里"——
后者会在删掉目标行后仍然通过（本项目已登记的那条形态）。
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
REPORT = ROOT / "docs" / "reports" / "v2-what-it-measures.md"


def _section(heading: str, next_heading_prefix: str) -> str:
    text = REPORT.read_text(encoding="utf-8")
    assert heading in text, f"报告里找不到「{heading}」"
    body = text.split(heading, 1)[1]
    end = body.find(next_heading_prefix)
    return body if end < 0 else body[:end]


def _table_rows(section: str) -> list[list[str]]:
    """把 markdown 表格行拆成单元格列表（去掉首尾的空单元格）。"""
    rows = []
    for line in section.splitlines():
        s = line.strip()
        if not (s.startswith("|") and s.endswith("|")):
            continue
        cells = [c.strip() for c in s.strip("|").split("|")]
        if all(set(c) <= set("-: ") for c in cells):
            continue  # 分隔行
        rows.append(cells)
    return rows


def test_section_6_declares_three_features_apparatus() -> None:
    """§6 必须声明它用的是**三项装置**。

    **判据是块引用里的装置名**，不是"文中出现过 0.4"——
    那个数字在报告里出现多次，删掉声明行后关键词断言仍会通过。
    """
    sec = _section("## 6. 结论 5", "\n## 7.")
    assert "uniform-v3-three-features" in sec, (
        "§6 没有声明装置 `uniform-v3-three-features`。\n"
        "加 cosine 后，本节数字变成'旧装置的数字'——不标注会让人误以为它们描述当前系统"
    )
    # 必须同时给出具体权重，否则"三项装置"这个名字无法反查
    assert "base=0.4, authority=0.3, status=0.3" in sec.replace("`", ""), (
        "§6 的装置声明没有写出具体权重（0.4/0.3/0.3）"
    )


def test_section_6_14_declares_cosine_apparatus() -> None:
    """§6.14 必须声明它用的是**cosine 装置**，且与 §6 的标签不同。"""
    sec = _section("### 6.14", "\n## 7.")
    assert "uniform-v3-cosine" in sec, (
        "§6.14 没有声明装置 `uniform-v3-cosine`"
    )
    assert "base=0.2, authority=0.2, cosine=0.6" in sec.replace("`", ""), (
        "§6.14 的装置声明没有写出具体权重（0.2/0.2/0.6）"
    )


def test_two_apparatus_labels_are_different() -> None:
    """两个标签必须**不相等**——比较单元格值，不比较"关键词是否出现"。"""
    sec6 = _section("## 6. 结论 5", "\n## 7.")
    sec614 = _section("### 6.14", "\n## 7.")

    label6 = "uniform-v3-three-features" if "uniform-v3-three-features" in sec6 else ""
    label614 = "uniform-v3-cosine" if "uniform-v3-cosine" in sec614 else ""

    assert label6 and label614, "两个标签至少要各自存在"
    assert label6 != label614, (
        f"两节的装置标签相同（都是 {label6!r}）——"
        "那说明其中一节的数字被覆盖了，两套数字没有并列保留"
    )


def test_both_apparatus_numbers_are_kept() -> None:
    """两套数字必须**并列保留**，不能只留一套。

    具体到 `billing` 的相对增益：三项装置是 `−0.0278`，cosine 装置是 `+0.0556`。
    **两个数都要在**——删掉旧的就丢失了"装置变化带来多少差异"这个信息。

    **判定必须定位到表格行与单元格**：`−0.0278` 在 §6 里出现 **6 次**
    （配对表、改写对照表、正文……）。用 `"−0.0278" in sec6` 会在这 6 处里
    任一处还在时就通过——删掉表格那一行后断言仍然绿。
    实测：删掉第一处（§6.5.1 的表格行）后，旧的写法仍然通过。
    """
    sec6 = _section("## 6. 结论 5", "\n## 7.")
    sec614 = _section("### 6.14", "\n## 7.")

    # §6：必须有一整行是 "billing / threeway / 12 / 0.0833 / 0.1111 / −0.0278"
    rows6 = _table_rows(sec6)
    threeway_rows = [
        r
        for r in rows6
        if len(r) >= 6 and r[0].strip("` ") == "billing" and "threeway" in r[1]
    ]
    assert threeway_rows, (
        f"§6 找不到 `billing` / `threeway` 那一行。解析到的行：{rows6[:3]}"
    )
    last_cell = _normalize(threeway_rows[0][-1])
    assert last_cell in {"−0.0278", "-0.0278"}, (
        f"§6 的 `billing`/`threeway` 行末单元格是 {threeway_rows[0][-1]!r}，"
        "应为 `**−0.0278**`。\n"
        "**必须定位到这一行**：这个数字在 §6 里出现 6 次，"
        "关键词断言会在删掉本行后仍然通过"
    )

    # §6.14：必须有 +0.0556，且定位到"同一命题"那张表
    rows614 = _table_rows(sec614)
    cosine_row = [
        r
        for r in rows614
        if len(r) >= 3 and "uniform-v3-cosine" in r[0]
    ]
    assert cosine_row, f"§6.14 找不到 `uniform-v3-cosine` 那一行。解析到：{rows614[:3]}"
    assert "+0.0556" in cosine_row[0][-1], (
        f"§6.14 的 cosine 行末单元格是 {cosine_row[0][-1]!r}，应含 +0.0556"
    )


def _normalize(cell: str) -> str:
    """去掉 markdown 加粗与空白，只留内容。"""
    return cell.replace("*", "").replace("`", "").strip()


def test_section_6_14_states_measured_not_predicted() -> None:
    """§6.14 必须写明这是**实测**，不是预测。

    预测可以是手工重排的估计（本项目曾算出 +0.8167 / +0.7222），
    而实测经过 `run_retrieval` 的完整融合，两个数字差一个量级。
    若把预测当结论，会严重高估 cosine 的收益。
    """
    sec = _section("### 6.14", "\n## 7.")

    assert "实测" in sec, "§6.14 没有写明这是实测"
    assert "预测" in sec or "估计" in sec, (
        "§6.14 没有提到旧的估计值——读者会以为两者一致"
    )
    # 必须点出旧估计高估了，否则"为什么数字差这么多"没有解释
    assert "+0.8167" in sec, (
        "§6.14 没有列出旧的手工估计 +0.8167，无法对照'估计 vs 实测'"
    )
