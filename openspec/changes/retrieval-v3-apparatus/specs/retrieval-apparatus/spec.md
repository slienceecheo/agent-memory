# Spec Delta

## Purpose

定义评测装置本身：排序用哪些特征、每个特征由什么取值、评测轴如何划分、以及权重敏感性如何在不重跑的情况下复算。装置必须先于数据固定，否则数据集的价值会随装置变化而流失。

## ADDED Requirements

### Requirement: 排序特征集

系统 SHALL 用三个特征对候选重排：融合分（`base`）、来源权威（`authority`）、状态惩罚（`status`）。
每个特征 MUST 落在 `[0, 1]`，且 MUST 可单独关闭。

`condition` MUST NOT 参与排序打分。它 MAY 只用于召回阶段的过滤。

#### Scenario: 三特征加权求和

- **WHEN** 提供三个特征值与一组权重
- **THEN** 候选得分为三个特征值按权重加权之和

#### Scenario: 权重和必须为 1

- **WHEN** 提供的权重之和偏离 1 超过 1e-6
- **THEN** 系统拒绝该组权重并报错

#### Scenario: 全零权重被拒绝

- **WHEN** 三个权重全为 0
- **THEN** 系统 MUST 拒绝并报错（权重之和必须为 1）

- **AND** 本项目 MUST NOT 提供"三个特征全部关闭"的构造方式：
  权重和恒为 1，而三个都关意味着和为 0，两者不相容

- **AND** `disabled_weights()` 的语义 MUST 是"**只开融合分**"（`base=1, authority=0, status=0`），
  MUST NOT 被描述为"全部关闭"

**为什么把旧场景改掉**：v2 的 spec 写的是"四个特征全部关闭 -> 退化为融合分排序"，
而那个场景**从来无法构造**——`RerankWeights` 一直要求权重和为 1。
测试 `test_all_off_falls_back_to_base` 用的是 `disabled_weights()`，
它的实际语义是"只开 base"，所以**测试名与断言内容不一致**。
本次 MODIFIED 本可顺手修掉，只把"四"改成"三"会把这个缺陷留在正式 spec 里。

#### Scenario: condition 不参与得分

- **WHEN** 两条候选除 `condition` 外三个特征值完全相同
- **THEN** 两者得分相同，`condition` 不改变任何一条的得分

### Requirement: 轴的定义必须可判定

评测轴 MUST 由可计算的结构属性定义，而不是由数据集的命名约定定义。

每条查询 MUST 记录其轴归属（二元：`relation_within` / `relation_cross`）**以及**该归属所依据的
`n_competitors`（池中与 gold 同 `relation` 的候选数量，不含 gold）。两者 MUST 都能写入结果文件。

#### Scenario: 同 relation 内有竞争者

- **WHEN** gold 之外池中至少存在一条与 gold 同 `relation` 的记忆
- **THEN** 该查询属于"relation 内选择"轴，且 `n_competitors > 0`

#### Scenario: relation 唯一

- **WHEN** gold 之外池中不存在与 gold 同 `relation` 的记忆
- **THEN** 该查询属于"跨 relation 选择"轴，且 `n_competitors == 0`

#### Scenario: subject 级轴判定按取值集合，且空轴单独处置

- **WHEN** 对一个 subject 汇总其所有可评分查询的 `n_competitors`
- **THEN** 判定 MUST 使用两轴取值集合 `set(within)` 与 `set(cross)` 的比较，
  并 MUST 返回四值之一：

  | 情形 | 判定 |
  |---|---|
  | 两轴都有查询，`set` 相等 | `merged` |
  | 两轴都有查询，`set` 不等 | `two_axes` |
  | 只有一轴有查询 | `single_axis` |
  | 两轴都没有查询 | `no_axis` |

