## MODIFIED Requirements

### Requirement: 排序特征集

系统 SHALL 用三个特征对候选重排：融合分（`base`）、来源权威（`authority`）、语义相似度（`cosine`）。
每个特征 MUST 落在 `[0, 1]`，且 MUST 可单独关闭。

`condition` MUST NOT 参与排序打分。它 MAY 只用于召回阶段的过滤。

`status` MUST NOT 作为排序特征：三条召回路径只返回 `ACTIVE`，它在池内恒为常数（见
`evaluation-harness` 的「恒常数字段不得作为排序特征」与「所有召回路径 MUST 只返回 ACTIVE」）。

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

- **AND** `disabled_weights()` 的语义 MUST 是"**只开融合分**"（`base=1, authority=0, cosine=0`），
  MUST NOT 被描述为"全部关闭"

**为什么把旧场景改掉**：v2 的 spec 写的是"四个特征全部关闭 -> 退化为融合分排序"，
而那个场景**从来无法构造**——`RerankWeights` 一直要求权重和为 1。
测试 `test_all_off_falls_back_to_base` 用的是 `disabled_weights()`，
它的实际语义是"只开 base"，所以**测试名与断言内容不一致**。
本次 MODIFIED 本可顺手修掉，只把"四"改成"三"会把这个缺陷留在正式 spec 里。

#### Scenario: condition 不参与得分

- **WHEN** 两条候选除 `condition` 外三个特征值完全相同
- **THEN** 两者得分相同，`condition` 不改变任何一条的得分

#### Scenario: 权重与特征值必须用关键字参数构造

- **WHEN** 以位置参数构造 `RerankWeights(0.4, 0.3, 0.3)` 或 `FeatureScores(0.5, 0.0, 1.0, 1.0)`
- **THEN** MUST 抛出 `TypeError`

- **AND** 理由 MUST 被写明：**字段含义在版本间变过**
  （`RerankWeights` 第三位：`condition` → `status` → `cosine`；
  `FeatureScores` 第四位：`status` → `cosine`），
  位置参数会让"看起来配了 cosine"的代码实际配的是别的字段

**为什么这条是产品契约而不是测试惯例**：它可观察——构造会抛错。
而"测试里请用关键字"不可观察，写进 spec 也只是惯例。

**这个场景为什么对 `FeatureScores` 尤其必要**：它的字段顺序是
`base` / `condition` / `authority` / `cosine`，而产物里 `features` 的键是
`base` / `authority` / `cosine`——`condition` 夹在第 2 位且不进 `features`。
**所以"按位置对应"的写法从一开始就是错的**，不是改字段后才错。
`kw_only` 让这种错位从静默变成构造期报错。

**实测的抛错形态**：`takes 1 positional argument but 4 were given`（`RerankWeights`）、
`but 5 were given`（`FeatureScores`）。所以判据能区分"拒收位置参数"与"别的构造错误"。

**这是全项目唯一使用 `kw_only=True` 的 dataclass**，理由必须写在代码里：
其他 dataclass（如 `Check("F24", "A 轴未饱和", True, ...)`）的字段含义从未变过。
**"字段含义会变"才是理由，不是"位置参数不好"。**

### Requirement: 逐条特征分必须持久化

每次评测 MUST 把每条 case 的三个排序特征取值写入 `features` 子对象：`base` / `authority` / `cosine`。

`condition` 的取值 MUST 单独写入 `condition_score` 字段（数值或 `null`），
**不放进 `features`**——它不参与排序，但它的分布是判断"条件能否被查询侧获得"的唯一依据。

#### Scenario: 每条 case 的 features 含三个键

- **WHEN** 一次评测产生 N 条 case
- **THEN** 每条 case 的 `features` 恰好含 `base` / `authority` / `cosine` 三个数值字段，不含 `condition`、不含 `status`

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
- **THEN** 该结果 MUST 记录所使用的**三权重**（`base` / `authority` / `cosine`），
  且该三元组 MUST 能被重新加载并产生相同结果

- **AND** MUST NOT 记录四元组：`condition` 已退出加权，记一个零权重会让人以为它仍参与排序

## ADDED Requirements

### Requirement: cosine 特征值必须来自向量召回，不得在重排阶段重算

`cosine` 的取值 MUST 由候选在向量召回路径中算出的那一个余弦值**经单调变换**得到，
MUST NOT 在重排阶段对候选重新做一次 embedding 比较。

变换只有一个：`cosine = max(0.0, raw_cos)`（把 `[-1, 1]` 压进 `rerank` 要求的 `[0, 1]`）。

#### Scenario: 逐条 cosine 等于召回时算出的分

- **WHEN** 一次评测启用了 `vector` 路径
- **THEN** 对每个进入重排的候选，`features_by_tag[tag]["cosine"]` MUST 等于
  `max(0.0, recall_by_vector_scored(...)` 给出的该候选原始余弦分`)`，逐位相等，不做四舍五入

- **AND** 判定 MUST 用一次**独立的召回调用**取回分数再比对，
  MUST NOT 用"`features_by_tag` 里的值与 `features_by_tag` 里的值"自比

- **AND** 排序用的分与记录的 `cosine` MUST 来自同一次召回调用

#### Scenario: 未启用 vector 路径时 cosine 为 0，且不得伪造

- **WHEN** 评测的 `paths` 不含 `vector`
- **THEN** 每条候选的 `cosine` MUST 为 `0.0`
- **AND** 结果 MUST 用既有字段表达"这条没有 cosine 信号"：
  `paths_enabled` 不含 `"vector"` 且 `path_returns["vector"]` 为 `null`

**为什么"不得自比"**：`features_by_tag` 里既存 cosine 又拿来当期望值，
是同一个数和自己比，任何实现都通过。必须另起一次召回调用。

**为什么不能在重排阶段重算**：`AGENTS.md` 已登记 embedding 的非确定性——
同一文本重复调用可能出现不同向量（跨变体余弦 0.9976）。
重算会引入第二次调用，于是"按 cosine 排序"用的分与"记录下来的 cosine"不是同一个数，
复算验收会以无法归因的方式失败（差异只在缓存未命中时出现）。
`max(0, x)` 是同一个数的单调变换，不涉及第二次调用，因此不违反这一条。
