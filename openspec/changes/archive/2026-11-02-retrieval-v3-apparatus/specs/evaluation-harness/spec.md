# Spec Delta

## ADDED Requirements

### Requirement: 结果文件记录逐条特征分

检索评测的结果文件 MUST 为每条 case 记录三个排序特征：`base`、`authority`、`status`，置于 `features` 子对象。

`condition` MUST 单独记录在 `condition_score` 字段（数值或 `null`），不得放进 `features`。
它不参与排序，但它的分布是判断"条件是否可被查询侧获得"的唯一依据。

#### Scenario: 每条 case 的 features 含三个键

- **WHEN** 一次评测产生 N 条 case
- **THEN** 每条 case 的 `features` 恰好含 `base` / `authority` / `status` 三个数值字段

#### Scenario: condition_score 独立记录

- **WHEN** 一次评测产生 N 条 case
- **THEN** 每条 case 都含 `condition_score` 字段，值为数值或 `null`

#### Scenario: 字段缺失时拒绝写出

- **WHEN** 任一 case 的 `features` 缺键，或缺 `condition_score` 字段
- **THEN** 评测 MUST 报错，不得写出缺字段的结果文件

#### Scenario: gold 未召回时两侧同时表达

- **WHEN** 某条 case 的 gold 没有进入重排候选集
- **THEN** `features` MUST 为 `null`，**且** `features_by_tag` 里 MUST 不含 gold 的 tag

- **AND** MUST NOT 用 `{}` 表示未召回：`{}` 是"存在但没有键"的对象，与"不存在"无法区分

#### Scenario: 特征分足以复现名次

- **WHEN** 用结果文件中记录的 `features` 与当次权重重新计算得分并排序
- **THEN** 每条 case 的名次与记录中的 `rank_after_rerank` 完全一致

### Requirement: 结果产物的分区

评测产物 MUST 按来源分区存放，不得混在同一层。每个分区 MUST 在**分区清单**里显式登记，
并写明**由哪条检查负责**。

分区清单 MUST 与磁盘一致，两个方向都要断言：

| 方向 | 违反形式 |
|---|---|
| 清单覆盖磁盘 | 新增 `results/foo/` 而未登记 -> **必须失败** |
| 磁盘覆盖清单 | 登记了 `features/` 却从不创建 -> 允许（预留），但 MUST 写明"尚不存在" |

**不得用"一个文件属于几个分区"作为判据**：文件系统保证一个文件只能在一个目录里，
所以"互斥"在这个设计里没有可被违反的形式，是一条恒真约束。

#### Scenario: v2 档案只统计顶层

- **WHEN** 统计 v2 档案的分类数与总数
- **THEN** MUST 只统计 `results/*.json` 顶层，**不含任何子目录**

- **AND** 该数量 MUST 作为历史事实固定，不随新版本产物增长而改写

#### Scenario: v3 产物独立指纹

- **WHEN** `results/v3/` 出现结果文件
- **THEN** 每个文件 MUST 带指纹，且 MUST NOT 与 v2 档案的指纹相同

- **AND** 指纹相同 MUST 视为"这批结果是旧代码跑的"，而不是"指纹校验太严"

#### Scenario: 历史对照物不得并入当前批

- **WHEN** `results/archive/` 下的文件带指纹
- **THEN** 其指纹 MUST NOT 与当前批相同

- **AND** 它们 MUST NOT 被登记进当前批的指纹清单——**并入会让"当前批同源"这个断言失效**

#### Scenario: 未知分区必须拒绝

- **WHEN** `results/` 下出现未登记的子目录
- **THEN** 校验 MUST 失败，而不是静默忽略

- **AND** 判据 MUST NOT 依赖"该目录里恰好有 json"：空目录出现时也 MUST 失败，
  否则"目录存在但为空"是一个不可见的过渡状态

#### Scenario: 分区未就绪时的空转必须可见

