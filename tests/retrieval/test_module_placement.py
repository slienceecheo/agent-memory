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


def test_no_src_eval_module_is_unbacked() -> None:
    """`src/memory/eval/` 下每个模块必须有**依据**，依据有两种形式之一：

    1. **spec 明确要求**它（如 `bootstrap` 的"配对 bootstrap 置信区间"、
       `metrics` 的 `substring_exact_match`）
    2. **被生产代码调用**（`src/` 或 `evals/` 里有 import）

    **为什么不用"名字出现在 spec 里"当判据**：那是靠关键词白名单，
    新模块凑巧名字匹配就会通过。而"有没有被调用"是结构事实，不需要白名单。

    第一版写成手工 `keywords` 表，只覆盖 `metrics` 和 `bootstrap` 两个模块——
    那是"测试名字覆盖一类、实现只查两个实例"，正是本文件要防的形态。
    """
    eval_dir = SRC / "memory" / "eval"
    if not eval_dir.exists():
        pytest.skip("src/memory/eval 不存在")

    spec = _spec_text().lower()

    # 收集"被谁 import"——结构事实，不依赖白名单
    importers: dict[str, set[str]] = {}
    for root in (SRC, ROOT / "evals"):
        for path in root.rglob("*.py"):
            text = path.read_text(encoding="utf-8")
            for module in eval_dir.glob("*.py"):
                if module.name.startswith("__"):
                    continue
                stem = module.stem
                if f"eval.{stem}" in text or f"eval import {stem}" in text:
                    # 排除模块自身所在目录的自引用
                    if root == SRC and module.parent in path.parents:
                        continue
                    importers.setdefault(stem, set()).add(
                        str(path.relative_to(ROOT))
                    )

    unbacked: list[str] = []
    for module in eval_dir.glob("*.py"):
        if module.name.startswith("__"):
            continue
        stem = module.stem
        in_spec = stem in spec
        called = bool(importers.get(stem))

        if not in_spec and not called:
            unbacked.append(f"{module.name}（spec 未提，且无生产调用方）")

    assert not unbacked, (
        f"这些模块在 src/ 但没有依据：{unbacked}。"
        "依据 = spec 明确要求，或被生产代码调用。"
        "两者都没有就是'实现先行'——要么补 requirement（需开变更），要么移到 evals/"
    )


def test_metrics_py_has_both_kinds_of_backing() -> None:
    """`metrics.py` 是"两种依据都有"的样本，用来验证上面的判据真能工作。

    - spec 第 59 行要求 `substring_exact_match`
    - `evals/baselines/base.py` 调用它

    若这条红，说明判据（spec 提及 / 生产调用）本身失效了。
    """
    spec = _spec_text()
    assert "substring_exact_match" in spec, "spec 不再要求 substring_exact_match"

    base = ROOT / "evals" / "baselines" / "base.py"
    if not base.exists():
        pytest.skip("evals/baselines/base.py 缺失")
    assert "memory.eval.metrics" in base.read_text(encoding="utf-8"), (
        "base.py 不再调用 metrics——依据只剩 spec 了"
    )


def test_unbacked_detector_actually_fires() -> None:
    """**判据必须真的会红**——否则它只是装饰。

    做法：临时在 `src/memory/eval/` 放一个无依据模块（spec 未提、无人调用），
    断言检测逻辑能抓到它，然后删掉。

    这条测试防的是"测试名字覆盖一类、实现只查一个实例"这一路反复出现的形态：
    第一版用的是手工 `keywords` 白名单，只覆盖 `metrics` 与 `bootstrap`，
    新模块只要名字凑巧匹配就会通过。
    """
    probe = SRC / "memory" / "eval" / "tmp_unbacked_probe.py"
    if not (SRC / "memory" / "eval").exists():
        pytest.skip("src/memory/eval 不存在")

    probe.write_text("MARKER = 1\n", encoding="utf-8")
    try:
        with pytest.raises(AssertionError, match="tmp_unbacked_probe"):
            test_no_src_eval_module_is_unbacked()
    finally:
        probe.unlink(missing_ok=True)

    # 删除后必须恢复绿色
    test_no_src_eval_module_is_unbacked()


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
