"""条件槽位抽取与匹配。

**为什么是硬编码词表而不是模型抽取**：条件匹配每次查询都要算，
模型抽取成本高、不可复现（缓存键会随查询爆炸）。
硬编码词表的失败是**可见的**（`structured=False` 比例上升），可修。

**中英双向是必需的**：实测三份场景文件里，dev/test 用英文 token
（`coding`、`prod`、`night`），independent 用中文（`法定节假日`、`客户应酬`）。
单向词表会让跨语言比较永远不匹配。

匹配规则：
- 两侧都为空 → 0.5（中性，不是 1.0——"都无条件"不该压过"条件匹配"）
- 一方为空 → 0.5（"没说条件"不等于"条件不符"）
- 双方非空 → 槽位集合的 Jaccard
"""

from __future__ import annotations

from dataclasses import dataclass

# 规范槽位：`类别:取值`。中英表达归一到同一个。
_ALIASES: dict[str, str] = {
    # 活动
    "coding": "activity:coding",
    "写代码": "activity:coding",
    "编程": "activity:coding",
    "开发": "activity:coding",
    "meeting": "activity:meeting",
    "开会": "activity:meeting",
    "会议": "activity:meeting",
    "client_dinner": "activity:client_dinner",
    "客户应酬": "activity:client_dinner",
    "应酬": "activity:client_dinner",
    "review": "activity:review",
    "评审": "activity:review",
    "refactor": "activity:refactor",
    "重构": "activity:refactor",
    "feature": "activity:feature",
    "功能开发": "activity:feature",
    "rush": "activity:rush",
    "赶进度": "activity:rush",
    "送孩子上学": "activity:school_run",
    "回爸妈家": "activity:visit_parents",
    # 环境
    "prod": "env:production",
    "production": "env:production",
    "生产": "env:production",
    "线上": "env:production",
    "dev": "env:development",
    "development": "env:development",
    "开发环境": "env:development",
    "local": "env:local",
    "本地": "env:local",
    "small": "env:small",
    "小项目": "env:small",
    "large": "env:large",
    "大项目": "env:large",
    "frontend": "env:frontend",
    "前端": "env:frontend",
    "backend": "env:backend",
    "后端": "env:backend",
    "在自己家": "env:home",
    # 时间
    "morning": "time:morning",
    "早上": "time:morning",
    "上午": "time:morning",
    "night": "time:night",
    "深夜": "time:night",
    "晚上": "time:night",
    "day": "time:day",
    "白天": "time:day",
    "holiday": "time:holiday",
    "节假日": "time:holiday",
    "法定节假日": "time:holiday",
    "weekly": "time:weekly",
    "每周": "time:weekly",
    "平时": "time:normal",
    "日常": "time:normal",
    "normal": "time:normal",
}

_SLOT_ORDER = ("activity", "env", "time", "raw")


@dataclass(frozen=True, slots=True)
class ParsedCondition:
    slots: frozenset[str]
    structured: bool

    @property
    def is_empty(self) -> bool:
        return not self.slots


def parse_condition(value: str | ParsedCondition | None) -> ParsedCondition:
    """把自由文本条件归一为槽位集合。

    未登记的表达整体保留为一个 `raw:` 槽位并标记 `structured=False`，
    这样"词表覆盖率"可被统计——而不是静默给出中性分。
    """
    if isinstance(value, ParsedCondition):
        return value

    if value is None:
        return ParsedCondition(slots=frozenset(), structured=True)

    text = value.strip()
    if not text:
        return ParsedCondition(slots=frozenset(), structured=True)

    folded = text.casefold()
    slots: set[str] = set()

    for alias, slot in _ALIASES.items():
        if alias.casefold() in folded:
            slots.add(slot)

    if slots:
        return ParsedCondition(slots=frozenset(slots), structured=True)

    # 未登记：整体保留
    return ParsedCondition(slots=frozenset({f"raw:{text}"}), structured=False)


def condition_match(
    left: str | ParsedCondition | None,
    right: str | ParsedCondition | None,
) -> float:
    """两个条件的匹配度，落在 [0, 1]。

    两侧任一为空 → 0.5（中性）。理由：
    - 两侧都空时给 1.0 会让"无条件"压过真正的条件匹配
    - 一方空时给 0.0 会把"没提条件"误判成"条件不符"
    """
    a = parse_condition(left)
    b = parse_condition(right)

    if a.is_empty or b.is_empty:
        return 0.5

    union = a.slots | b.slots
    if not union:
        return 0.5
    return len(a.slots & b.slots) / len(union)
