"""评测指标。

`substring_exact_match` 对齐 MemoryAgentBench 的官方口径：
标准答案作为预测答案的子串出现即为命中，比较前做 NFKC 归一与大小写折叠。

两处刻意的严格：
- 空标准答案直接报错，而不是返回 False——静默返回会让分数虚高。
- 空/None 预测返回 False，而不是抛异常——一条坏样本不该中断整批。
"""

from __future__ import annotations

import unicodedata


def _normalize(text: str) -> str:
    """NFKC 归一（全角→半角）后去首尾空白并折叠大小写。"""
    return unicodedata.normalize("NFKC", text).strip().casefold()


def substring_exact_match(gold: str, prediction: str | None) -> bool:
    normalized_gold = _normalize(gold)
    if not normalized_gold:
        raise ValueError("标准答案为空，无法进行子串匹配；请检查数据或过滤该样本。")
    if prediction is None:
        return False
    normalized_prediction = _normalize(prediction)
    if not normalized_prediction:
        return False
    return normalized_gold in normalized_prediction
