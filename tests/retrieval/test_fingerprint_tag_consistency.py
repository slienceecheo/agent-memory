"""结果文件的指纹必须能对上 frozen tag——否则第一次复算就会撞上。

**实测的不一致**：

    results/v2-*.json 的 code_version = 47e4785-dirty
    dataset-v2-frozen 指向          5a55620

两者相差 3 个 commit。而 `47e4785..5a55620` 之间**确实改了 `evals/`**：
`check_v2_dataset.py` 加了 gates 指纹。所以"tag 之后只有文档改动"这个
常见假设在这里是**假的**。

逐项核实（本文件断言的就是这些）：

| 范围 | 47e4785..frozen 有改动吗 | 影响 |
|---|---|---|
| `evals/run_retrieval.py`（评测入口） | **无** | 评测数字有效 |
| `evals/datasets/*`、`src/**` | **无** | 同上 |
| `evals/tools/check_v2_dataset.py` | **有**（加 gates 指纹） | 只影响输出格式，判定不变 |
| 文档 | 有 | 无影响 |

所以结论是：**数字有效，但"指纹 == tag"不成立**。
这条测试锁住"这个不一致是被核实的，不是被忽略的"。
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
TAG = "dataset-v2-frozen"
RESULTS = ROOT / "results"


def _git(*args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=ROOT, capture_output=True, text=True, encoding="utf-8"
    ).stdout


def _tag_commit() -> str:
    return _git("rev-parse", f"{TAG}^{{commit}}").strip()


def _result_commit() -> str:
    """结果文件记录的 code_version 去掉 `-dirty` 后缀。"""
    payload = json.loads(
        (RESULTS / "v2-sample-threeway.json").read_text(encoding="utf-8")
    )
    version = str(payload["code_version"])
    return version.removesuffix("-dirty")


def test_result_fingerprint_is_ancestor_of_tag() -> None:
    """结果文件的 commit 必须是 tag 指向 commit 的**祖先**。

    若它不是祖先（比如结果是在 tag 之后跑的），说明 tag 之后改了代码却没重跑——
    那时结果文件与 tag 就不再对应。
    """
    result_commit = _result_commit()
    tag_commit = _tag_commit()

    ancestor = subprocess.run(
        ["git", "merge-base", "--is-ancestor", result_commit, tag_commit],
        cwd=ROOT,
    )
    assert ancestor.returncode == 0, (
        f"结果的 commit {result_commit} 不是 {TAG}（{tag_commit}）的祖先——"
        "tag 之后改了代码却没重跑结果"
    )


def test_no_changes_to_the_evaluation_entry_between_result_and_tag() -> None:
    """**关键**：结果 commit 到 tag 之间，评测入口不得有改动。

    实测只有 `check_v2_dataset.py` 变了（加 gates 指纹），
    而它不影响 `run_retrieval.py` 产出的数字。

    若将来有人在这段区间改了 `run_retrieval.py`，这条会红——
    那时必须重跑结果，否则数字与 tag 不对应。
    """
    diff = _git("diff", "--name-only", f"{_result_commit()}..{_tag_commit()}", "--", "evals", "src")
    changed = {line.strip() for line in diff.splitlines() if line.strip()}

    # 允许的改动：只影响 gates 输出格式，不碰评测路径
    allowed = {"evals/tools/check_v2_dataset.py"}
    unexpected = changed - allowed

    assert not unexpected, (
        f"结果 commit 到 tag 之间，评测相关文件被改了：{sorted(unexpected)}——"
        "必须重跑结果并重新打 tag"
    )


def test_gate_verdicts_still_reproduce() -> None:
    """gates 文件在改动之前生成，但当前代码重跑必须给出同一判定。

    这是"那次改动只影响格式"的直接验证。

    **为什么不调网络**：`run_all()` 不导入 embedding，F19b/F20 读的是
    已有的消融结果 JSON。所以这个测试在任何环境下都只读文件。

    **但仍然要求 gates 结果与消融结果存在**：缺它们时 `run_all()` 会
    返回 F19b/F20 失败而不是跳过，那会把"环境不全"报成"判定不一致"。
    """
    import sys

    sys.path.insert(0, str(ROOT))

    # 前置：F19b/F20 依赖的结果文件必须在
    for needed in (
        "v2-sample-condition-ablation.json",
        "v2-billing-condition-ablation.json",
    ):
        if not (RESULTS / needed).exists():
            pytest.skip(f"{needed} 缺失——缺它会误报判定不一致")

    from evals.datasets.retrieval_v2 import load_dataset
    from evals.tools.check_v2_dataset import run_all

    for name, path in (
        ("sample", "v2-sample-gates.json"),
        ("billing", "v2-billing-gates.json"),
    ):
        stored_path = RESULTS / path
        if not stored_path.exists():
            pytest.skip(f"{path} 缺失")
        stored = json.loads(stored_path.read_text(encoding="utf-8"))
        stored_checks = {c["code"]: c["passed"] for c in stored["checks"]}
        fresh = {
            r.code: r.passed
            for r in run_all(load_dataset(ROOT / "data" / "retrieval-v2" / name))
        }

        diff = {
            k: (stored_checks.get(k), fresh.get(k))
            for k in stored_checks
            if stored_checks[k] != fresh.get(k)
        }
        assert not diff, f"{name} 的判定变了：{diff}"


def test_handoff_documents_the_fingerprint_tag_gap() -> None:
    """§0 必须解释"指纹 47e4785-dirty 与 tag 5a55620 的关系"。

    否则第一次复算的人会撞上它，然后怀疑自己的环境。
    """
    text = (ROOT / "docs" / "HANDOFF.md").read_text(encoding="utf-8")

    assert "47e4785" in text, "§0 未写结果的 commit"
    assert "5a55620" in text, "§0 未写 tag 指向的 commit"
    # 必须说清为什么不同
    assert "祖先" in text or "之前" in text
    # 必须给出复算方式
    assert "git diff" in text or "checkout" in text


def test_handoff_states_which_files_changed_in_that_range() -> None:
    """§0 必须写明区间内**改了什么**——不能只说"只有文档"。

    实测 `check_v2_dataset.py` 也改了。写"只有文档改动"是不准确的。
    """
    text = (ROOT / "docs" / "HANDOFF.md").read_text(encoding="utf-8")
    section = text[: text.index("## 项目是什么")] if "## 项目是什么" in text else text

    assert "check_v2_dataset" in section, (
        "§0 未写明区间内改了 check_v2_dataset.py——"
        "「只有文档改动」这个说法是错的"
    )


def test_code_version_semantics_is_documented() -> None:
    """必须写明 `code_version` 的 `-dirty` 语义。

    它混了两件事：commit + 工作区是否干净。
    所以"结果指纹 47e4785-dirty"与"tag 5a55620"永远对不上，
    除非跑的时候工作区恰好干净。
    """
    text = (ROOT / "docs" / "HANDOFF.md").read_text(encoding="utf-8")

    assert "-dirty" in text
    assert "工作区" in text
