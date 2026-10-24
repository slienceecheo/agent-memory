"""归一化的行为契约。

归一化决定"什么算同一个键"。它错两头的代价不对称：
- 归一不足 → 同一概念被当成两条事实（表现为"记忆里有两份"，可接受）
- 归一过度 → 不同概念被合并（表现为"记忆里错了一份"，很难发现）

所以设计上宁可不猜：未登记的表达保留原值并标记 `normalized=False`。
"""

from __future__ import annotations

import dataclasses

import pytest

from memory.resolver.normalize import (
    InvalidKey,
    normalize_key,
)


def test_case_and_whitespace_are_folded() -> None:
    """大小写与空白差异不该产生两条事实。"""
    a = normalize_key("Project:Agent-Memory", "Package_Manager")
    b = normalize_key("  project:agent-memory  ", "  package_manager  ")

    assert a.subject == b.subject
    assert a.relation == b.relation


def test_fullwidth_is_normalized() -> None:
    """全角字符在中文输入里很常见，不归一会产生两套键。"""
    a = normalize_key("项目Ａ", "包管理器")
    b = normalize_key("项目A", "包管理器")

    assert a.subject == b.subject


def test_registered_alias_maps_to_canonical() -> None:
    """别名表把常见说法收敛到一个规范名。"""
    canonical = normalize_key("project:x", "package_manager")
    alias = normalize_key("project:x", "包管理器")

    assert alias.relation == canonical.relation
    assert alias.normalized is True


def test_english_alias_maps_to_same_canonical() -> None:
    canonical = normalize_key("project:x", "package_manager")
    alias = normalize_key("project:x", "package manager")

    assert alias.relation == canonical.relation


def test_unregistered_expression_keeps_original_and_flags() -> None:
    """未登记的表述保留原值并标记。

    强行映射到一个"看起来像"的名字，会把不同概念合并，
    而这种错误一旦写入就无法从结果看出来。
    """
    key = normalize_key("project:x", "某个没登记过的说法")

    assert key.relation == "某个没登记过的说法"
    assert key.normalized is False


def test_normalization_does_not_merge_different_subjects() -> None:
    """近似但不同的主体必须保持不同。"""
    a = normalize_key("project:agent-memory", "package_manager")
    b = normalize_key("project:agent-memory-v2", "package_manager")

    assert a.subject != b.subject
    assert a != b


def test_empty_subject_is_rejected() -> None:
    """空主体会让所有空主体的事实互相覆盖。"""
    with pytest.raises(InvalidKey, match="subject"):
        normalize_key("", "package_manager")


def test_empty_relation_is_rejected() -> None:
    with pytest.raises(InvalidKey, match="relation"):
        normalize_key("project:x", "   ")


def test_plural_is_normalized() -> None:
    """英文复数在自然语言里很常见。"""
    a = normalize_key("project:x", "package_managers")
    b = normalize_key("project:x", "package_manager")

    assert a.relation == b.relation


def test_key_equality_and_hash() -> None:
    """键要能作为字典的键使用。"""
    a = normalize_key("project:x", "包管理器")
    b = normalize_key("project:x", "package_manager")

    assert a == b
    assert hash(a) == hash(b)
    assert len({a, b}) == 1


def test_key_is_immutable() -> None:
    key = normalize_key("project:x", "package_manager")

    with pytest.raises(dataclasses.FrozenInstanceError):
        key.subject = "other"  # type: ignore[misc]


def test_chinese_subject_is_preserved() -> None:
    """中文主体不能被归一成空或拼音。"""
    key = normalize_key("这个仓库", "包管理器")

    assert key.subject == "这个仓库"
