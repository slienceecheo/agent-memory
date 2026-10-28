"""§0.1 变更记录必须与实际 git 历史一致。

**为什么需要这些测试**：我曾在对话里断言"6 次修订全是收紧"，
实测是 5 次收紧 + 1 次放宽；又曾用一个只匹配加粗写法的脚本，
把 tag 时的 11 条门禁数错成 4 条。

两次都是"凭印象描述历史"。这组测试把历史变成可复算的断言，
让报告里的每个数字都能被 `git show` 验证。
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
PROTO = "docs/requirements/retrieval-dataset-v2.md"
TAG = "e6a795a"
SAMPLE = ROOT / "data" / "retrieval-v2" / "sample"

pytestmark = pytest.mark.skipif(
    subprocess.run(
        ["git", "rev-parse", "--is-inside-work-tree"],
        cwd=ROOT,
        capture_output=True,
    ).returncode
    != 0,
    reason="不是 git 仓库",
)


def _show(rev: str, path: str) -> str:
    result = subprocess.run(
        ["git", "show", f"{rev}:{path}"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if result.returncode != 0:
        pytest.skip(f"无法读取 {rev}:{path}")
    return result.stdout


def _gates(text: str) -> set[str]:
    """抽出表格里定义的门禁编号。

    必须同时匹配 `| F1 |` 与 `| **F12** |`——
    只匹配加粗会把 tag 时的 11 条误报成 4 条（真实发生过的 bug）。
    """
    found = set()
    for line in text.splitlines():
        m = re.match(r"\|\s*\**\s*(F\d+[ab]?)\s*\**\s*\|", line.strip())
        if m:
            found.add(m.group(1))
    return found


def test_tag_had_eleven_gates() -> None:
    """tag 时是 F1–F11，不是 4 条。

    我上一轮的审计脚本只匹配 `| **F12** |` 这种加粗写法，
    于是 F1–F7 全被漏掉，得出"tag 时只有 4 个门禁"的错误结论。
    """
    gates = _gates(_show(TAG, PROTO))

    assert len(gates) == 11, f"tag 时实际 {len(gates)} 条：{sorted(gates)}"
    assert {f"F{i}" for i in range(1, 12)} == gates
    # F12 及以上在 tag 时不存在
    assert not {g for g in gates if int(re.sub(r"\D", "", g)) >= 12}


def test_f13_absent_at_tag() -> None:
    """F13 在 tag 时不存在——它是 597cf6a 才出现的。"""
    assert "F13" not in _gates(_show(TAG, PROTO))
    assert "F13" in _gates(_show("597cf6a", PROTO))


def test_f13_denominator_was_undefined_when_introduced() -> None:
    """F13 首次出现时分母未定义，952a55e 才写明是 A 轴查询。

    这是 §0.1.3 的全部依据：一个阈值被调整两次，
    每次都因样例在旧口径下的表现而推动。
    """
    first = _show("597cf6a", PROTO)
    row = next(
        line for line in first.splitlines() if re.match(r"\|\s*\**\s*F13\s*\**\s*\|", line.strip())
    )
    assert "≥ 40%" in row
    assert "A 轴" not in row, "首次出现时不应已指定 A 轴分母"

    later = _show("952a55e", PROTO)
    row2 = next(
        line for line in later.splitlines() if re.match(r"\|\s*\**\s*F13\s*\**\s*\|", line.strip())
    )
    assert "A 轴" in row2, "952a55e 才把分母写成 A 轴查询"


def test_f19_f20_added_after_ablation_result() -> None:
    """F19/F20 与消融结果在同一个 commit（27d0139）。"""
    before = _gates(_show("e91f893", PROTO))
    after = _gates(_show("27d0139", PROTO))

    assert "F19" not in before
    assert "F20" not in before
    assert {"F19", "F20"} <= after


def test_dataset_files_unchanged_since_first_commit() -> None:
    """数据文件只有一个提交，早于任何检索分数。"""
    if not SAMPLE.exists():
        pytest.skip("样例数据集缺失")

    log = subprocess.run(
        ["git", "log", "--oneline", "--", "data/retrieval-v2/sample/"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
    ).stdout.strip().splitlines()

    assert len(log) == 1, f"数据文件被改了 {len(log)} 次：{log}"
    assert log[0].startswith("597cf6a")


def test_protocol_records_the_amendments() -> None:
    """协议里必须有 §0.1，且写明 2 次依据来自样例结果。"""
    text = (ROOT / PROTO).read_text(encoding="utf-8")

    assert "## 0.1 变更记录" in text
    assert "C 与 D 合计 2 次" in text
    assert "provisional" in text

    # 那句错误断言可以出现，但只能作为被反驳的对象——
    # 不能作为协议自己的陈述。
    if "6 次全是收紧" in text:
        assert "实测不成立" in text, "引用了错误断言却没有反驳它"

    # 放宽必须被点名，否则"全部收紧"会以沉默的方式复活
    assert "放宽" in text
    assert "33.3%" in text and "40.0%" in text


def test_f20_documents_its_weak_evidence() -> None:
    """F20 必须写明阈值 0.3 是实测 0.60 的一半，事后设定。"""
    text = (ROOT / PROTO).read_text(encoding="utf-8")

    assert "实测值 0.60 的一半" in text or "实测 0.60 的一半" in text
    assert "n=4" in text
    # 报告必须给实测值，不能只写"通过"
    assert "报告必须给出实测掉幅" in text or "报告必须写实测掉幅" in text
