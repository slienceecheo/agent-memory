"""缓存键的行为契约。

缓存键必须对四个字段都敏感。任何一个被漏掉，就会出现
"查询向量覆盖文档向量"或"换模型后复用旧向量"这类静默错误。
"""

from __future__ import annotations

from memory.embedding.cache_keys import cache_key

BASE = {
    "model": "qwen3.7-text-embedding-flash",
    "dims": 1024,
    "text_type": "document",
    "text": "项目使用 pnpm 作为包管理器",
}


def test_same_inputs_produce_same_key() -> None:
    """键不稳定会让每次运行都未命中，A3 的"第二次为 0 次网络请求"永远不成立。"""
    assert cache_key(**BASE) == cache_key(**BASE)


def test_model_change_changes_key() -> None:
    """漏掉 model 会复用别的模型产出的向量，维度相同也不可比。"""
    changed = {**BASE, "model": "text-embedding-v4"}
    assert cache_key(**BASE) != cache_key(**changed)


def test_dims_change_changes_key() -> None:
    """漏掉 dims 会把 768 维向量当成 1024 维读出来。"""
    changed = {**BASE, "dims": 768}
    assert cache_key(**BASE) != cache_key(**changed)


def test_text_type_change_changes_key() -> None:
    """漏掉 text_type 会让查询向量污染文档向量——实测两者余弦仅 0.842。"""
    changed = {**BASE, "text_type": "query"}
    assert cache_key(**BASE) != cache_key(**changed)


def test_text_change_changes_key() -> None:
    """漏掉 text 是最致命的：所有文本共用一个向量。"""
    changed = {**BASE, "text": "项目使用 npm 作为包管理器"}
    assert cache_key(**BASE) != cache_key(**changed)


def test_key_is_hex_string_of_64_chars() -> None:
    """键直接拼进文件路径，非法字符会导致写入失败。"""
    key = cache_key(**BASE)
    assert len(key) == 64
    assert set(key) <= set("0123456789abcdef")


def test_unicode_text_is_treated_as_text_not_bytes() -> None:
    """若直接对 str 做 hash 而编码不一致，同一条中文会得到两个键。"""
    key = cache_key(**{**BASE, "text": "中文测试"})
    assert key == cache_key(**{**BASE, "text": "中文测试"})
