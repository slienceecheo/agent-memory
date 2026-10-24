"""内容指纹。

用途：判断"这次写入的内容是否与当前有效的那条一致"，从而决定 NOOP 还是新版本。

纳入指纹的字段及其理由：

| 字段 | 纳入 | 理由 |
|---|---|---|
| owner / scope / subject / relation / condition | 是 | 定位字段变了就是另一条事实 |
| value | 是 | 值变了当然不同 |
| authority | 是 | 用户自述与工单备注的可信度不同，不该互相吞并 |

刻意排除的字段及其理由：

| 字段 | 排除 | 理由 |
|---|---|---|
| session_id / turn_id | 是 | 同一事实换个会话说一遍，仍是同一事实 |
| recorded_at | 是 | 否则每次写入都不同，幂等失效 |
| status | 是 | 指纹描述内容，状态由幂等逻辑另行判断 |
| valid_from / valid_to | 是 | 同一事实的两个不重叠有效期属于"再就业"场景，由区间逻辑处理 |

最后一条尤其关键：若把 valid_from 纳入指纹，"重复确认同一事实"每次都会造新版本。
"""

from __future__ import annotations

import hashlib

from memory.store.models import MemoryItem

_SEP = "\x1f"  # 单元分隔符，正常文本不会出现，防止字段串味


def fingerprint(item: MemoryItem) -> str:
    """对条目的内容做内容寻址哈希。"""
    parts = (
        item.owner,
        item.scope.value,
        item.subject,
        item.relation,
        item.condition or "",
        item.value,
        item.authority.value,
    )
    return hashlib.sha256(_SEP.join(parts).encode("utf-8")).hexdigest()
