"""HANDOFF 的"坏断言形态"表必须完整，且 `CAPABILITIES` 不得漂移。

## 为什么需要这个文件

**两件事都刚发生过，而且都是"没有断言守着"的形态：**

1. `test_adjacency_returns_only_active` 覆盖范围被高估
   —— 删掉 Python 二次过滤仍绿，但名字让人以为覆盖整条链
2. `CAPABILITIES` 漏掉 `retrieval-apparatus`
   —— 那个测试的 docstring 里写死的数字既不是当前 5 个能力的和，
   也不是全部，而且没有断言守着

**所以本文件做两件事**：
- 断言 HANDOFF 记录了**五种**形态（不只四种）
- 断言 `CAPABILITIES` 与 `openspec/specs/` 一致（已在
  `test_spec_normative_words.py` 里，这里只做交叉引用）
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
HANDOFF = ROOT / "docs" / "HANDOFF.md"
SPECS = ROOT / "openspec" / "specs"


def _text() -> str:
    if not HANDOFF.exists():
        pytest.skip("HANDOFF 缺失")
    return HANDOFF.read_text(encoding="utf-8")


def _section() -> str:
    """取"坏断言的五种形态"这一节，**含它的平级子节**。

    **边界是下一个 `## `（二级标题）**，不是下一个 `### `：
    `### 第五种` 与 `### 顺带发现` 都是 `###` 级，与本节平级。
    若用 `###` 作边界，会只切到表格结束——而第五种与漂移案例都在后面。
    """
    text = _text()
    marker = "### 坏断言的"
    assert marker in text, "HANDOFF 里找不到「坏断言的……形态」这一节"
    start = text.index(marker)
    rest = text[start:]
    m = re.search(r"\n## ", rest[4:])
    return rest if m is None else rest[: m.start() + 4]


def test_handoff_lists_five_assertion_forms() -> None:
    """**HANDOFF 必须记录五种坏断言形态，且标题与表格一致。**

    第五种（覆盖范围被高估）是 `recall-active-only-contract` 归档时
    实测发现的，而它此前不在表里。

    **若表里只有四种**，下一个人不会知道"断言正确但覆盖不全"
    也是一种需要专门检查的缺陷。

    **标题与表格必须同步**：标题写"四种"而表里有 5 行，
    是"数字没有断言守着"的另一个实例。
    """
    section = _section()

    # 表格必须有 1–5 五行
    for n in ("1", "2", "3", "4", "5"):
        pattern = rf"^\| {n} \|"
        assert re.search(pattern, section, re.MULTILINE), (
            f"HANDOFF 的形态表缺少第 {n} 行"
        )

    # 五行的"形态"列必须各不相同
    rows = re.findall(r"^\| (\d) \| ([^|]+) \|", section, re.MULTILINE)
    forms = {n: name.strip() for n, name in rows}
    assert len(forms) == 5, f"形态表只有 {len(forms)} 行：{sorted(forms)}"
    assert len(set(forms.values())) == 5, (
        f"形态表有重复的行：{forms}"
    )

    # **标题里的数字必须与表格行数一致**
    m = re.search(r"### 坏断言的(.{1,8}?)形态", section)
    assert m, "找不到本节标题"
    title_part = m.group(1)
    zh = {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6}
    declared = next((zh[c] for c in title_part if c in zh), None)
    assert declared == 5, (
        f"标题写的是「{title_part}形态」，而表里有 5 行。\n"
        "标题里的数字也必须跟着改——否则它又是一个没有断言守着的数字。"
    )


def test_handoff_has_the_overestimated_coverage_form() -> None:
    """**第五种形态必须是"覆盖范围被高估"，且带实测对照表。**

    光有名字不够：要给出"删掉哪一层、哪条断言红不红"的实测。

    **判据定位到那张对照表**：`行为断言` 在段落里出现 4 次，
    用 `"行为断言" in section` 会在删掉表格后仍然通过。
    """
    section = _section()

    assert "覆盖范围" in section, (
        "第五种形态的名称必须含「覆盖范围」"
    )

    rows = [
        ln.strip() for ln in section.splitlines() if ln.strip().startswith("|")
    ]
    vector_row = [r for r in rows if "vector.py" in r]
    adjacency_row = [r for r in rows if "adjacency.py" in r]

    assert vector_row, "第五种的对照表缺少 `vector.py` 那一行"
    assert adjacency_row, "第五种的对照表缺少 `adjacency.py` 那一行"

    def cells_of(row: str) -> list[str]:
        """取表格行的单元格，去掉加粗标记。

        **不依赖具体措辞**：`绿/红` 与 `通过/失败` 都能比。
        """
        return [
            c.strip().replace("*", "").strip()
            for c in row.strip("|").split("|")
        ]

    # vector：删掉后行为断言与源码断言**结论相同**（都红）
    v = cells_of(vector_row[0])
    assert len(v) == 3, f"`vector.py` 那行应有 3 列，实际 {v}"
    assert v[1] == v[2], (
        f"`vector.py` 那行两列结果应相同（删掉 SQL 后两者都失败）：{v}"
    )

    # adjacency：删掉后行为断言与源码断言**结论不同**
    a = cells_of(adjacency_row[0])
    assert len(a) == 3, f"`adjacency.py` 那行应有 3 列，实际 {a}"
    assert a[1] != a[2], (
        f"`adjacency.py` 那行两列结果不应相同：{a}\n"
        "**这个差异就是'覆盖范围被高估'的证据**：行为断言没覆盖到那层。"
    )

    # 必须指出发现方式
    assert "删掉" in section, (
        "第五种形态必须说明发现方式（把链路的另一层单独删掉）"
    )


def test_handoff_warns_about_handwritten_lists_drifting() -> None:
    """**HANDOFF 必须记录"手写清单会漂移"及其后果。**

    `CAPABILITIES` 漏了 `retrieval-apparatus`，导致那个测试数的
    Scenario 数既不是 5 个能力的和，也不是全部。

    **判据定位到修法那两条**：`手写` 在段落里出现 2 次。
    """
    section = _section()

    assert "CAPABILITIES" in section, (
        "必须记录 `CAPABILITIES` 漂移这个案例"
    )
    assert "retrieval-apparatus" in section, (
        "必须点名漏掉的那个能力"
    )

    # 修法必须同时列出两条
    m = re.search(r"\*\*修法两条\*\*|修法两条", section)
    assert m, "必须有一段「修法两条」"
    tail = section[m.start() :]
    assert "CAPABILITIES" in tail and "所有能力" in tail, (
        "修法第 1 条必须是「断言 CAPABILITIES 覆盖所有能力」"
    )
    assert "docstring" in tail and "不写" in tail, (
        "修法第 2 条必须是「docstring 里不写具体数字」"
    )


def test_handoff_says_not_to_hardcode_numbers_in_docstrings() -> None:
    """**必须写明 docstring 里不写具体数字。**

    写死的数字没有断言守着，每次归档都会变成错的。

    **判据是那条禁令本身**，不是 `"docstring" in section` ——
    它在段落里出现 2 次。
    """
    section = _section()
    assert "**docstring 里不写具体数字**" in section, (
        "必须有一条明确的禁令：「docstring 里不写具体数字」"
    )
    flat = section.replace("\n", "")
    assert "没有断言守着" in flat or "没有任何断言" in flat, (
        "必须说明为什么不能写——写死的数字没有断言守着"
    )


# ---------- 交叉验证：CAPABILITIES 与 specs 一致 ----------


def test_capabilities_covers_all_specs() -> None:
    """**`CAPABILITIES` 必须覆盖所有有 spec 的能力。**

    这条与 `test_spec_normative_words.py::test_capabilities_list_covers_all_existing_specs`
    重复——**但本文件读的是"另一个角度"**：
    那条断言在 `test_spec_normative_words.py` 内部，若有人删掉它，
    这里仍会红。

    **为什么值得重复**：`CAPABILITIES` 漂移过一次，而那次没人发现，
    因为唯一的"覆盖检查"不存在。多一条守住它，代价很小。
    """
    from tests.test_spec_normative_words import CAPABILITIES

    existing = {
        d.name
        for d in SPECS.iterdir()
        if d.is_dir() and (d / "spec.md").exists()
    }
    listed = set(CAPABILITIES)

    assert listed == existing, (
        f"CAPABILITIES 与 specs 不一致。\n"
        f"  有 spec 但没列：{sorted(existing - listed)}\n"
        f"  列了但没 spec：{sorted(listed - existing)}"
    )
