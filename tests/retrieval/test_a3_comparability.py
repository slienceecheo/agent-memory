"""A3 三组对照必须来自同一份代码，否则对照本身不成立。

**这条为什么必要**：`code_version` 第一次投入使用就抓到一个真问题——
四份结果的 `code_diff_hash` 分成两组（`240595d2` 与 `189db1d9`）。
三份数字看起来整齐（0.9091 / 0.8182 / 0.6667，差值 0.091 / 0.152，
像"每接一路掉一截"），但其中一份来自另一个代码状态。

**数字本身不会告诉你它们不可比。** 这与 C4 归档被覆盖是同一类问题，
只是层级更高：不是文件被覆盖，而是这一组数字没有共同的代码基线。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
RESULTS = ROOT / "results"

A3_FILES = (
    "a3-lexical.json",
    "a3-lexical-vector.json",
    "a3-lexical-vector-adjacency.json",
)


def _load(name: str) -> dict[str, object]:
    path = RESULTS / name
    if not path.exists():
        pytest.skip(f"{name} 不存在（尚未跑 A3 对照）")
    return json.loads(path.read_text(encoding="utf-8"))


def test_three_way_results_share_code_fingerprint() -> None:
    """三组对照的 `code_diff_hash` 必须相同。"""
    hashes = {name: _load(name).get("code_diff_hash") for name in A3_FILES}

    distinct = set(hashes.values())
    assert len(distinct) == 1, (
        f"三组对照的代码指纹不同：{hashes}\n"
        "这意味着它们不是同一份代码的三种配置，而是三次不同代码各跑了一次。"
        "请在同一 diff_hash 下重跑全部三组，再引用这些数字。"
    )


def test_three_way_results_share_commit() -> None:
    """commit 部分也必须相同（`-dirty` 后缀可以不同但不应出现）。"""
    versions = {name: _load(name).get("code_version") for name in A3_FILES}

    assert len(set(versions.values())) == 1, f"commit 不同：{versions}"


def test_a3_results_cover_the_three_configurations() -> None:
    """三份结果必须分别对应三种路径配置，不能重复。"""
    enabled = {name: tuple(_load(name).get("paths_enabled") or ()) for name in A3_FILES}

    assert enabled[A3_FILES[0]] == ("lexical",)
    assert enabled[A3_FILES[1]] == ("lexical", "vector")
    assert set(enabled[A3_FILES[2]]) == {"lexical", "vector", "adjacency"}
    assert len(set(enabled.values())) == 3


def test_a3_results_use_same_split_and_pool() -> None:
    """split / weights / pool / k 必须一致，否则不是同一实验。"""
    fields = ("split", "weights", "pool_mode", "k")
    first = {f: _load(A3_FILES[0]).get(f) for f in fields}

    for name in A3_FILES[1:]:
        payload = _load(name)
        for field in fields:
            assert payload.get(field) == first[field], (
                f"{name} 的 {field} 是 {payload.get(field)!r}，"
                f"与 {A3_FILES[0]} 的 {first[field]!r} 不同"
            )
