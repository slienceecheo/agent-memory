"""三特征重排。

`final = w_base·base + w_auth·authority + w_status·status`

三个特征的定义与值域（**每个都必须落在 [0,1]**，越界即报错）：

| 特征 | 含义 | 为什么有方差 |
|---|---|---|
| `base` | RRF 分数按最大值归一 | 融合分数天然不同 |
| `authority` | 来源权威归一 | 独立集里 9 条 third_party、2 条 system_inferred |
| `status` | ACTIVE > CONFLICTED > SUPERSEDED | 冲突候选进池时有差异 |

**`condition` 是审计字段，不参与加权。**
`FeatureScores` 仍保留 `condition` 字段（**结构即事实**：它记录了"这条候选与查询条件
匹配到什么程度"），但 `RerankWeights` 没有对应权重，`rerank()` 也不加它。

为什么退出加权：v2 的消融实测显示，去掉 condition 后 A 轴 `SEH@1` 从 0.900 掉到 0.300
——**那个 0.600 的"贡献"里混着"查询侧能不能拿到条件"这个上游问题**，
而不是排序本身的能力差异。把权重留着等于让一个测不准的量继续影响排序。

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
    authority: float
    status: float

    def __post_init__(self) -> None:
        values = (self.base, self.authority, self.status)
        if any(value < 0.0 for value in values):
            raise ValueError(f"权重不能为负：{values}")
        total = sum(values)
        if abs(total - 1.0) > _UNIT_TOLERANCE:
            raise ValueError(
                f"权重之和必须为 1（当前为 {total:.6f}）。"
                "和为 1 才能让'全关'与'全开'的分数可比。"
            )

    def total(self) -> float:
        return self.base + self.authority + self.status


def disabled_weights() -> RerankWeights:
    """关闭除融合分外的全部特征。

    极端权重在构造函数里合法（`RerankWeights(1,0,0)`），
    因为消融实验需要"只有 base"这类情形。
    """
    return RerankWeights(base=1.0, authority=0.0, status=0.0)


PREREGISTERED_WEIGHTS: dict[str, RerankWeights] = {
    # condition 退出排序后，原先的 cond_heavy 无意义，已移除。
    # uniform 从「四特征各 0.25」重算为「三特征 0.4/0.3/0.3」，
    # 保持 base 相对最高（融合分是主信号）。
    "uniform": RerankWeights(base=0.4, authority=0.3, status=0.3),
    "base_heavy": RerankWeights(base=0.8, authority=0.1, status=0.1),
    "auth_heavy": RerankWeights(base=0.2, authority=0.7, status=0.1),
    "status_only": RerankWeights(base=0.2, authority=0.1, status=0.7),
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
    """按权重加权求和并排序。

    **并列时保持输入顺序**（Python 的 `sorted` 是稳定排序）。
    调用方负责传入有语义的顺序。

    本函数**不提供并列裁决策略**。理由：早先的实现用 `item_id` 破并列，
    而 `item_id` 在不同调用方那里含义不同（在 `run_retrieval` 里是稳定 tag，
    在别处可能是 uuid）。而调用方拿到结果后会按自己的判据重排
    （见 `evals/run_retrieval.py` 的 `fused_position`），
    所以内部这个二级键**永远会被覆盖**。

    留着一个会被覆盖的判据是有害的：读代码的人会以为它在起作用。
    实测例子：`billing-c2` 上 tag 字典序与融合顺序恰好一致，
    于是无法从结果判断谁在裁决——这种不可归因的状态本身就是隐患。

    需要确定性的并列裁决时，由调用方传入已排好的顺序。
    """
    scored: list[Ranked] = []
    for candidate in candidates:
        features = candidate.features
        _validate(features)
        # condition 不参与加权：它是审计字段，不是排序策略（见 design D1）。
        total = (
            weights.base * features.base
            + weights.authority * features.authority
            + weights.status * features.status
        )
        scored.append(
            Ranked(item_id=candidate.item_id, score=total, features=features)
        )

    # 只按分数排；并列保持输入顺序（stable sort）。
    scored.sort(key=lambda item: -item.score)
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
