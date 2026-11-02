# Spec Delta

## MODIFIED Requirements

### Requirement: 四特征重排

> **标题沿用旧名，阅读时以正文为准。** 这条 requirement 的标题是 `MODIFIED`
> 的匹配键，改名会让归档拒绝本次 delta（实测：
> `memory-retrieval MODIFIED failed for header "### Requirement: 三特征重排" - not found`）。
> 而正文已改为三特征——**标题与正文的这处不一致是已知的，且只有一处**。

系统 SHALL 用三个特征对候选重排：融合分、来源权威、状态惩罚。
每个特征 MUST 返回 [0,1]，且 MUST 可单独关闭以支持消融。

`condition` MUST NOT 参与重排打分；它 MAY 只用于召回阶段的过滤与审计。

**与历史产物的关系**：v2 的 15 份冻结结果（`47e4785-dirty`）
是用**四个**特征跑的，其中包含 `condition` 权重。它们**不适用于本版本**：

| 版本 | 排序特征 | `weights` 字段 |
|---|---|---|
| v2 产物（`results/*.json`，冻结） | 4（含 `condition`） | 四元组 |
| **本版本** | **3**（无 `condition`） | 三元组 |

所以：

- 用本版本代码读 v2 结果文件 MUST 被视为**跨版本误用**，而不是"解析失败"
- 不得为了兼容 v2 产物而保留 `condition` 权重——那会让"三特征"重新变成四特征
- 复算 v2 的数字 MUST 使用 v2 的代码状态，不得用本版本的 `recompute_order`

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
- **WHEN** 三个特征全部关闭
- **THEN** 退化为融合分排序，且不因权重校验失败

### Requirement: 条件槽位抽取

系统 SHALL 把自由文本条件归一为结构化槽位，且**写入侧与查询侧 MUST 使用同一套词表**。
抽取结果 MUST NOT 参与重排打分，只用于召回阶段的过滤与审计。

#### Scenario: 常见条件被识别
- **WHEN** 条件包含时间、场景、环境类表达
- **THEN** 抽出对应的槽位键值

#### Scenario: 中英表达归一到同一槽位
- **WHEN** 同一条件以中文与英文分别表达（如"应酬"与"client_dinner"）
- **THEN** 归一到相同的槽位键

#### Scenario: 无法识别时整体保留
- **WHEN** 条件不含任何已知表达
- **THEN** 原文作为一个槽位保留，并标记未结构化

#### Scenario: 未结构化比例可统计
- **WHEN** 汇总一批条件
- **THEN** 能报出 `structured=False` 的比例

#### Scenario: 槽位匹配用重叠度
- **WHEN** 两侧都有结构化槽位
- **THEN** 按键值集合的 Jaccard 计算匹配度

#### Scenario: 不参与排序
- **WHEN** 两条候选的三个排序特征值完全相同，仅条件不同
- **THEN** 两者的重排得分相同
