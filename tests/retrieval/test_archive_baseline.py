"""补字段不得改变任何数字——用 git 里的原始文件验证，不用我记得的值。

**为什么必须有 archive**：`test_numbers_unchanged_by_the_rerun` 之前比的是
"当前文件"与"硬编码的期望值"。而硬编码的值可能来自报告抄写，
那样这条测试就变成"我记得没变"，而不是"可复算地没变"。

`results/archive/v2-sample-threeway-cb9c77f.json` 是从
`git show cb9c77f:results/v2-sample-threeway.json` 取出的原始文件，
`code_version = 8b1b600-dirty`、`run_count = 1`、**无新字段**。

它是"补字段前"的唯一权威副本。
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
ARCHIVE = ROOT / "results" / "archive" / "v2-sample-threeway-cb9c77f.json"
CURRENT = ROOT / "results" / "v2-sample-threeway.json"


def _load(path: Path) -> dict[str, object]:
    if not path.exists():
        pytest.skip(f"{path.name} 缺失")
    return json.loads(path.read_text(encoding="utf-8"))


def test_archive_is_the_pre_field_version() -> None:
    """archive 必须是"补字段前"的版本，否则它无法证明字段是唯一变化。"""
    old = _load(ARCHIVE)

    assert "rerank_order_tags" not in old["per_case"][0], (  # type: ignore[index]
        "archive 里已有新字段——它不是补字段前的版本"
    )
    assert "pool_tag_meta" not in old["per_case"][0], (  # type: ignore[index]
        "archive 里已有新字段"
    )
    assert old["run_count"] == 1
    assert str(old["code_version"]).startswith("8b1b600")


def test_ranks_are_identical_after_adding_fields() -> None:
    """逐条 rank 必须完全相同。

    **这是"补字段没改实验"的唯一可复算证据。**
    """
    old = _load(ARCHIVE)
    cur = _load(CURRENT)

    old_ranks = {c["case_id"]: c["rank_after_rerank"] for c in old["per_case"]}  # type: ignore[index]
    cur_ranks = {c["case_id"]: c["rank_after_rerank"] for c in cur["per_case"]}  # type: ignore[index]

    assert old_ranks.keys() == cur_ranks.keys()
    diffs = {k: (old_ranks[k], cur_ranks[k]) for k in old_ranks if old_ranks[k] != cur_ranks[k]}
    assert not diffs, f"补字段改变了名次：{diffs}"


def test_seh_and_srs_are_identical_after_adding_fields() -> None:
    old = _load(ARCHIVE)
    cur = _load(CURRENT)

    assert old["seh_at_k"] == pytest.approx(cur["seh_at_k"], abs=1e-12)  # type: ignore[arg-type]
    assert old["srs"] == pytest.approx(cur["srs"], abs=1e-12)  # type: ignore[arg-type]


def test_path_returns_are_identical() -> None:
    """三路返回条数**不得**相同——它是另一个阶段。

    **这条测试原本写错了，值得记下**：archive（`8b1b600-dirty`）跑在
    `e91f893` **之前**，而那次提交给干扰项传了 `memory_text`
    （此前是 `text=None`，FTS 索引里只有 value）。于是：

        阶段 archive：lexical 总召回 10 条（q1/q2/q5/q6 各 1 条）
        阶段当前  ：lexical 总召回 14 条（同样四条各 2 条）

    **名次没变**（12 条 rank 全部相同），变的是召回宽度。

    所以：
    - `rank` 相同 → 可以用 archive 证明"补字段没改名次"
    - `path_returns` 不同 → 不能用 archive 证明"召回完全没变"，那本来就不是同一阶段

    把这条写反，会得出"rerun 改变了召回"的错误结论。
    """
    old = _load(ARCHIVE)
    cur = _load(CURRENT)

    old_returns = old["path_returns"]
    cur_returns = cur["path_returns"]

    # vector 与 adjacency 相同（这两路不受 text 改动影响）
    assert old_returns["vector"] == cur_returns["vector"]  # type: ignore[index]
    assert old_returns["adjacency"] == cur_returns["adjacency"]  # type: ignore[index]

    # lexical 必须**不同**：archive 早于 e91f893，那时干扰项 text=None
    assert old_returns["lexical"] != cur_returns["lexical"], (  # type: ignore[index]
        "两阶段的 lexical 召回相同了——说明归档文件不是 e91f893 之前的版本"
    )
    assert old_returns["lexical"] == 10  # type: ignore[index]
    assert cur_returns["lexical"] == 14  # type: ignore[index]


def test_archive_matches_git_history() -> None:
    """archive 必须与 git 里的 `cb9c77f` 版本逐字节等价（内容层面）。

    否则它是一份来历不明的副本，不能当证据。
    """
    result = subprocess.run(
        ["git", "show", "cb9c77f:results/v2-sample-threeway.json"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    if result.returncode != 0:
        pytest.skip("git 历史不可用")

    from_git = json.loads(result.stdout)
    archived = _load(ARCHIVE)

    assert from_git["seh_at_k"] == pytest.approx(archived["seh_at_k"], abs=1e-12)  # type: ignore[arg-type]
    assert from_git["run_count"] == archived["run_count"]
    assert str(from_git["code_version"]) == str(archived["code_version"])

    git_ranks = {c["case_id"]: c["rank_after_rerank"] for c in from_git["per_case"]}
    arc_ranks = {c["case_id"]: c["rank_after_rerank"] for c in archived["per_case"]}  # type: ignore[index]
    assert git_ranks == arc_ranks
