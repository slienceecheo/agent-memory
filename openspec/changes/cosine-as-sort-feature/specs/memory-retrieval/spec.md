## MODIFIED Requirements

### Requirement: 四特征重排

系统 SHALL 用三个特征对候选重排：融合分、来源权威、语义相似度（`cosine`）。
每个特征 MUST 返回 [0,1]，且 MUST 可单独关闭以支持消融。

`condition` MUST NOT 参与重排打分；它 MAY 只用于召回阶段的过滤与审计。
`status` MUST NOT 参与重排打分：三条召回路径只返回 `ACTIVE`，它在候选池内恒为常数。

#### Scenario: 历史产物的特征数与当前不同

- **WHEN** 读 v2 的 15 份冻结结果（`47e4785-dirty`）
- **THEN** 它们是用**四个**特征跑的（含 `condition` 权重），与本版本的三个特征不同构

- **AND** 用本版本代码读 v2 结果文件 MUST 被视为**跨版本误用**，而不是"解析失败"

- **AND** MUST NOT 为了兼容 v2 产物而保留 `condition` 权重——那会让"三特征"重新变成四特征

- **AND** 复算 v2 的数字 MUST 使用 v2 的代码状态，MUST NOT 用本版本的 `recompute_order`

| 版本 | 排序特征 | `weights` 字段 |
|---|---|---|
| v2 产物（`results/*.json`，冻结） | 4（含 `condition`） | 四元组 |
| v3 三项装置（归档历史） | 3（`base` / `authority` / `status`） | 三元组 |
| **本版本** | **3**（`base` / `authority` / `cosine`） | 三元组 |

**第二行是历史记录，不是当前行为**：`status` 恒为 1.0，它在三项装置里占的权重是空的。
把这一行留在表里，是为了让"同一句'三元组'在两个装置下含义不同"这件事可见。

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

> **场景名沿用旧名**：OpenSpec 的 MODIFIED 不允许丢弃已有场景。
> 内容改为事实：这个量仍有映射，但**不再参与排序**。

- **WHEN** 候选包含冲突或已取代的条目
- **THEN** 该条目的 `status_score` MUST 低于 ACTIVE 条目（映射仍然存在且有序）

- **AND** 该映射 MUST NOT 进入重排得分：`RerankWeights` MUST NOT 有 `status` 字段

**为什么保留这个映射**：它是证明"当前池内 `status` 无方差"的工具——
`test_effective_feature_count` 用 `status_score` 算出池内取值集合 == `{1.0}`，
从而证明"4 个观测字段里只有 3 个有效特征"。
删掉映射会让那个结论失去计算依据。

**为什么保留场景名**：删除一个已存在的场景会被 `openspec validate` 拒绝
（`omits scenario(s) the current spec still has`），而改名同样视为删除。

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
  （`base=1, authority=0, cosine=0`），MUST NOT 被描述为"全部关闭"

- **AND** 若需要"退化为融合分排序"这一行为，MUST 用"只开 base"表达，
  MUST NOT 用"全部关闭"表达
