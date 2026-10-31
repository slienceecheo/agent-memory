"""`src/` 里只放 spec 要求的能力；评测工具归 `evals/`。

**为什么需要**：`wilson.py` 曾被放在 `src/memory/eval/`，而
`openspec/specs/evaluation-harness/spec.md` 里没有对应的 requirement。
于是 `src/` 出现"实现先行、spec 缺失"——下一个人读代码会问
"这个模块对应哪条要求"，然后发现没有。

这与 C4 缺陷 7（"单元测试通过"被写成"已建成"）是同一种形态的弱版本。

分层原则：

| 位置 | 放什么 | 依据 |
|---|---|---|
| `src/memory/eval/` | 系统能力 | **spec 要求** |
| `evals/metrics/` | 评测装置 | 不产品化 |
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SPECS = ROOT / "openspec" / "specs"
SRC = ROOT / "src"


def _spec_text() -> str:
    parts = []
    for path in SPECS.rglob("spec.md"):
        parts.append(path.read_text(encoding="utf-8"))
    return "\n".join(parts)


def test_wilson_is_not_in_src() -> None:
    """`wilson.py` 必须在 `evals/`，不在 `src/`。

    它在 `src/` 时没有任何 spec requirement 支撑。
    """
    assert not (SRC / "memory" / "eval" / "wilson.py").exists(), (
        "wilson.py 又被放回 src/ 了——那它需要一条 spec requirement"
    )
    assert (ROOT / "evals" / "metrics" / "wilson.py").exists()


def test_bootstrap_has_spec_backing() -> None:
    """`bootstrap.py` 在 `src/` 是有依据的——spec 明确要求配对 bootstrap。

    这条测试记录"为什么 bootstrap 可以在 src/ 而 wilson 不行"。
    """
    spec = _spec_text()

    assert "配对 bootstrap 置信区间" in spec or "bootstrap" in spec.lower()
    assert (SRC / "memory" / "eval" / "bootstrap.py").exists()


def test_no_src_eval_module_lacks_spec_mention() -> None:
    """`src/memory/eval/` 下每个模块都应在 spec 里被提到。

    这是"实现先行、spec 缺失"的直接检查。
    """
    spec = _spec_text().lower()
    eval_dir = SRC / "memory" / "eval"
    if not eval_dir.exists():
        pytest.skip("src/memory/eval 不存在")

    unbacked: list[str] = []
    for path in eval_dir.glob("*.py"):
        if path.name.startswith("__"):
            continue
        stem = path.stem.lower()
        # 模块名或其核心概念应出现在 spec 中
        if stem in spec:
            continue
        # 允许"模块名与概念名不同"的情况，按关键词匹配
        keywords = {
            "metrics": ["macro-f1", "seh", "srs"],
            "bootstrap": ["bootstrap"],
        }.get(stem, [])
        if any(k in spec for k in keywords):
            continue
        unbacked.append(path.name)

    assert not unbacked, (
        f"这些模块在 src/ 但没有 spec 依据：{unbacked}。"
        "要么补 requirement（需开变更），要么移到 evals/"
    )


def test_wilson_docstring_explains_its_location() -> None:
    """模块 docstring 必须写明"为什么在 evals/ 而不是 src/"。

    否则将来有人会以为它是随手放的。
    """
    path = ROOT / "evals" / "metrics" / "wilson.py"
    if not path.exists():
        pytest.skip("wilson.py 缺失")

    text = path.read_text(encoding="utf-8")
    head = text[:2000]

    assert "为什么在 `evals/`" in head or "为什么在 evals/" in head
    assert "spec" in head.lower()
    # 必须提到对照物：bootstrap 有 spec 依据
    assert "bootstrap" in head


def test_no_production_import_of_wilson() -> None:
    """`src/` 不得 import `wilson`——它目前只是评测工具。

    若将来要产品化，那是新变更的事：需要补 spec 要求并显式提升。
    """
    violations: list[str] = []
    for path in SRC.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        # 排除模块自身（现在不在 src，但防御性处理）
        if "wilson" in path.name:
            continue
        if re.search(r"evals\.metrics\.wilson|from .*wilson import", text):
            violations.append(str(path.relative_to(ROOT)))

    assert not violations, (
        f"src/ 里出现对 wilson 的 import：{violations}——"
        "产品化需要补 spec 要求，不能偷偷接线"
    )
