"""存储协议的行为契约。

断言的是"接口形状与异常语义"，而不是某个实现。
这些测试的价值：C3 依赖这套接口；接口漂移会让 C3 的代码全部重写。
"""

from __future__ import annotations

import inspect
from typing import get_type_hints

import pytest

from memory.store.base import (
    ActiveExists,
    InvalidTransition,
    InvariantViolation,
    MemoryStore,
    NotFound,
    StoreBusy,
    StoreError,
)


def test_protocol_declares_required_operations() -> None:
    """缺少任一操作会让 C3/C4 无法实现所需行为。"""
    for name in (
        "insert",
        "supersede",
        "retract",
        "resolve_conflict",
        "active_at",
        "timeline",
        "get",
        "count",
    ):
        assert hasattr(MemoryStore, name), f"协议缺少 {name}"


@pytest.mark.parametrize(
    "method", ["insert", "supersede", "retract", "resolve_conflict"]
)
def test_write_methods_require_reason_and_actor(method: str) -> None:
    """没有原因的审计记录无法追责；这两个参数必须强制，而不是可选默认值。"""
    signature = inspect.signature(getattr(MemoryStore, method))
    for param in ("reason", "actor"):
        assert param in signature.parameters, f"{method} 缺少必填参数 {param}"
        assert signature.parameters[param].default is inspect.Parameter.empty, (
            f"{method}.{param} 不能有默认值，否则调用方会省略它"
        )


def test_exceptions_are_distinguishable() -> None:
    """全部继承同一个基类，但彼此不可互相捕获。"""
    for exc in (ActiveExists, InvariantViolation, InvalidTransition, NotFound, StoreBusy):
        assert issubclass(exc, StoreError)

    with pytest.raises(ActiveExists):
        raise ActiveExists("x")
    with pytest.raises(StoreError):
        raise InvalidTransition("x")


def test_store_busy_is_not_confused_with_invariant_violation() -> None:
    """并发写锁与"已有有效值"是两件事。混为一谈会让重试逻辑做错决定。"""
    assert not issubclass(StoreBusy, InvariantViolation)
    assert not issubclass(InvariantViolation, StoreBusy)


def test_type_hints_resolve() -> None:
    """注解若在运行期无法解析，依赖它的实现会静默退化。"""
    hints = get_type_hints(MemoryStore.active_at)
    assert "return" in hints
