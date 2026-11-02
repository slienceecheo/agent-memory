## MODIFIED Requirements

### Requirement: 四特征重排

系统 SHALL 用三个特征对候选重排：融合分、来源权威、状态惩罚。
每个特征 MUST 返回 [0,1]，且 MUST 可单独关闭以支持消融。

`condition` MUST NOT 参与重排打分；它 MAY 只用于召回阶段的过滤与审计。

#### Scenario: 历史产物的特征数与当前不同

- **WHEN** 读 v2 的 15 份冻结结果（`47e4785-dirty`）
- **THEN** 它们是用**四个**特征跑的（含 `condition` 权重），与本版本的三个特征不同构

- **AND** 用本版本代码读 v2 结果文件 MUST 被视为**跨版本误用**，而不是"解析失败"

- **AND** MUST NOT 为了兼容 v2 产物而保留 `condition` 权重——那会让"三特征"重新变成四特征

- **AND** 复算 v2 的数字 MUST 使用 v2 的代码状态，MUST NOT 用本版本的 `recompute_order`

| 版本 | 排序特征 | `weights` 字段 |
|---|---|---|
| v2 产物（`results/*.json`，冻结） | 4（含 `condition`） | 四元组 |
| **本版本** | **3**（无 `condition`） | 三元组 |

#### Scenario: 基础项为融合分
- **WHEN** 只有融合分特征启用
- **THEN** 排序与纯 RRF 完全一致

#### Scenario: 条件匹配
- **WHEN** 查询带条件，候选分为条件相同与不同，其余三个特征相同
- **THEN** 两者重排得分相同——该特征不参与打分，只在召回阶段做过滤

#### Scenario: 条件缺失时为中性
- **WHEN** 查询或候选任一方无条件
- **THEN** 该情形不产生任何排序贡献（原先的 `0.5` 中性值不再参与打分）

#### Scenario: 来源权威
- **WHEN** 两条候选融合分相同但来源权威不同
- **THEN** 权威更高者排前

#### Scenario: 状态惩罚
- **WHEN** 候选包含冲突或已取代的条目
- **THEN** 其状态惩罚分低于 ACTIVE 条目

#### Scenario: 特征值域
- **WHEN** 任一特征对任一候选取值
- **THEN** 结果落在 [0,1]，越界即报错

#### Scenario: 权重和为 1
- **WHEN** 提供一组权重
- **THEN** 其和必须为 1（容差 1e-6），否则拒绝

#### Scenario: 全部特征关闭

> **场景名沿用旧名**：OpenSpec 的 MODIFIED 不允许丢弃已有场景
> （实测：`omits scenario(s) the current spec still has: "全部特征关闭"`），
> 所以名字保留，内容改为事实。**这个状态实际上不可构造**——见下方。

- **WHEN** 尝试把三个权重全部设为 0
- **THEN** 系统 MUST 拒绝并报错（权重之和必须为 1）

- **AND** 本项目 MUST NOT 提供"三个特征全部关闭"的构造方式：
  权重和恒为 1，而三个都关意味着和为 0，两者不相容

- **AND** `disabled_weights()` 的语义 MUST 是"**只开融合分**"
  （`base=1, authority=0, status=0`），MUST NOT 被描述为"全部关闭"

- **AND** 若需要"退化为融合分排序"这一行为，MUST 用"只开 base"表达，
  MUST NOT 用"全部关闭"表达

