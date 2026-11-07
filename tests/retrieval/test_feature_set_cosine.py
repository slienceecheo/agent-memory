"""commit ① 的测试（TDD 红灯阶段）。

对应 tasks 1.1 / 1.2 / 1.3 / 1.4 / 1.4b / 1.5 / 1.6。

**这些测试在改动前应当红**：
- 1.1/1.2/1.3/1.4b 会因为 FeatureScores/RerankWeights 还是旧字段而红
- 1.5/1.6 会因为 DEFECT18_WEIGHTS 不存在而 ImportError
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


# ---------- 1.1 / 1.2 字段集 ----------


def test_feature_scores_has_cosine_not_status() -> None:
    """`FeatureScores` 是**观测**：base / condition / authority / cosine。

    `status` 删除（池内恒 1.0，见 `recall-active-only-contract`）；
    `cosine` 加入。`condition` 保留为审计字段。
    """
    from memory.retrieval.rerank import FeatureScores

    fields = set(FeatureScores.__dataclass_fields__)

    assert fields == {"base", "condition", "authority", "cosine"}, (
        f"FeatureScores 字段是 {sorted(fields)}，"
        "应为 base/condition/authority/cosine"
    )
    assert "status" not in fields, (
        "FeatureScores 仍有 status——恒常数字段不得作为观测保留"
    )


def test_rerank_weights_has_cosine_not_status() -> None:
    """`RerankWeights` 是**策略**：base / authority / cosine（三权重）。"""
    from memory.retrieval.rerank import RerankWeights

    fields = set(RerankWeights.__dataclass_fields__)

    assert fields == {"base", "authority", "cosine"}, (
        f"RerankWeights 字段是 {sorted(fields)}，应为 base/authority/cosine"
    )
    assert "status" not in fields
    assert "condition" not in fields, "condition 不得重新进入加权"


# ---------- 1.3 加权式 ----------


def test_rerank_uses_three_features() -> None:
    """cosine 变化必须改变排序——证明它真的进了加权。"""
    from memory.retrieval.rerank import FeatureScores, RerankWeights, rerank

    class _C:
        def __init__(self, item_id: str, feats: FeatureScores) -> None:
            self.item_id = item_id
            self.features = feats

    # base 与 authority 相同，只有 cosine 不同
    low = _C("low", FeatureScores(base=0.5, condition=0.0, authority=0.5, cosine=0.1))
    high = _C("high", FeatureScores(base=0.5, condition=0.0, authority=0.5, cosine=0.9))

    w = RerankWeights(base=0.0, authority=0.0, cosine=1.0)
    order = [r.item_id for r in rerank([low, high], weights=w)]

    assert order == ["high", "low"], (
        f"按 cosine 排序得到 {order}，应为 ['high', 'low']。"
        "cosine 没进加权式？"
    )


def test_condition_still_does_not_affect_score() -> None:
    """`condition` 仍是审计字段：改它不改变得分。"""
    from memory.retrieval.rerank import FeatureScores, RerankWeights, rerank

    class _C:
        def __init__(self, item_id: str, feats: FeatureScores) -> None:
            self.item_id = item_id
            self.features = feats

    w = RerankWeights(base=0.5, authority=0.25, cosine=0.25)
    lo = _C("x", FeatureScores(base=0.5, condition=0.0, authority=1.0, cosine=0.5))
    hi = _C("x", FeatureScores(base=0.5, condition=1.0, authority=1.0, cosine=0.5))

    assert rerank([lo], weights=w)[0].score == pytest.approx(
        rerank([hi], weights=w)[0].score
    ), "condition 又影响了得分"


# ---------- 1.4 rerank 函数体不再引用 status ----------


def test_status_score_is_not_in_rerank() -> None:
    """`rerank()` 的函数体不得引用 `features.status` / `weights.status`。

    **判据定位到函数体**，不是整个文件：
    `status_score()` 与 `_STATUS_SCORE` 要保留（它们是测量工具）。
    """
    src = (ROOT / "src" / "memory" / "retrieval" / "rerank.py").read_text(
        encoding="utf-8"
    )
    tree = ast.parse(src)

    body = None
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == "rerank":
            body = ast.get_source_segment(src, node) or ""
            break

    assert body is not None, "找不到 rerank() 函数"
    assert "features.status" not in body, "rerank() 仍读 features.status"
    assert "weights.status" not in body, "rerank() 仍读 weights.status"


# ---------- 1.4b kw_only ----------


def test_rerank_weights_reject_positional_args() -> None:
    """位置参数必须 `TypeError`。

    **理由**：第三个字段的含义在三个版本里变过三次
    （`condition` → `status` → `cosine`）。位置参数会让
    "看起来配了 cosine" 的代码实际配的是别的字段。
    """
    from memory.retrieval.rerank import RerankWeights

    with pytest.raises(TypeError, match="positional"):
        RerankWeights(0.4, 0.3, 0.3)  # type: ignore[misc]


def test_feature_scores_reject_positional_args() -> None:
    """`FeatureScores` 同型，而且更根本：它的字段顺序与产物键序本来就不一致。

    字段：`base` / **`condition`** / `authority` / `cosine`
    产物：`base` / `authority` / `cosine`（`condition` 不进 `features`）
    所以"按位置对应"从一开始就是错的。
    """
    from memory.retrieval.rerank import FeatureScores

    with pytest.raises(TypeError, match="positional"):
        FeatureScores(0.5, 0.0, 1.0, 1.0)  # type: ignore[misc]


# ---------- 1.5 / 1.6 缺陷载体 ----------


def test_defect18_numbers_match_weights() -> None:
    """缺陷 19 的三个数必须由 `DEFECT18_WEIGHTS` 算出。

    `d_base = 1.000 - 0.910` 写死在这里：它是**数据属性**，不是权重属性。
    """
    from memory.retrieval.rerank import DEFECT18_WEIGHTS

    w = DEFECT18_WEIGHTS
    d_base = 1.000 - 0.910

    advantage = w.base * d_base
    penalty = w.authority * (1.00 - 0.00)

    assert advantage == pytest.approx(0.0180, abs=1e-4)
    assert penalty == pytest.approx(0.2000, abs=1e-4)
    assert penalty - advantage == pytest.approx(0.1820, abs=1e-4)
    assert penalty > advantage, "结构断言：缺陷 19 必须仍然成立"


def test_defect18_carrier_is_independent_of_preregistered() -> None:
    """清空预注册表后，缺陷算术必须一字不变——这就是"独立"的定义。

    **不能写 `DEFECT18_WEIGHTS != PREREGISTERED_WEIGHTS["uniform"]`**：
    两者当前同值（0.2/0.2/0.6），那个断言在正确实现上也会红。
    值相等是设计意图（回答同一个算术问题）；耦合与否是**读取路径**的问题。
    判据是 `is`，不是 `!=`——见
    `test_preregistered_naming.py::test_anchor_does_not_follow_the_default`。
    """
    from memory.retrieval import rerank as rr

    original = dict(rr.PREREGISTERED_WEIGHTS)
    try:
        # 把预注册表全部换成 base-only：若缺陷算术跟着变，说明它读了这张表
        rr.PREREGISTERED_WEIGHTS.clear()
        rr.PREREGISTERED_WEIGHTS["uniform"] = rr.RerankWeights(
            base=1.0, authority=0.0, cosine=0.0
        )

        w = rr.DEFECT18_WEIGHTS
        advantage = w.base * (1.000 - 0.910)
        penalty = w.authority * (1.00 - 0.00)

        assert advantage == pytest.approx(0.0180, abs=1e-4), (
            "预注册表被改后 base 优势变了——缺陷载体读了 PREREGISTERED_WEIGHTS"
        )
        assert penalty == pytest.approx(0.2000, abs=1e-4)
    finally:
        rr.PREREGISTERED_WEIGHTS.clear()
        rr.PREREGISTERED_WEIGHTS.update(original)