- **AND** MUST NOT 使用中位数、有序列表（含样本量）或 within/cross 标签集合作为判据
- **AND** MUST NOT 把"两轴都为空"判为 `merged`——`set()` 与 `set()` 相等不代表两轴同构
- **AND** `single_axis` MUST NOT 归并为 `merged`：两者报告轴数都是 1，但前者是"只有一轴"，
  后者是"两轴同构，合并后仍代表两轴"

#### Scenario: 两轴不可合并时必须有其他区分量

- **WHEN** 同一 subject 内两轴的 `n_competitors` 取值集合不同（判定为 `two_axes`）
- **THEN** 系统 MUST 在报告中分别给出两轴的分数；MUST NOT 以命名区分为由保留两轴

### Requirement: 逐条特征分必须持久化

每次评测 MUST 把每条 case 的三个排序特征取值写入 `features` 子对象：`base` / `authority` / `status`。

`condition` 的取值 MUST 单独写入 `condition_score` 字段（数值或 `null`），
**不放进 `features`**——它不参与排序，但它的分布是判断"条件能否被查询侧获得"的唯一依据。

#### Scenario: 每条 case 的 features 含三个键

- **WHEN** 一次评测产生 N 条 case
- **THEN** 每条 case 的 `features` 恰好含 `base` / `authority` / `status` 三个数值字段，不含 `condition`

#### Scenario: condition_score 独立记录

- **WHEN** 一次评测产生 N 条 case
- **THEN** 每条 case 都含 `condition_score` 字段；查询侧无条件时为 `null`，否则为 `condition_match` 的取值

#### Scenario: 特征分足以离线复算名次

- **WHEN** 用结果文件中记录的 `features_by_tag`、`fusion_tags` 与权重重新计算得分并排序
- **THEN** 得到的每条 case 名次与记录中的 `rank_after_rerank` 完全一致，差异数为 0

- **AND** MUST NOT 只凭 `features`（gold 自己那三项）复算：
  名次是相对于整池的，只存 gold 的分复算不出"它为什么排第 3"

- **AND** 复算 MUST 复现**两步**裁决：先按权重得分，并列时按 `fusion_tags` 的位置。
  只复现第一步在无并列数据上永远绿，而 `rerank` 内部按 tag 字典序破并列会让
  `d-<case>-0` 恒排在 `gold-<case>` 之前——**一个固定偏向，看起来像排序结果**

- **AND** 测试 MUST 包含一个**人为构造的并列 case**，且两种裁决给出相反名次；
  MUST NOT 只依赖真实数据"恰好出现并列"

- **AND** 测试 MUST 断言"池 > 1 的 case 数量不少于 5"：
  池只有 1 条时任何实现都"复算一致"，那是空转

#### Scenario: 缺字段时拒绝写结果

- **WHEN** 任一 case 的 `features` 缺键，或缺 `condition_score` 字段
- **THEN** 系统 MUST 报错，不得写出缺字段的结果文件

#### Scenario: gold 未召回时两侧同时表达

- **WHEN** 某条 case 的 gold 没有进入重排候选集
- **THEN** `features` MUST 为 `null`，**且** `features_by_tag` 里 MUST 不含 gold 的 tag

- **AND** MUST NOT 用 `{}` 表示未召回：`{}` 是"存在但没有键"的对象，与"不存在"无法区分

### Requirement: 权重敏感性的离线复算

系统 SHALL 支持仅凭已存结果文件复算"改变权重后的名次"，无需重跑检索。

#### Scenario: 只改权重不改特征

- **WHEN** 用同一份结果文件里已存的特征分，仅替换权重参数
- **THEN** 得到的新名次只依赖特征分与新权重，与原始检索路径无关

#### Scenario: 复算结果可追溯到具体权重

- **WHEN** 输出一次离线复算的结果
- **THEN** 该结果 MUST 记录所使用的**三权重**（`base` / `authority` / `status`），
  且该三元组 MUST 能被重新加载并产生相同结果

- **AND** MUST NOT 记录四元组：`condition` 已退出加权，记一个零权重会让人以为它仍参与排序
