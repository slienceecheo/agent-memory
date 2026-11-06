"""三特征重排。

`final = w_base·base + w_auth·authority + w_cosine·cosine`

三个特征的定义与值域（**每个都必须落在 [0,1]**，越界即报错）：

| 特征 | 含义 | 为什么有方差 |
|---|---|---|
| `base` | RRF 分数按最大值归一 | 融合分数天然不同 |
| `authority` | 来源权威归一 | 独立集里 9 条 third_party、2 条 system_inferred |
| `cosine` | 查询与候选的向量余弦 | 语义相似度，不依赖字面重叠 |

**`condition` 是审计字段，不参与加权。**
`FeatureScores` 仍保留 `condition` 字段（**结构即事实**：它记录了"这条候选与查询条件
匹配到什么程度"），但 `RerankWeights` 没有对应权重，`rerank()` 也不加它。

为什么退出加权：v2 的消融实测显示，去掉 condition 后 A 轴 `SEH@1` 从 0.900 掉到 0.300
——**那个 0.600 的"贡献"里混着"查询侧能不能拿到条件"这个上游问题**，
而不是排序本身的能力差异。把权重留着等于让一个测不准的量继续影响排序。

**已删除的三个特征**（审查实测它们在 ACTIVE-only 上恒为常数）：

- `temporal_validity`：所有召回路径只返回 ACTIVE，恒为 1.0
- `recency`：场景文件没有时间字段，全部同一 `BASE_TIME`
- `status`：同 `temporal_validity`——三条召回路径只返回 `ACTIVE`，池内恒 1.0

留着它们只会让"重排有效"看起来成立，实际上是排序没变。

**为什么两个 dataclass 都用 `kw_only=True`**（本项目唯一这样做的）：

字段含义在版本间变过。`RerankWeights` 的第三位：`condition` → `status` → `cosine`；
`FeatureScores` 的第四位：`status` → `cosine`。位置参数会让"看起来配了 cosine"的
代码实际配的是别的字段，而且**不报错**。
`FeatureScores` 还多一层：它的字段顺序是 `base`/`condition`/`authority`/`cosine`，
而产物 `features` 的键是 `base`/`authority`/`cosine`——`condition` 夹在中间且不进产物。
所以"按位置对应"从一开始就是错的。

其它 dataclass（如 `Check`）仍用位置参数，因为它们的字段含义从未变过。
**"字段含义会变"才是 `kw_only` 的理由，不是"位置参数不好"。**
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol

from memory.retrieval.condition import condition_match
from memory.retrieval.fusion import DEFAULT_K
from memory.store.models import Authority, Status

_UNIT_TOLERANCE = 1e-6


@dataclass(frozen=True, slots=True, kw_only=True)
class RerankWeights:
    base: float
    authority: float
    cosine: float

    def __post_init__(self) -> None:
        values = (self.base, self.authority, self.cosine)
        if any(value < 0.0 for value in values):
            raise ValueError(f"权重不能为负：{values}")
        total = sum(values)
        if abs(total - 1.0) > _UNIT_TOLERANCE:
            raise ValueError(
                f"权重之和必须为 1（当前为 {total:.6f}）。"
                "和为 1 才能让'全关'与'全开'的分数可比。"
            )

    def total(self) -> float:
        return self.base + self.authority + self.cosine


def disabled_weights() -> RerankWeights:
    """关闭除融合分外的全部特征。

    极端权重在构造函数里合法（`RerankWeights(base=1, authority=0, cosine=0)`），
    因为消融实验需要"只有 base"这类情形。
    """
    return RerankWeights(base=1.0, authority=0.0, cosine=0.0)


#: 缺陷 19/21 的载体：authority 仍有非零权重时，罚分能否推翻 base 优势。
#:
#: **必须独立于 `PREREGISTERED_WEIGHTS`**：那张表随实验设计变，
#: 而"缺陷是否成立"只在缺陷算术需要重新验证时才该变。
#: 绑在一起会让"换一组实验配置"意外地改变一个独立结论。
#:
#: 先例：`test_authority_weight_threshold_is_quantified` 一直用独立权重，
#: 所以预注册表改名/改值时它不受影响。
DEFECT18_WEIGHTS = RerankWeights(base=0.2, authority=0.2, cosine=0.6)


#: 默认权重的数值。`uniform` 与 `mixed` 共用它，避免两份数字各自漂移。
#:
#: **0.2/0.2/0.6 不是"随手调的数字"**：它等于 `mixed`，即"给无信号项留余量"的配置。
#: 选它作默认的理由与选 `mixed` 作稳健性对照相同——比 `cosine_only` 保守。
_DEFAULT_WEIGHTS = RerankWeights(base=0.2, authority=0.2, cosine=0.6)


PREREGISTERED_WEIGHTS: dict[str, RerankWeights] = {
    # `uniform` 是**历史遗留接口名**，它从未在 v3 里"均匀"过：
    # 四特征时代 0.25×4（唯一一次），三特征时代 0.4/0.3/0.3，现在 0.2/0.2/0.6。
    #
    # **为什么不改名**：`weights_name="uniform"` 有 48 处调用，
    # 其中 44 处不依赖具体数值（只依赖"这个名字存在且是一组合法权重"）。
    # 改名会产生与判据无关的 diff。而"它不均匀"这件事写在
    # `evaluation-harness` 的 spec 里，不靠名字暗示。
    "uniform": _DEFAULT_WEIGHTS,
    # 与默认同值，但**独立的键**：它回答"给无信号项留余量会损失多少"，
    # 是稳健性对照。哪天默认改了，它仍应指向 0.2/0.2/0.6。
    "mixed": _DEFAULT_WEIGHTS,
    # 上界配置：只用有信号的特征能做到多好。
    "cosine_only": RerankWeights(base=0.0, authority=0.0, cosine=1.0),
    # 已删除：
    # - `status_only`：指向已不存在的特征
    # - `base_heavy` / `auth_heavy`：描述的信号已被证否
    #   （base 恒等于融合顺序；authority 是分层过滤器而非信号）
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
    """状态映射。**保留作测量工具**，不参与加权。

    它的用途是证明"当前池内 status 无方差"——
    `test_effective_feature_count` 用它算出池内取值集合 == `{1.0}`，
    从而证明"4 个观测字段里只有 3 个有效特征"。

    删掉这个映射会让那个结论失去计算依据。
    """
    return _STATUS_SCORE[status]


def condition_score(query_condition: str | None, item_condition: str | None) -> float:
    return condition_match(query_condition, item_condition)


# ---------- 组合 ----------


@dataclass(frozen=True, slots=True, kw_only=True)
class FeatureScores:
    base: float
    condition: float
    authority: float
    cosine: float


class Rerankable(Protocol):
    item_id: str
    features: FeatureScores


@dataclass(frozen=True, slots=True)
class Ranked:
    item_id: str
    score: float
    features: FeatureScores


def _validate(features: FeatureScores) -> None:
    for name in ("base", "condition", "authority", "cosine"):
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
            + weights.cosine * features.cosine
        )
        scored.append(
            Ranked(item_id=candidate.item_id, score=total, features=features)
        )

    # 只按分数排；并列保持输入顺序（stable sort）。
    scored.sort(key=lambda item: -item.score)
    return scored


__all__ = [
    "DEFAULT_K",
    "DEFECT18_WEIGHTS",
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
