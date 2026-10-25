"""四特征重排。

`final = w_base·base + w_cond·condition + w_auth·authority + w_status·status`

四个特征的定义与值域（**每个都必须落在 [0,1]**，越界即报错）：

| 特征 | 含义 | 为什么有方差 |
|---|---|---|
| `base` | RRF 分数按最大值归一 | 融合分数天然不同 |
| `condition` | 查询条件与候选条件的槽位匹配度 | 30/90 条有条件，其余中性 0.5 |
| `authority` | 来源权威归一 | 独立集里 9 条 third_party、2 条 system_inferred |
| `status` | ACTIVE > CONFLICTED > SUPERSEDED | 冲突候选进池时有差异 |

**已删除的两个特征**（审查实测它们在 ACTIVE-only 上恒为常数）：

- `temporal_validity`：所有召回路径只返回 ACTIVE，恒为 1.0
- `recency`：场景文件没有时间字段，全部同一 `BASE_TIME`

留着它们只会让"重排有效"看起来成立，实际上是排序没变。
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol

from memory.retrieval.condition import condition_match
from memory.retrieval.fusion import DEFAULT_K
from memory.store.models import Authority, Status

_UNIT_TOLERANCE = 1e-6


@dataclass(frozen=True, slots=True)
class RerankWeights:
    base: float
    condition: float
    authority: float
    status: float

    def __post_init__(self) -> None:
        values = (self.base, self.condition, self.authority, self.status)
        if any(value < 0.0 for value in values):
            raise ValueError(f"权重不能为负：{values}")
        total = sum(values)
        if abs(total - 1.0) > _UNIT_TOLERANCE:
            raise ValueError(
                f"权重之和必须为 1，当前为 {total:.6f}。"
                "和为 1 才能让'全关'与'全开'的分数可比。"
            )

    def total(self) -> float:
        return self.base + self.condition + self.authority + self.status


def disabled_weights() -> RerankWeights:
    """全特征关闭：只剩基础项。

    走独立分支而不是 `RerankWeights(1,0,0,0)`，
    因为后者会让人误以为"只开 base"是特殊情况，
    而实际上它是消融的一个端点。
    """
    return RerankWeights(base=1.0, condition=0.0, authority=0.0, status=0.0)


PREREGISTERED_WEIGHTS: dict[str, RerankWeights] = {
    "uniform": RerankWeights(base=0.25, condition=0.25, authority=0.25, status=0.25),
    "base_heavy": RerankWeights(base=0.7, condition=0.1, authority=0.1, status=0.1),
    "cond_heavy": RerankWeights(base=0.2, condition=0.6, authority=0.1, status=0.1),
    "auth_heavy": RerankWeights(base=0.2, condition=0.1, authority=0.6, status=0.1),
    "status_only": RerankWeights(base=0.2, condition=0.1, authority=0.1, status=0.6),
}


# ---------- 单特征 ----------


def rrf_norm(score: float, *, max_score: float) -> float:
    """RRF 分数归一化到 [0,1]。"""
    if max_score <= 0.0:
        return 0.0
    return min(1.0, max(0.0, score / max_score))


_AUTHORITY_SCORE: dict[Authority, float] = {
    Authority.THIRD_PARTY: 0.0,
    Authority.SYSTEM_INFERRED: 0.33,
    Authority.USER_DOCUMENT: 0.66,
    Authority.USER_DIRECT: 1.0,
}


def authority_score(level: Authority) -> float:
    return _AUTHORITY_SCORE[level]


_STATUS_SCORE: dict[Status, float] = {
    Status.ACTIVE: 1.0,
    Status.CONFLICTED: 0.5,
    Status.SUPERSEDED: 0.2,
    Status.RETRACTED: 0.0,
}


def status_score(status: Status) -> float:
    return _STATUS_SCORE[status]


def condition_score(query_condition: str | None, item_condition: str | None) -> float:
    return condition_match(query_condition, item_condition)


# ---------- 组合 ----------


@dataclass(frozen=True, slots=True)
class FeatureScores:
    base: float
    condition: float
    authority: float
    status: float


class Rerankable(Protocol):
    item_id: str
    features: FeatureScores


@dataclass(frozen=True, slots=True)
class Ranked:
    item_id: str
    score: float
    features: FeatureScores


def _validate(features: FeatureScores) -> None:
    for name in ("base", "condition", "authority", "status"):
        value = getattr(features, name)
        if not 0.0 - _UNIT_TOLERANCE <= value <= 1.0 + _UNIT_TOLERANCE:
            raise ValueError(
                f"特征 {name} 的取值 {value} 不在 [0,1] 内。"
                "未限定值域时大数会压过任何权重，权重搜索因此失去意义。"
            )


def rerank(
    candidates: Sequence[Rerankable],
    *,
    weights: RerankWeights,
) -> list[Ranked]:
    """按权重加权求和并排序。并列时按 item_id 排序以保证可复现。"""
    scored: list[Ranked] = []
    for candidate in candidates:
        features = candidate.features
        _validate(features)
        total = (
            weights.base * features.base
            + weights.condition * features.condition
            + weights.authority * features.authority
            + weights.status * features.status
        )
        scored.append(
            Ranked(item_id=candidate.item_id, score=total, features=features)
        )

    scored.sort(key=lambda item: (-item.score, item.item_id))
    return scored


__all__ = [
    "DEFAULT_K",
    "PREREGISTERED_WEIGHTS",
    "FeatureScores",
    "Ranked",
    "RerankWeights",
    "authority_score",
    "condition_score",
    "disabled_weights",
    "rerank",
    "rrf_norm",
    "status_score",
]
