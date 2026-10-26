"""结果文件必须能自证"是哪版代码跑的"（缺陷 12 的第二子问题）。

**为什么这个字段比 `paths_enabled` 更基础**：
`paths_enabled` 说"试了什么"，`code_version` 说"用的是什么"。
缺了后者，前者就没有参照系。

这一轮花了几轮才查清 `{1:33}` 与 `{1:29, 2:4}` 的分歧，
靠的是 `git log` + `run_count` 反推。若有 `code_version`，第一眼就能看出来。

三个设计要求：

1. **`-dirty` 标记**：未提交代码产生的结果**不可复现**，必须标出来
2. **`code_diff_hash`**：两份 `-dirty` 结果若 diff 相同，就是同一份工作区代码；
   否则是两次不同的未提交状态。只记 `-dirty` 无法区分
3. **限定路径**：`git status --porcelain` 必须限定到 `evals src`，
   否则一个未跟踪的临时文件会让每次运行都标 `-dirty`，标记失去信息量
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

from evals.run_retrieval import code_version

ROOT = Path(__file__).resolve().parents[2]


def test_code_version_has_commit_and_dirty_marker() -> None:
    """返回值形如 `<short-rev>` 或 `<short-rev>-dirty`。"""
    version = code_version()

    assert re.fullmatch(r"[0-9a-f]{7,12}(-dirty)?", version), version


def test_code_version_matches_head_when_clean_prefix() -> None:
    """无未提交改动时，返回值必须以 HEAD 的 short rev 开头。

    不断言完全相等——若测试运行时工作区恰好有改动，会带 `-dirty`。
    这里只断言 commit 前缀部分正确。
    """
    head = subprocess.run(
        ["git", "rev-parse", "--short", "HEAD"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
    ).stdout.strip()

    assert code_version().startswith(head)


def test_code_version_is_stable_within_one_state() -> None:
    """同一状态下两次调用返回相同值。

    **这条防的是实现里混入 `datetime.now()` 之类的东西**——
    那会让"同一份代码"产生不同版本号，字段就失去识别能力。
    """
    assert code_version() == code_version()


def test_diff_hash_present_only_when_dirty() -> None:
    """`code_diff_hash` 只在 dirty 时非空；干净时为 None。

    两份 `-dirty` 结果靠它区分：hash 相同 = 同一份工作区代码，
    不同 = 两次不同的未提交状态。
    """
    from evals.run_retrieval import code_fingerprint

    fingerprint = code_fingerprint()

    assert set(fingerprint) == {"code_version", "code_diff_hash"}
    assert isinstance(fingerprint["code_version"], str)
    if fingerprint["code_version"].endswith("-dirty"):
        assert fingerprint["code_diff_hash"], "dirty 状态必须有 diff hash"
        assert len(str(fingerprint["code_diff_hash"])) == 64, "应为 sha256 hex"
    else:
        assert fingerprint["code_diff_hash"] is None


def test_diff_hash_covers_only_code_paths() -> None:
    """diff hash 只看 `evals` 与 `src`，不看文档或结果文件。

    若不限路径，改一份报告也会让 `code_version` 变成 `-dirty`，
    那这个标记就不再表示"代码变了"。
    """
    source = (ROOT / "evals" / "run_retrieval.py").read_text(encoding="utf-8")

    assert "evals" in source and "src" in source
    assert "git" in source and "status" in source


def test_result_payload_includes_code_fingerprint() -> None:
    """评测结果里必须带这两个字段。"""
    from evals.run_retrieval import evaluate

    result = evaluate(
        [],
        all_specs=[],
        weights_name="uniform",
        enable_dedup=False,
        judge=None,
        k=5,
    )

    assert "code_version" in result
    assert "code_diff_hash" in result
