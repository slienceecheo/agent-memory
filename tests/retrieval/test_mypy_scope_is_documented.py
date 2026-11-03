"""`mypy` 的覆盖范围必须被写清楚，否则"clean"是假绿。

**为什么这条要有**：`pyproject.toml` 里

```toml
[tool.mypy]
files = ["src"]

[[tool.mypy.overrides]]
module = ["evals.*", "tests.*"]
ignore_errors = true
```

所以：

| 命令 | 看起来 | 实际 |
|---|---|---|
| `mypy`（无参数） | clean | **只查 38 个 src 文件** |
| `mypy src evals tests` | clean（232 files） | **evals/tests 的 492 个错误被关掉** |

**实测**：往 `tests/` 塞一个 `def f(x: int) -> str: return x`，
`mypy tests/...` 仍报 `Success: no issues found`。

**这条测试不主张"应该修那 492 个错误"**——那是独立决策。
它只主张：**报告里的 "mypy clean" 必须带范围**，
否则读者会以为 tests/evals 也被检查过。
"""

from __future__ import annotations

import tomllib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
PYPROJECT = ROOT / "pyproject.toml"


def _mypy_config() -> dict:
    data = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))
    return data.get("tool", {}).get("mypy", {})


def test_mypy_files_is_src_only() -> None:
    """配置里的 `files` 只有 `src`——这是"38 files"的来源。

    改这个配置会让 `mypy` 的覆盖范围变宽（并立刻冒出数百个错误），
    所以它应当是一次**显式决策**，不是顺手改。
    """
    cfg = _mypy_config()
    assert cfg.get("files") == ["src"], (
        f"mypy 的 files 变成 {cfg.get('files')!r}。"
        "若确实要扩到 evals/tests，先处理那 492 个错误，并同步改 HANDOFF 的范围说明。"
    )


def test_evals_and_tests_are_ignored() -> None:
    """`evals.*` / `tests.*` 被 `ignore_errors = true` 屏蔽——这才是"232 files clean"的真相。"""
    data = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))
    overrides = data.get("tool", {}).get("mypy", {}).get("overrides", [])
    assert overrides, "overrides 段不见了——mypy 行为会变"

    ignored_modules: set[str] = set()
    for ov in overrides:
        if ov.get("ignore_errors") is True:
            mods = ov.get("module") or []
            if isinstance(mods, str):
                mods = [mods]
            ignored_modules.update(mods)

    assert "evals.*" in ignored_modules, f"evals.* 不再被忽略：{ignored_modules}"
    assert "tests.*" in ignored_modules, f"tests.* 不再被忽略：{ignored_modules}"


def test_handoff_states_the_real_scope() -> None:
    """HANDOFF 必须写明范围，而不是只写 "mypy -> clean"。"""
    text = (ROOT / "docs" / "HANDOFF.md").read_text(encoding="utf-8")

    assert "`mypy -> clean` 必须带范围" in text, (
        "HANDOFF 少了'必须带范围'的说明。"
        "只有一句 clean，读者会以为 tests/evals 也被查过。"
    )
    assert "38 个 src 文件" in text
    assert "492 个错误" in text
    assert "假绿" in text or "被**关掉**" in text


def test_ignore_errors_really_suppresses(tmp_path: Path) -> None:
    """**实证**：`ignore_errors` 生效时，明显的类型错误不会报。

    这条是防"配置改了但行为没变"——例如把 `module` 写成 `tests`（无 `.*`）。
    """
    probe = ROOT / "tests" / "_mypy_scope_probe.py"
    probe.write_text(
        "def f(x: int) -> str:\n"
        "    return x\n",
        encoding="utf-8",
    )
    try:
        import subprocess

        r = subprocess.run(
            ["uv", "run", "--no-sync", "mypy", str(probe.relative_to(ROOT))],
            cwd=ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        out = (r.stdout or "") + (r.stderr or "")
        if "error: Cannot find implementation" in out or r.returncode not in (0, 1):
            pytest.skip(f"mypy 不可用：{out.strip()[:100]}")

        assert "Success" in out, (
            f"tests 下的明显类型错误被 mypy 报出来了：{out.strip()[:200]}。\n"
            "若这是有意的（例如移除了 ignore_errors），"
            "请同步改 HANDOFF 与 test_evals_and_tests_are_ignored。"
        )
    finally:
        probe.unlink(missing_ok=True)
