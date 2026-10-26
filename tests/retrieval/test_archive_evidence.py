"""归档证据锁定（`evidence_lock`）。

**与 `locked_defect` 的区别**：

| 标记 | 锁什么 | 什么时候该红 |
|---|---|---|
| `locked_defect` | 当前代码里的缺陷 | 缺陷修好时（翻面） |
| `evidence_lock` | git 归档里的历史数字 | **只有一种情况：git 历史被改写** |

所以本文件的测试**必须从 `git show <rev>:<path>` 读取**，不能 `open()` 工作区文件。
这一轮踩过的坑正是这个：`open()` 读到的是未提交的工作区状态，
而 `git show` 读到的是归档——两者被当成同一个实验比较了四轮。

**Windows 上的一个真实陷阱**：`git show rev:path` 的路径分隔符必须是 `/`，
用 `\\` 会报 `path exists on disk, but not in '<rev>'`（实测）。
"""

from __future__ import annotations

import json
import subprocess
from collections import Counter
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]

#: C4 归档的 commit。它是"接三路之前"的最后一版。
C4_ARCHIVE = "c4b3152"


def load_from_git(rev: str, path: str) -> dict[str, object]:
    """从 git 对象库读 JSON，**不走文件系统**。

    `path` 必须用正斜杠：Windows 上传反斜杠会失败。
    """
    if "\\" in path:
        raise ValueError(
            f"git show 的路径必须用正斜杠，收到 {path!r}；"
            "Windows 上反斜杠会报 'exists on disk, but not in <rev>'"
        )
    result = subprocess.run(
        ["git", "show", f"{rev}:{path}"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    if result.returncode != 0:
        pytest.fail(
            f"读不到 {rev}:{path}。"
            f"只有两种可能：git 历史被改写，或路径写错。\n"
            f"stderr: {result.stderr.strip()}"
        )
    return json.loads(result.stdout)


def _rank_histogram(payload: dict[str, object]) -> dict[int, int]:
    per_case = payload["per_case"]  # type: ignore[index]
    ranked = [
        c["rank_after_fusion"]  # type: ignore[index]
        for c in per_case
        if c.get("has_gold") and not c.get("skipped")  # type: ignore[union-attr]
    ]
    return dict(Counter(ranked))


@pytest.mark.evidence_lock
@pytest.mark.parametrize(
    ("split", "expected_rank", "expected_pool"),
    [
        ("dev", {1: 33}, {14: 33}),
        ("test", {1: 17}, {14: 7, 15: 10}),
        ("independent", {1: 26}, {15: 26}),
    ],
)
def test_archive_rank_after_fusion(
    split: str, expected_rank: dict[int, int], expected_pool: dict[int, int]
) -> None:
    """C4 归档里 gold 全部排第 1，而池有 14–15 条。

    这是「池从未进入融合」的**唯一直接证据**。
    若本条变红，唯一可能的原因是 `c4b3152` 的内容被改写——
    请先 `git cat-file -p c4b3152` 核对，不要改本测试。
    """
    payload = load_from_git(
        C4_ARCHIVE, f"results/retrieval-{split}-uniform-nodedup-poolunrelated.json"
    )

    assert _rank_histogram(payload) == expected_rank, (
        f"{split} 的 rank_after_fusion 变了：{_rank_histogram(payload)}。"
        "只有一种可能：git 历史被改写。请先核对 commit，不要直接改本测试。"
    )
    pool_sizes = dict(
        Counter(
            c["pool_size"]  # type: ignore[index]
            for c in payload["per_case"]  # type: ignore[index]
            if c.get("has_gold") and not c.get("skipped")  # type: ignore[union-attr]
        )
    )
    assert pool_sizes == expected_pool


@pytest.mark.evidence_lock
def test_archive_has_no_path_observability() -> None:
    """C4 归档没有 `paths_enabled` 字段——那时还没有路径观测。

    这条解释了为什么"默认参数重跑"会污染它：
    防护按 `paths_enabled` 判断，而归档没有这个字段（视为未知），
    所以任何一次带路径信息的重跑都算"不同实验"。
    """
    payload = load_from_git(
        C4_ARCHIVE, "results/retrieval-dev-uniform-nodedup-poolunrelated.json"
    )

    assert payload.get("paths_enabled") is None, (
        "归档开始记录 paths_enabled 了；请更新缺陷 12 的说明"
    )
    assert payload["run_count"] == 1


@pytest.mark.evidence_lock
def test_archive_pool_never_reached_fusion() -> None:
    """池里有候选，但融合排名宽度远小于池。

    C4 归档 `rank_after_fusion` 最大为 1，池有 14 条。
    所以池里 13 条从未参与排序——这是"池难度从未成立"的算术依据。
    """
    payload = load_from_git(
        C4_ARCHIVE, "results/retrieval-dev-uniform-nodedup-poolunrelated.json"
    )
    histogram = _rank_histogram(payload)
    pool_sizes = {
        c["pool_size"]  # type: ignore[index]
        for c in payload["per_case"]  # type: ignore[index]
        if c.get("has_gold") and not c.get("skipped")  # type: ignore[union-attr]
    }

    assert max(histogram) == 1
    assert max(pool_sizes) == 14
    assert max(pool_sizes) - max(histogram) == 13


@pytest.mark.evidence_lock
def test_git_show_rejects_backslash() -> None:
    """Windows 陷阱：`git show` 的路径必须用正斜杠。

    实测反斜杠会报 `path exists on disk, but not in '<rev>'`——
    那个报错看起来像"文件不在归档里"，而不是"路径分隔符错了"。
    """
    with pytest.raises(ValueError, match="正斜杠"):
        load_from_git(C4_ARCHIVE, "results\\retrieval-dev-uniform-nodedup-poolunrelated.json")


@pytest.mark.integrity_check
def test_working_archive_is_not_polluted() -> None:
    """工作区的归档文件未被覆盖。

    **这条不是 `evidence_lock`，是 `integrity_check`。**

    两者的失败动作不同：

    | 类型 | 红的原因 | 该做什么 |
    |---|---|---|
    | `evidence_lock` | git 历史被改写 | 核对 commit，不要改测试 |
    | `integrity_check` | 工作区文件被覆盖 | `git checkout` 还原 |

    原先它被标成 `evidence_lock` 并断言"工作区 == 归档"，
    这会**禁止任何默认参数的实验**：一旦重跑，本条就红，
    而红的原因不是代码错，是"归档被覆盖"这个已知问题又发生了一次。
    那会把"守护归档"变成"禁止跑实验"。

    正确语义：先检测污染（是本条），再断言归档数字（是那 6 条 evidence_lock）。

    用 JSON 语义比对而不是文本 diff：行尾 CRLF/LF 会让文本 diff 误报
    （实测还原后 `arch == cur` 为 True，但字符串比对接。
    """
    path = "results/retrieval-dev-uniform-nodedup-poolunrelated.json"
    archived = load_from_git(C4_ARCHIVE, path)
    current = json.loads((ROOT / path).read_text(encoding="utf-8"))

    if current != archived:
        pytest.fail(
            "工作区的 C4 归档文件已被覆盖——这不是代码缺陷，是数据污染。\n"
            "修复动作：\n"
            f"  git show {C4_ARCHIVE}:{path} > {path}\n"
            "  然后把 retrieval-run-count.json 里对应的计数改回 1。\n"
            "不要改本测试：它检测的是文件状态，不是行为。"
        )
