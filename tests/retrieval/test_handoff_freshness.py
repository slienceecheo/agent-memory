"""HANDOFF 的"更新日期"必须是最后一次归档的日期（tasks 本变更）。

**为什么这条要有**：`docs/HANDOFF.md:3` 的 `更新日期` 是这份文档**唯一的新鲜度标记**。

实测：它写着 `2026-10-30`，而九轮归档改过 HANDOFF 多次，日期一直没更新。
下个会话的人靠这个日期判断"文档有多旧"，会得到错误结论。

**为什么之前没被发现**：没有任何测试断言它。
所以它属于"改了很多次但没人检查"的那一类——和"总数改了、分项没改"是同型。

**判据**：`更新日期` == `openspec/changes/archive/` 下最新的目录名里的日期。

归档目录名格式是 `YYYY-MM-DD-<change-name>`，所以日期可以直接从名字取。
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
HANDOFF = ROOT / "docs" / "HANDOFF.md"
ARCHIVE = ROOT / "openspec" / "changes" / "archive"


def _latest_archive_date() -> str:
    """归档目录里最新的 `YYYY-MM-DD` 前缀。"""
    if not ARCHIVE.exists():
        pytest.skip("还没有归档变更")
    dates = []
    for d in ARCHIVE.iterdir():
        if not d.is_dir():
            continue
        m = re.match(r"^(\d{4}-\d{2}-\d{2})-", d.name)
        if m:
            dates.append(m.group(1))
    assert dates, "归档目录里没有符合 `YYYY-MM-DD-` 前缀的目录"
    return max(dates)


def test_handoff_update_date_matches_latest_archive() -> None:
    """HANDOFF 的更新日期必须等于最后一次归档的日期。

    若某次归档改了 HANDOFF 却忘了改日期，这条会红——
    **而那个红指向的是"新鲜度标记过期"，不是归档本身有问题。**
    """
    text = HANDOFF.read_text(encoding="utf-8")

    m = re.search(r"^> 更新日期：(\d{4}-\d{2}-\d{2})$", text, re.M)
    assert m, "HANDOFF 第 3 行应形如 `> 更新日期：YYYY-MM-DD`"

    declared = m.group(1)
    expected = _latest_archive_date()

    assert declared == expected, (
        f"HANDOFF 写的是 {declared}，而最后一次归档是 {expected}。\n"
        "归档改了文档却没改日期——读者会以为文档更旧。"
    )


def test_update_date_is_not_in_the_future() -> None:
    """日期不得晚于系统当天——防"手写一个未来日期让它一直通过"。

    这条防的是：若有人把日期写成 `2099-01-01`，
    上面那条会一直红（因为归档日期追不上），于是他可能改判据。
    **先在这里拦住"未来日期"这个错误做法。**
    """
    from datetime import date

    text = HANDOFF.read_text(encoding="utf-8")
    m = re.search(r"^> 更新日期：(\d{4}-\d{2}-\d{2})$", text, re.M)
    assert m

    declared = date.fromisoformat(m.group(1))
    assert declared <= date.today(), (
        f"HANDOFF 的更新日期 {declared} 晚于今天 {date.today()}——"
        "未来日期不是新鲜度标记。"
    )