- **WHEN** 某分区尚无文件，其校验无法执行
- **THEN** 该校验 MUST 跳过，且跳过消息 MUST 非空并写明"这不代表已通过"

- **AND** MUST 另有独立测试在临时目录上证明**同一判据会失败**，
  否则"空转"与"检查从不生效"在输出上无法区分

- **AND** "该独立测试存在"这件事本身 MUST 被断言——它被删掉时，
  主校验的跳过就重新变成永久跳过

#### Scenario: 有文件时不得跳过

- **WHEN** 某分区**已经有文件**
- **THEN** 该分区的主校验 MUST NOT 跳过；MUST 给出通过或失败

- **AND** 跳过条件 MUST 依赖**传入的目录**，MUST NOT 依赖某个全局常量所指向的真实目录。
  否则会出现"传临时目录时正常、生产路径上不跑"

- **AND** 判据 MUST 断言"分区非空时动作是 `run` 或 `fail` 之一"，
  MUST NOT 只断言"跳过消息非空"——后者在"检查根本没跑"时也成立

- **AND** 双向覆盖：本 scenario 管"分区有文件 -> 检查必须跑"；
  "文件 -> 必须被某分区覆盖"是另一条（见「未知分区必须拒绝」）

**为什么这条独立存在**：`skip` 与 `pass` 在 CI 输出里几乎一样（都是通过信号）。
而"检查没跑"有三种原因，处置完全不同：

| 原因 | 例子 | 处置 |
|---|---|---|
| 数据不存在 | v3 空目录 | 合理，允许 skip |
| 路径写错 | `dev.jsonl.jsonl` | 缺陷，必须红 |
| **条件写宽** | "依赖真实目录"而非"依赖传入目录" | **缺陷，且最隐蔽** |

第三种在你传临时目录时表现正常，只在生产路径上不跑——**本项目已出现过两次第一种误判、一次第三种雏形**。

## MODIFIED Requirements

### Requirement: 检索质量的度量

系统 SHALL 为检索任务提供 SEH@K、SRS 与四类失败归因，并 MUST 同时给出
样本数与配对 bootstrap 区间。系统 MUST 记录每次评估中各召回路径的返回条数，
使"路径参与测量"与"路径空转"可区分。

#### Scenario: SEH@K 的定义
- **WHEN** 计算某 K 值的 SEH
- **THEN** 标准答案位于前 K 条的比例即为该值，取值在 [0, 1]

#### Scenario: SRS 的定义
- **WHEN** 计算 SRS
- **THEN** 按标准答案的排名归一化到 [0, 1]，排名第 1 得 1.0，
  完全未召回得 0.0，且 MUST 与 SEH@K 分开报告

#### Scenario: K 大于结果总数
- **WHEN** K 超过实际返回条数
- **THEN** 按实际返回条数计算，不把缺失位置算作命中

#### Scenario: 区间与样本数
- **WHEN** 报告任一检索指标
- **THEN** 同时给出样本数与 bootstrap 区间；样本数过少时明确标注

#### Scenario: 配对比较
- **WHEN** 比较两个检索配置
- **THEN** 用配对 bootstrap 在同一批查询上比较，而非两次独立采样

#### Scenario: 召回路径的返回条数被记录
- **WHEN** 完成一次检索评估
- **THEN** 结果中包含每条召回路径各自的返回条数，而不只是融合后的候选数

#### Scenario: 路径空转必须可见
- **WHEN** 某条召回路径被调用但返回 0 条
- **THEN** 该事实出现在结果中，且报告中不得把该次评估描述为"三路都参与了排序"

#### Scenario: 无 gold 的 case 必须单独计数
- **WHEN** 样本中存在没有 `gold_item_id` 的 case
- **THEN** 这些 case MUST 单独计数，且 MUST 从召回类指标的分母中排除

#### Scenario: 比例区间必须说明方法与适用性
- **WHEN** 报告给出任何比例区间
- **THEN** MUST 同时说明所用方法与样本量；样本量小时 MUST 说明该方法在此规模下的适用性
