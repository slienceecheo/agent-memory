"""缺陷 17：`paths` 含 vector 但 `embedder=None` 时不得静默降级。

**这是本轮最贵的一个装置问题**：同一个 `evaluate()` 调用，加不加 embedder：

    不加  path_returns={'lexical': 14, 'vector': None}   SEH@5=0.6667
    加    path_returns={'lexical': 14, 'vector': 144}    SEH@5=1.0000

而 `paths_unwired` 在两种情况下**都是空**，与"只开 lexical"完全无法区分。

第 1 组当初加 `paths_unwired` 正是为了区分"没开"和"开了但没接线"。
现在出现了第三种状态：**开了、接线了、但依赖没注入**——它落在两种现有状态
之间，两边都不匹配，于是显示成"没开"。

在测量工具里，静默降级永远比抛错危险：调用方会得到一组看起来正常的数字，
而真实原因是某条路径根本没跑。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from evals.run_retrieval import evaluate

from memory.retrieval.pool_modes import PoolMode

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data" / "conflict-set"


def _rows() -> list[dict[str, object]]:
    path = DATA / "dev.jsonl"
    if not path.exists():
        pytest.fail(f"数据集缺失：{path}")
    rows = [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    return [r for r in rows if r.get("gold")][:2]


def _specs() -> list[dict[str, object]]:
    rows = [
        json.loads(line)
        for line in (DATA / "dev.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    return [r["gold"] for r in rows if r.get("gold")]  # type: ignore[misc]


def test_vector_without_embedder_raises() -> None:
    """**核心**：请求 vector 但不给 embedder，必须抛错。

    不许静默跳过——那会让 `SEH@5` 从 1.000 掉到 0.667 而不留痕迹。
    """
    with pytest.raises(ValueError, match="embedder"):
        evaluate(
            _rows(),
            all_specs=_specs(),
            weights_name="uniform",
            enable_dedup=False,
            judge=None,
            k=5,
            pool_mode=PoolMode.UNRELATED,
            paths=("lexical", "vector"),
            embedder=None,
        )


def test_error_message_names_the_missing_dependency() -> None:
    """错误信息必须指出缺什么、以及为什么不能静默跳过。"""
    with pytest.raises(ValueError) as excinfo:
        evaluate(
            _rows(),
            all_specs=_specs(),
            weights_name="uniform",
            enable_dedup=False,
            judge=None,
            k=5,
            pool_mode=PoolMode.UNRELATED,
            paths=("vector",),
            embedder=None,
        )

    message = str(excinfo.value)
    assert "embedder" in message
    assert "静默" in message or "silently" in message.lower()


def test_lexical_only_without_embedder_is_fine() -> None:
    """只开 lexical 时不需要 embedder——这是合法的零依赖配置。"""
    result = evaluate(
        _rows(),
        all_specs=_specs(),
        weights_name="uniform",
        enable_dedup=False,
        judge=None,
        k=5,
        pool_mode=PoolMode.UNRELATED,
        paths=("lexical",),
        embedder=None,
    )

    assert result["path_returns"]["lexical"] is not None
    assert result["path_returns"]["vector"] is None


def test_no_paths_without_embedder_is_fine() -> None:
    """全关（零召回基线）不需要 embedder。"""
    result = evaluate(
        _rows(),
        all_specs=_specs(),
        weights_name="uniform",
        enable_dedup=False,
        judge=None,
        k=5,
        pool_mode=PoolMode.UNRELATED,
        paths=(),
        embedder=None,
    )

    assert result["seh_at_k"] == 0.0
