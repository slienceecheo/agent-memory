"""五组配置的 provenance 必须统一，且覆盖必须被记录。

**为什么需要**：报告里的五组分解表是 v2 当前唯一的路径贡献证据。
它曾经混了四个代码状态：

    8b1b600-dirty / 0af9969c   lexical、lexical-vector、lexical-vector-adjacency
    e91f893       / None       vector、vector-adjacency（连 hash 都没记）
    cb9c77f-dirty / a65de977   sample-threeway

其中 `e91f893` 与 `8b1b600-dirty` 是 git 历史上的两个点，
而 `v2-sample-threeway` 还混进了新字段。

于是"lexical=0.6667 / vector=1.0000"这两行出自不同版本的代码，
读者无法判断复算会得到什么。

这和 `{1:33}` vs `{1:29,2:4}` 是同一形态，只是发生在五组而不是一组。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
RESULTS = ROOT / "results"

CONFIGS = [
    "v2-ledger-lexical.json",
    "v2-ledger-vector.json",
    "v2-ledger-lexical-vector.json",
    "v2-ledger-vector-adjacency.json",
    "v2-ledger-lexical-vector-adjacency.json",
    "v2-sample-threeway.json",
]


def _load(name: str) -> dict[str, object]:
    path = RESULTS / name
    if not path.exists():
        pytest.skip(f"{name} 缺失")
    return json.loads(path.read_text(encoding="utf-8"))


def test_all_configs_share_one_code_state() -> None:
    """六份结果必须来自同一个 `code_version` 与 `code_diff_hash`。

    这是"五组分解可比较"的前提。不同版本的数字并列，
    等于把两个实验的结果放在一张表里。
    """
    versions = set()
    hashes = set()
    for name in CONFIGS:
        payload = _load(name)
        versions.add(str(payload.get("code_version")))
        hashes.add(str(payload.get("code_diff_hash")))

    assert len(versions) == 1, f"code_version 不统一：{versions}"
    assert len(hashes) == 1, f"code_diff_hash 不统一：{hashes}"


def test_all_configs_have_the_new_fields() -> None:
    """六份都应有 `rerank_order_tags` / `pool_tag_meta`。

    旧文件没有这个字段，所以"哪些文件是旧的"一眼可见——
    这正是把竞争集名次做成可复算的副产品。
    """
    for name in CONFIGS:
        payload = _load(name)
        first = payload["per_case"][0]  # type: ignore[index]
        assert "rerank_order_tags" in first, f"{name} 缺 rerank_order_tags"
        assert "pool_tag_meta" in first, f"{name} 缺 pool_tag_meta"


def test_overwrite_is_recorded_when_code_state_changed() -> None:
    """被不同代码状态覆盖过的文件必须记 `supersedes`。

    `run_count=2` 有两种含义：同一实验跑了两次，或两个实验写进了同一文件。
    只有 `supersedes` 能分开它们。
    """
    superseded = {}
    for name in CONFIGS:
        payload = _load(name)
        if "supersedes" in payload:
            superseded[name] = payload["supersedes"]

    assert superseded, "没有任何文件记录 supersedes——覆盖未被记录"
    for name, old in superseded.items():
        assert isinstance(old, dict), f"{name} 的 supersedes 不是对象"
        assert "code_version" in old
        assert "code_diff_hash" in old
        # 判据是**完整状态**（version + diff hash），不只是 version：
        # 同一 commit 上 `ruff --fix` 之后 diff hash 会变，
        # 只比 version 会把"代码确实变了"误判成"同一状态"。
        current = _load(name)
        same = (
            old["code_version"] == current["code_version"]
            and old["code_diff_hash"] == current["code_diff_hash"]
        )
        assert not same, f"{name} 的 supersedes 与当前完整状态相同，不该记录"


def test_supersedes_old_versions_are_from_git_history() -> None:
    """`supersedes` 里的版本号必须是 git 历史中真实存在的 commit（或带 -dirty）。

    否则 provenance 是编造的。
    """
    import subprocess

    for name in CONFIGS:
        payload = _load(name)
        old = payload.get("supersedes")
        if not isinstance(old, dict):
            continue
        version = str(old["code_version"]).replace("-dirty", "")
        result = subprocess.run(
            ["git", "cat-file", "-t", version],
            cwd=ROOT,
            capture_output=True,
            text=True,
        )
        assert result.stdout.strip() == "commit", (
            f"{name} 的 supersedes 版本 {version} 不是真实 commit"
        )


def test_numbers_unchanged_by_the_rerun() -> None:
    """**核心**：重跑只为补字段，不得改变任何数字。

    五组的 SEH@5 必须仍是旧值：

        lexical 0.6667 / vector 1.0000 / lex+vec 1.0000
        vec+adj 0.9167 / 3paths 0.9167

    若某个数字变了，说明代码改动影响了结果，那"补齐字段"就变成了"换了实验"。
    """
    expected = {
        "v2-ledger-lexical.json": 0.6667,
        "v2-ledger-vector.json": 1.0000,
        "v2-ledger-lexical-vector.json": 1.0000,
        "v2-ledger-vector-adjacency.json": 0.9167,
        "v2-ledger-lexical-vector-adjacency.json": 0.9167,
        "v2-sample-threeway.json": 0.9167,
    }
    for name, value in expected.items():
        actual = _load(name)["seh_at_k"]
        assert actual == pytest.approx(value, abs=1e-4), f"{name}: {actual} != {value}"


def test_word_path_contributes_nothing_on_axis_a() -> None:
    """A 轴上词面贡献为 0——这是报告里的核心结论，必须能复算。

    `lex+vec` 与 `vector` 的 A 轴 SEH@1 相同。
    """
    sys_path = ROOT / "data" / "retrieval-v2" / "sample" / "queries.jsonl"
    if not sys_path.exists():
        pytest.skip("数据集缺失")

    axis_of = {
        json.loads(line)["query_id"]: json.loads(line)["axis"]
        for line in sys_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    }
    a_ids = [qid for qid, axis in axis_of.items() if axis == "A"]

    def axis_a_seh1(name: str) -> float:
        payload = _load(name)
        ranks = {
            case["case_id"]: case["rank_after_rerank"]
            for case in payload["per_case"]  # type: ignore[index]
        }
        return sum(1 for qid in a_ids if ranks[qid] == 1) / len(a_ids)

    with_lex = axis_a_seh1("v2-ledger-lexical-vector.json")
    without_lex = axis_a_seh1("v2-ledger-vector.json")

    assert with_lex == pytest.approx(without_lex, abs=1e-4), (
        f"词面在 A 轴上有了增量：lex+vec={with_lex} vector={without_lex}"
    )
