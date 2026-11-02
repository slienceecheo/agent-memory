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

import pytest

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
    if not ARCHIVE.exists():
        pytest.skip("还没有归档变更")

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
    if not archived:
        pytest.skip("还没有归档变更")
    text = archived[0].read_text(encoding="utf-8")
    done = len(re.findall(r"^\s*-\s*\[x\]", text, re.M))
    assert done > 0, f"{archived[0]} 读不到任何已勾任务——正则或文件格式变了"


def test_active_changes_are_not_checked_by_this_gate() -> None:
    """**边界确认**：进行中的变更允许有未勾任务，本门禁不查它。

    若把判据套到 `changes/`（进行中）上，任何刚建的变更都会红，
    于是人会去加 `xfail` 或放宽断言——**门禁就消失了**。

    **这条用"行为"验证边界，不扫描源码**：
    上一版扫描自身源码找 `_unchecked(ACTIVE`，而那段字符串就写在测试自己文件里，
    **自指**——它永远红。改为直接断言"归档集与活动集不相交"，且活动集当前为空。
    """
    archived = {d.name for d in ARCHIVE.iterdir() if d.is_dir()} if ARCHIVE.exists() else set()
    # `archive/` 自身是归档根，不是活动变更
    active = {
        d.name
        for d in ACTIVE.iterdir()
        if d.is_dir() and d.name != "archive"
    } if ACTIVE.exists() else set()

    # 两个集合不相交：归档是"完成"，活动是"进行中"
    assert not (archived & active), f"同名目录同时在活动与归档里：{archived & active}"

    # 活动集当前为空——本门禁只对归档成立，所以此刻它不约束任何东西
    assert active == set(), (
        f"有进行中的变更：{sorted(active)}。"
        "本门禁只查归档目录，不查它们——这是设计边界，不是遗漏。"
    )
