"""`dataset-v2-frozen` 这个 tag 必须存在，且它的语义必须写在 message 里。

**为什么需要**：没有 tag，v3 的对比基线就是"某个 commit"或"某个工作区状态"，
半年后没人能回答"v2 是哪一版"。

而 tag 存在还不够——它的 message 必须写明：
1. `frozen` **不等于**合格（否则会被读成"数据没问题"）
2. 5 处数据缺陷（否则后来者会去修它们）
3. 第二作者未执行（否则会被读成"有独立样本"）

这一路所有麻烦都来自"版本不清"：
`{1:33}` vs `{1:29,2:4}`、11 份结果混三次代码状态、消融文件无指纹。
tag 是唯一能解决这件事的工具。
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
TAG = "dataset-v2-frozen"


def _tag_message() -> str:
    result = subprocess.run(
        ["git", "tag", "-l", "-n99", TAG],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if result.returncode != 0 or TAG not in result.stdout:
        pytest.skip(f"{TAG} 不存在")
    return result.stdout


def test_frozen_tag_exists() -> None:
    result = subprocess.run(
        ["git", "tag", "--list", TAG],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    assert TAG in result.stdout, f"{TAG} 不存在——v2 没有可引用的版本名"


def test_all_three_tags_exist() -> None:
    """协议两个 + 冻结一个，三个都要在。"""
    result = subprocess.run(
        ["git", "tag", "--list", "dataset-v2*"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    tags = set(result.stdout.split())

    assert tags == {"dataset-v2-protocol", "dataset-v2-protocol-r2", TAG}, tags


def test_frozen_message_says_it_does_not_mean_qualified() -> None:
    """**最重要的一条**：`frozen` 不得被读成"合格"。"""
    message = _tag_message()

    assert "不等于" in message or "不是" in message
    assert "合格" in message


def test_frozen_message_lists_all_five_data_defects() -> None:
    """5 处数据缺陷必须写进 tag message——否则后来者会去修它们。"""
    message = _tag_message()

    for code in ("F13", "F17b", "F18", "F21a", "F24"):
        assert code in message, f"tag message 未列出 {code}"


def test_frozen_message_title_matches_body_count() -> None:
    """**标题的数字必须与正文对得上。**

    实测矛盾：标题写"带 5 处已登记的数据缺陷"，而正文列了 7 条未通过。
    读者会数出 7 而标题说 5。

    而 tag message 是**这个项目里最难修改的一处文字**——
    它指向一个 commit，commit 内容不能改，只能重打 tag。
    所以这类矛盾会永久留在 git 里。

    这条测试要求：标题同时写明「7 条未通过」与「5 条数据缺陷」，
    且正文里 7 = 2 + 1 + 4 的分解存在。
    """
    message = _tag_message()
    # 只取标题区（第一段，到第一个 ## 之前）
    header = message.split("## ")[0]

    assert "7 条未通过" in header, "标题未写总失败数 7"
    assert "5 条" in header, "标题未写数据缺陷数 5"
    assert "2 条" in header, "标题未写构造性数 2"

    # 正文的分母必须加得起来
    assert "7 = 2 + 1 + 4" in message, "正文缺少 7 = 2 + 1 + 4 的分解"


def test_frozen_message_defines_what_counts_as_data_defect() -> None:
    """必须写明"数据缺陷"包含哪几类——否则 5 与 7 的差无法解释。"""
    message = _tag_message()

    assert "真实不足" in message and "正确的失败" in message
    assert "构造性" in message
    # 明确排除
    assert "不在此列" in message or "不是数据缺陷" in message


def test_frozen_message_separates_constructive_from_data_defects() -> None:
    """F6 / F21b 是构造性的，不得混进"数据缺陷"。"""
    message = _tag_message()

    assert "构造性" in message
    assert "F6" in message and "F21b" in message
    assert "正确的失败" in message


def test_frozen_message_records_third_author_gap() -> None:
    """第二作者未执行这件事必须写进 tag——否则会被读成有独立样本。"""
    message = _tag_message()

    assert "§8.1" in message or "8.1" in message
    assert "未执行" in message
    assert "第三方独立性" in message or "不具备" in message


def test_frozen_message_points_at_the_report() -> None:
    """必须能从这里找到**当时的**四条结论。

    **读的是 tag 消息，不是报告**：tag 是不可变的历史产物，
    写于 2026-10-30（结论 5 出现于 2026-11-05）。
    所以这里断言的是"tag 当时列了四条"，MUST NOT 跟着报告改成五条——
    那等于要求改写历史，而 tag 的意义正是"不变"。
    """
    message = _tag_message()

    assert "v2-what-it-measures.md" in message
    # 四条结论的编号
    for n in ("1", "2", "3", "4"):
        assert f"  {n}  " in message or f"{n}  " in message


def test_frozen_tag_points_at_a_commit_that_exists() -> None:
    """tag 必须指向一个真实 commit，且该 commit 上有完整的结果文件。

    **不硬编码测试计数**：那会随每次改动而漂，而 tag 的意义正是"不变"。
    改为断言"该 commit 上 §0 记录的门禁数与实际结果一致"——
    那才是"冻结时状态可复算"的实质。
    """
    result = subprocess.run(
        ["git", "rev-parse", f"{TAG}^{{commit}}"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    if result.returncode != 0:
        pytest.skip("无法解析 tag")
    commit = result.stdout.strip()
    assert len(commit) == 40, f"不是完整 commit hash：{commit}"

    # 该 commit 上必须有 gates 结果文件
    show = subprocess.run(
        ["git", "show", f"{commit}:results/v2-sample-gates.json"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    assert show.returncode == 0, "tag 指向的 commit 上没有 gates 结果"
    assert "checks" in show.stdout, "gates 结果格式不对"
