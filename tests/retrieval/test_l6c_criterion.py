"""L6c 的判据必须看真实返回值，不能看源码里有没有函数名。

**为什么单独一条测试**：这条门禁最初的实现是
`if f"recall_by_{name}(" in source`，于是把调用注释掉
（`# recall_by_adjacency(...)`）字符串仍在，L6c 依然 PASS。

它宣称"直接测返回了什么"，实际测的是"源码里有没有这个字符串"——
与 C4 缺陷 6（docstring 与代码不一致）同形，只是位置在门禁本身。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from evals.tools.check_v2_dataset import check_l6c_paths_return_nonempty

ROOT = Path(__file__).resolve().parents[2]
RESULTS = ROOT / "results"


def test_l6c_reads_run_result_not_source() -> None:
    """判据必须来自结果文件，且**函数体**里不出现 `recall_by_` 源码匹配。

    用 `ast` 只取函数体，不取 docstring——docstring 里提到
    `recall_by_adjacency(` 是为了说明问题，不是判据。
    """
    import ast
    import inspect

    tree = ast.parse(inspect.getsource(check_l6c_paths_return_nonempty))
    func = tree.body[0]
    assert isinstance(func, ast.FunctionDef)
    body = "\n".join(ast.unparse(node) for node in func.body[1:])  # 跳过 docstring

    assert "path_returns" in body, "应读运行结果里的 path_returns"
    assert "json.loads" in body or "read_text" in body
    assert "recall_by_" not in body, (
        "判据又回到源码匹配了；把调用注释掉仍会 PASS"
    )


def test_l6c_requires_a_real_run_file() -> None:
    """没有结果文件时必须判失败，而不是默认通过。"""
    from evals.tools.check_v2_dataset import Check

    result = check_l6c_paths_return_nonempty(None)  # type: ignore[arg-type]

    assert isinstance(result, Check)
    if not (RESULTS / "a3-lexical-vector-adjacency.json").exists():
        assert result.passed is False
        assert "缺少真实运行结果" in result.detail


@pytest.mark.parametrize("field", ["lexical", "vector", "adjacency"])
def test_l6c_fails_when_a_path_returns_zero(field: str, tmp_path: Path, monkeypatch) -> None:
    """任一路返回 0 条时必须判失败。"""
    target = RESULTS / "a3-lexical-vector-adjacency.json"
    if not target.exists():
        pytest.skip("缺少三路运行结果")

    payload = json.loads(target.read_text(encoding="utf-8"))
    payload["path_returns"][field] = 0
    broken = tmp_path / "broken.json"
    broken.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    import evals.tools.check_v2_dataset as module

    monkeypatch.setattr(module, "ROOT", tmp_path.parent)
    # 直接构造同名路径
    fake_results = tmp_path.parent / "results"
    fake_results.mkdir(exist_ok=True)
    (fake_results / "a3-lexical-vector-adjacency.json").write_text(
        broken.read_text(encoding="utf-8"), encoding="utf-8"
    )

    result = check_l6c_paths_return_nonempty(None)  # type: ignore[arg-type]

    assert result.passed is False
    assert f"{field} 返回 0 条" in result.detail
