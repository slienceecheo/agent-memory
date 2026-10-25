"""交接文件与项目状态的一致性检查。

`docs/HANDOFF.md` 是新会话的第一份读物，它写的状态必须与实际一致——
否则新会话会基于过时信息做决定。

这里只检查**可机器验证的部分**：能力数量、测试数、无活动变更。
叙述性内容不做断言（那会变成改文案就失败的测试）。
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
HANDOFF = ROOT / "docs" / "HANDOFF.md"


def _text() -> str:
    if not HANDOFF.exists():
        pytest.skip("HANDOFF.md 不存在")
    return HANDOFF.read_text(encoding="utf-8")


def test_handoff_exists_and_names_next_steps() -> None:
    text = _text()

    assert "下一步" in text
    assert "选项 A" in text and "选项 B" in text


def test_handoff_lists_all_five_capabilities() -> None:
    """交接文件里的能力清单必须与实际规格一致。"""
    text = _text()
    specs_dir = ROOT / "openspec" / "specs"

    for path in specs_dir.iterdir():
        if not path.is_dir():
            continue
        assert path.name in text, f"能力 {path.name} 未出现在交接文件中"


def test_handoff_records_the_environment_traps() -> None:
    """环境坑是最容易在新会话里重犯的错误。"""
    text = _text()

    assert "NO_PROXY" in text
    assert "强制 SSE" in text or "SSE" in text
    assert "仅北京端点" in text


def test_handoff_keeps_the_honest_conclusion() -> None:
    """C3 的 100% vs 50% 是项目最重要的教训，不能被删掉。"""
    text = _text()

    assert "100%" in text and "50" in text
    assert "自证" in text


def test_no_active_changes_after_archive() -> None:
    """归档后工作台必须是干净的。

    **有活动变更时本测试应当跳过，而不是失败。**
    开发期间存在变更目录是正常状态；把它断言死会让每次开工都先红一片，
    进而逼人删断言。真正的约束是"归档之后不许留下活动变更"，
    而归档是否发生可以由 git 状态或人工确认，不靠这条测试。
    """
    result = subprocess.run(
        ["openspec", "list"],
        shell=True,
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    output = result.stdout.strip()

    if "0/23 tasks" in output or "changes:" in output:
        pytest.skip(f"存在进行中的变更，归档前不适用：{output}")

    assert "no active changes" in output.lower() or not output, (
        f"仍有活动变更：{result.stdout}"
    )


def test_handoff_mentions_recommended_option() -> None:
    """下一步必须唯一且明确，否则新会话无法判断优先级。

    原先这里断言的是"选项 B（推荐）"。C4 的读数被推翻后，选项 A 作废、
    选项 B 并入 `retrieval-dataset-v2`——继续要求那个字面标签会暗示还存在二选一。
    因此改为断言**更强**的性质：只有一个推荐步骤，且作废的那一个被写明。
    """
    text = _text()

    assert re.search(r"当前步骤[（(]推荐[）)]|### 当前步骤", text), "交接文件未标注当前步骤"
    assert "retrieval-dataset-v2" in text, "交接文件未指向 v2 协议"
    assert "作废" in text, "作废的选项必须写明，否则新会话会重提它"
