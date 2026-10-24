"""缓存键的生成规则。

键必须同时覆盖模型、维度、编码模式与原文，而且对文本统一按 UTF-8 编码，
避免同一段中文因编码方式不同产生不同的键。
"""

from __future__ import annotations

import hashlib

_SEPARATOR = "\x1f"  # 单元分隔符，正常文本不会出现，避免字段串味


def cache_key(*, model: str, dims: int, text_type: str, text: str) -> str:
    """生成内容寻址键。

    字段顺序固定，且用不可见分隔符连接，防止 ("ab", "c") 与 ("a", "bc") 撞键。
    """
    payload = _SEPARATOR.join((model, str(dims), text_type, text))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
