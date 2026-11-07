"""commit ③ 的权重命名测试（先红）。

对应 tasks 4.0a / 4.0b。
"""

from __future__ import annotations


def test_preregistered_names_describe_questions() -> None:
    """预注册的组名必须描述"回答什么问题"，不是"数值形状"。

    - `uniform`：历史遗留接口名（默认配置）。**它从未在 v3 里"均匀"过**。
    - `cosine_only`：只用有信号的特征能做到多好（上界，主配置）。

    **两组回答两个不同的问题**：默认 vs 上界。这就是预注册的全部意图。

    删除 `base_heavy` / `auth_heavy` / `status_only`：
    前两个描述的信号已被证否（base 等同融合顺序；authority 是分层过滤器），
    第三个指向已不存在的特征。

    删除 `mixed`：它与 `uniform` 是**同一个对象**（`is` 为 True），
    提供的对照信息为零；且它的名字与数据集轴 `Axis.MIXED` 撞车
    （见 `test_weight_names_do_not_collide_with_axis_values`）。
    """
    from memory.retrieval.rerank import PREREGISTERED_WEIGHTS

    assert set(PREREGISTERED_WEIGHTS) == {"uniform", "cosine_only"}, (
        f"预注册名字是 {sorted(PREREGISTERED_WEIGHTS)}，"
        "应为 uniform/cosine_only"
    )


def test_weight_names_do_not_collide_with_axis_values() -> None:
    """权重配置名不得与数据集轴值同名。

    **实测撞车**（本次删除 `mixed` 的理由之一）：

    | 层 | 定义位置 | `mixed` 的含义 |
    |---|---|---|
    | 数据集轴 | `evals/datasets/retrieval_v2.py` 的 `Axis.MIXED` | 混合两轴查询（A + C） |
    | 权重配置 | `RerankWeights` 的 `PREREGISTERED_WEIGHTS` 键 | （曾是）0.2/0.2/0.6 |

    两者同名、无关。`grep mixed` 一处返回两种东西。

    **判据必须写在测试里，不能写进 `rerank.py`**：
    `Axis` 属评测层，`rerank.py` 属产品层——产品不得依赖评测层。
    """
    from evals.datasets.retrieval_v2 import Axis

    from memory.retrieval.rerank import PREREGISTERED_WEIGHTS

    overlap = set(PREREGISTERED_WEIGHTS) & {a.value for a in Axis}
    assert not overlap, f"权重名与轴值撞车：{sorted(overlap)}"


def test_anchor_does_not_follow_the_default() -> None:
    """缺陷载体必须是**独立对象**，不是默认权重的别名。

    这两行字面量看起来重复，很容易被"优化"成
    `DEFECT18_WEIGHTS = _DEFAULT_WEIGHTS`。那样写语法正确、值也相同，
    但"改默认时锚点不动"这个性质会**静默消失**。

    **本条断言的是对象身份，不是数值**——数值本来就该相等。

    **前提**：`_DEFAULT_WEIGHTS` 是模块级单例。
    若将来改成"函数返回新实例"（如 `disabled_weights()` 那样），
    每次构造都会产生不同对象，`is not` 恒为真而判据失去意义。
    那时应改用行为断言：清空预注册表后 `DEFECT18_WEIGHTS` 仍可用
    （见 `test_feature_set_cosine.py::test_defect18_carrier_is_independent_of_preregistered`）。
    """
    from memory.retrieval import rerank as rr

    anchor = rr.DEFECT18_WEIGHTS
    default = rr.PREREGISTERED_WEIGHTS["uniform"]

    # 值本来就应该相等（同一个算术问题）
    assert (anchor.base, anchor.authority, anchor.cosine) == (
        default.base,
        default.authority,
        default.cosine,
    ), "缺陷载体与默认权重当前应当同值"

    # 但必须是两个对象
    assert anchor is not default, (
        "DEFECT18_WEIGHTS 变成了统一权重的别名——"
        "那样改默认时锚点会跟着变，"
        "『缺陷算术不随默认漂移』这个性质会静默消失。\n"
        "修法：写成独立字面量 `RerankWeights(base=..., authority=..., cosine=...)`。"
    )


def test_default_weights_are_the_preregistered_values() -> None:
    """默认权重必须是 0.2/0.2/0.6。

    **这不是"随手调的数字"**：它等于 `mixed`，也就是"给无信号项留余量"的配置。
    选它作默认的理由与选 `mixed` 作稳健性对照相同——它比 `cosine_only` 保守。
    """
    from memory.retrieval.rerank import PREREGISTERED_WEIGHTS

    w = PREREGISTERED_WEIGHTS["uniform"]

    assert (w.base, w.authority, w.cosine) == (0.2, 0.2, 0.6), (
        f"默认权重是 {(w.base, w.authority, w.cosine)}，应为 (0.2, 0.2, 0.6)"
    )


def test_cosine_only_is_the_upper_bound_config() -> None:
    """`cosine_only` 必须是 `(0, 0, 1)`——上界配置。"""
    from memory.retrieval.rerank import PREREGISTERED_WEIGHTS

    w = PREREGISTERED_WEIGHTS["cosine_only"]

    assert (w.base, w.authority, w.cosine) == (0.0, 0.0, 1.0)


def test_removed_names_are_gone() -> None:
    """`status_only` 等名字必须消失——它们指向已不存在或已被证否的特征。"""
    from memory.retrieval.rerank import PREREGISTERED_WEIGHTS

    for gone in ("status_only", "auth_heavy", "base_heavy"):
        assert gone not in PREREGISTERED_WEIGHTS, (
            f"{gone} 仍在预注册表里。"
            "status_only 指向已删除的特征；"
            "auth_heavy/base_heavy 描述的信号已被证否（过滤器 / 等同融合顺序）"
        )
