"""commit ③ 的权重命名测试（先红）。

对应 tasks 4.0a / 4.0b。
"""

from __future__ import annotations


def test_preregistered_names_describe_questions() -> None:
    """预注册的组名必须描述"回答什么问题"，不是"数值形状"。

    - `uniform`：历史遗留接口名（默认配置）。**它从未在 v3 里"均匀"过**。
    - `mixed`：给无信号项留余量会损失多少（稳健性对照）。
    - `cosine_only`：只用有信号的特征能做到多好（上界，主配置）。

    删除 `base_heavy` / `auth_heavy` / `status_only`：
    前两个描述的信号已被证否，第三个指向已不存在的特征。
    """
    from memory.retrieval.rerank import PREREGISTERED_WEIGHTS

    assert set(PREREGISTERED_WEIGHTS) == {"uniform", "mixed", "cosine_only"}, (
        f"预注册名字是 {sorted(PREREGISTERED_WEIGHTS)}，"
        "应为 uniform/mixed/cosine_only"
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


def test_mixed_and_default_are_the_same_value_but_distinct_keys() -> None:
    """`mixed` 与默认同值，但必须是**两个键**。

    **为什么不合并成一个键**：`uniform` 是"默认"这个接口，
    `mixed` 是"留余量"这个语义。生命周期不同——
    哪天默认改成 `cosine_only`，`mixed` 仍然应该指向 0.2/0.2/0.6。
    合并会让"改默认"自动改掉语义名。

    **这条断言的写法是"值相等"**：它们本来就该相等（同一个算术问题）。
    独立性不靠值不等来证明——那由
    `test_feature_set_cosine.py::test_defect18_carrier_is_independent_of_preregistered`
    的行为断言守（清空表后缺陷算术不变）。
    """
    from memory.retrieval.rerank import PREREGISTERED_WEIGHTS

    default = PREREGISTERED_WEIGHTS["uniform"]
    mixed = PREREGISTERED_WEIGHTS["mixed"]

    assert (default.base, default.authority, default.cosine) == (
        mixed.base,
        mixed.authority,
        mixed.cosine,
    ), "默认与 mixed 当前应当同值（同一个算术问题）"


def test_removed_names_are_gone() -> None:
    """`status_only` 等名字必须消失——它们指向已不存在或已被证否的特征。"""
    from memory.retrieval.rerank import PREREGISTERED_WEIGHTS

    for gone in ("status_only", "auth_heavy", "base_heavy"):
        assert gone not in PREREGISTERED_WEIGHTS, (
            f"{gone} 仍在预注册表里。"
            "status_only 指向已删除的特征；"
            "auth_heavy/base_heavy 描述的信号已被证否（过滤器 / 等同融合顺序）"
        )
