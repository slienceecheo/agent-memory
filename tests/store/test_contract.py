"""契约测试的入口。

实现通过 fixture 的 `params` 注册。新增 Postgres 实现时只加一个名字，
下面的全部断言自动套用，测试代码零改动。
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from pathlib import Path

import pytest

from memory.store.base import MemoryStore
from memory.store.contract import CHECKS, run_all_contract_checks
from memory.store.sqlite import SqliteStore

# 新增实现时在这里加一个工厂：name -> 构造函数
FACTORIES: dict[str, Callable[[Path], MemoryStore]] = {
    "sqlite": lambda path: SqliteStore(path),
}


@pytest.fixture(params=list(FACTORIES))
def store(request: pytest.FixtureRequest, tmp_path: Path) -> Iterator[MemoryStore]:
    instance = FACTORIES[request.param](tmp_path / "contract.db")
    yield instance
    instance.close()  # type: ignore[attr-defined]


@pytest.fixture
def make_db(tmp_path: Path) -> Callable[[str], MemoryStore]:
    """为每条独立检查提供一个干净的库。"""

    created: list[MemoryStore] = []

    def factory(tag: str) -> MemoryStore:
        instance = FACTORIES["sqlite"](tmp_path / f"{tag}.db")
        created.append(instance)
        return instance

    yield factory
    for instance in created:
        instance.close()  # type: ignore[attr-defined]


def test_all_contract_checks_pass(store: MemoryStore) -> None:
    """聚合入口：一次跑完全部检查，失败时列出是哪一条。"""
    failures = run_all_contract_checks(store)

    assert failures == [], "契约检查失败：\n" + "\n".join(failures)


@pytest.mark.parametrize("check_name", list(CHECKS))
def test_each_contract_check_individually(
    make_db: Callable[[str], MemoryStore], check_name: str
) -> None:
    """逐条独立跑，失败定位更精确。

    与聚合测试重复是刻意的：聚合给出总览，逐条给出精确的失败点。
    """
    fresh = make_db(check_name.replace(" ", "_").replace("/", "_"))

    CHECKS[check_name](fresh)


def test_contract_covers_every_acceptance_criterion() -> None:
    """proposal 里 B1–B7 共 7 条，契约检查必须一一对应。"""
    assert len(CHECKS) == 7
    for index in range(1, 8):
        assert any(key.startswith(f"B{index}") for key in CHECKS), f"缺少 B{index} 的检查"
