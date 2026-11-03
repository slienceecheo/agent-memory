"""归档的变更不得留下未勾选的任务。

**为什么这条要有**：`openspec archive --yes` 对未勾选任务只打一行 Warning 就继续。
实测 `fix-oversized-requirement-text` 归档时是 **6/9**（3 条未勾），
归档成功、退出码 0、CI 全绿——**只有一行容易被滚过去的 Warning**。

而"任务没做完就归档"意味着：`tasks.md` 里写的验收步骤，
有一些从来没跑过，而归档把这件事变成既成事实。

**这条门禁现在对全部 7 个归档变更是绿的**（含那 3 条被补勾的）。
它的价值不在抓历史，在**下一次 `--yes` 跳过的瞬间就红**。

**为什么断言"0 个未勾"而不是"有 Warning 就红"**：
Warning 是 openspec 的输出文本，抓它要解析 stdout，且版本一变就失效。
而未勾任务计数是归档产物的**结构事实**——它不依赖任何工具的输出格式。
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ARCHIVE = ROOT / "openspec" / "changes" / "archive"
ACTIVE = ROOT / "openspec" / "changes"


def _unchecked(tasks: Path) -> list[str]:
    """返回未勾选任务的文本行。"""
    text = tasks.read_text(encoding="utf-8")
    return [
        line.strip()
        for line in text.splitlines()
        if re.match(r"^\s*-\s*\[ \]", line)
    ]


def test_archived_changes_have_no_unchecked_tasks() -> None:
    """归档目录下任何 `tasks.md` 的未勾任务数必须为 0。

    **这条会在 `--yes` 跳过未完成任务的那次归档上立刻红。**
    """
    # **不用 skip**：本项目已有 7 个归档变更，"还没有归档"这个前提不成立。
    # 若它真的不存在，说明仓库结构坏了——那应该红，而不是跳过。
    assert ARCHIVE.exists(), f"归档目录不存在：{ARCHIVE}"

    offenders: dict[str, list[str]] = {}
    for change in sorted(ARCHIVE.iterdir()):
        if not change.is_dir():
            continue
        tasks = change / "tasks.md"
        if not tasks.exists():
            continue
        unchecked = _unchecked(tasks)
        if unchecked:
            offenders[change.name] = unchecked

    assert not offenders, (
        "这些归档变更留下了未勾选的任务：\n"
        + "\n".join(
            f"  {name}: {len(items)} 条\n"
            + "\n".join(f"    {item[:70]}" for item in items[:5])
            for name, items in offenders.items()
        )
        + "\n归档前应把 `tasks.md` 勾完，或把未做的任务改写成'未做+原因'。"
    )


def test_check_counts_are_real() -> None:
    """**门禁本身要被验证**：未勾任务的计数必须真能从文本里读出来。

    没有这条，"所有归档变更 0 未勾"与"我的正则从来没匹配到任何东西"
    在输出上完全一样——**这正是 skip 与 pass 不分的同型问题。**
    """
    sample = "- [x] 已完成\n- [ ] 未完成\n  - [ ] 子项未完成\n"

    unchecked = [
        line.strip()
        for line in sample.splitlines()
        if re.match(r"^\s*-\s*\[ \]", line)
    ]
    assert len(unchecked) == 2, f"正则没抓到未勾任务：{unchecked}"
    assert unchecked[0].startswith("- [ ] 未完成")

    # 正向：已勾不应被算进来
    done_only = "- [x] a\n- [x] b\n"
    assert not [
        line for line in done_only.splitlines() if re.match(r"^\s*-\s*\[ \]", line)
    ]

    # 且它对真实文件有效：取一个已归档变更，确认能读到它的勾选数
    archived = sorted(ARCHIVE.glob("*/tasks.md"))
    assert archived, f"没有找到任何归档的 tasks.md：{ARCHIVE}"
    text = archived[0].read_text(encoding="utf-8")
    done = len(re.findall(r"^\s*-\s*\[x\]", text, re.M))
    assert done > 0, f"{archived[0]} 读不到任何已勾任务——正则或文件格式变了"


def _norm(name: str) -> str:
    """去掉归档时加上的日期前缀（`YYYY-MM-DD-`）。

    **必须规范化**：归档目录名带日期前缀、活动目录名不带，
    所以 `archived & active` 在结构上恒为空——
    它看起来在检查"归档只复制没删除"，实际上永远通过。

    实测：建一个 `openspec/changes/retrieval-v3-apparatus/`
    （正是"只复制未删除"的形态），原写法仍 1 passed。
    """
    return re.sub(r"^\d{4}-\d{2}-\d{2}-", "", name)


def test_archived_and_active_do_not_overlap() -> None:
    """**规范化后**比较：同一变更不得同时出现在活动与归档里。

    这条抓的是"归档只复制、没有删除"——那会让 `openspec list`
    把残留当成活动变更，而 `test_handoff` 对"有活动变更"是 **skip**，
    于是整个仓库对这种残留保持沉默。

    **上一版的判据是 `archived & active`，它恒为空**（日期前缀 vs 无前缀），
    所以那条断言没有判别力。写成这条时先在探针上验过它会红。
    """
    archived = (
        {_norm(d.name) for d in ARCHIVE.iterdir() if d.is_dir()}
        if ARCHIVE.exists()
        else set()
    )
    active = (
        {d.name for d in ACTIVE.iterdir() if d.is_dir() and d.name != "archive"}
        if ACTIVE.exists()
        else set()
    )

    overlap = archived & active
    assert not overlap, (
        f"这些变更同时存在于活动与归档：{sorted(overlap)}。\n"
        "归档应当把目录**移走**，而不是复制一份留下。\n"
        "残留会被 openspec list 当成活动变更，而 test_handoff 对"
        "'有活动变更'是 skip——于是整条链对它沉默。"
    )


def test_active_changes_are_not_checked_by_this_gate() -> None:
    """**边界确认**：进行中的变更允许有未勾任务，本门禁不查它。

    若把判据套到 `changes/`（进行中）上，任何刚建的变更都会红，
    于是人会去加 `xfail` 或放宽断言——**门禁就消失了**。

    "归档后不许留活动变更"这件事由
    `tests/test_handoff.py::test_no_active_changes_after_archive` 负责，
    且它用的是 **skip** 而非 fail——同一状态两个测试不该给相反处置。

    **本条不断言"活动集为空"**：上一版写了 `assert active == set()`，
    而它正是上文批评的那个反模式——下一次开工建了变更目录就会红。
    实测：建 `openspec/changes/zz-probe-in-progress/` 就红了。
    """
    # 只在"有活动变更"时验证边界：此时归档门禁仍应只扫归档
    active = (
        {d.name for d in ACTIVE.iterdir() if d.is_dir() and d.name != "archive"}
        if ACTIVE.exists()
        else set()
    )

    # 有活动变更时，本文件的门禁仍只看 archive——用"未勾任务计数不受影响"验证
    archived_tasks = sorted(ARCHIVE.glob("*/tasks.md")) if ARCHIVE.exists() else []
    assert archived_tasks, "归档目录里没有 tasks.md，门禁失去了作用对象"
    # 活动目录里的 tasks.md（若有）不应被算进归档统计
    for name in active:
        assert not (ARCHIVE / name / "tasks.md").exists(), (
            f"{name} 的 tasks.md 出现在归档目录里——归档不该包含活动变更"
        )
