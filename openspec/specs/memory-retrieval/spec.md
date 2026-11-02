# memory-retrieval Specification

## Purpose
定义从记忆中检索相关条目的契约：给定一个查询，系统应从一组候选记忆中找出
**最适合用于回答该查询**的那些，并按相关性排序。它不负责写入、判定与作答。

## Requirements

### Requirement: 检索形式化

系统 SHALL 用 `(query, candidate_pool, gold_item_id)` 三元组定义一次检索评估。
`gold_item_id` 为空的场景（新增事实）MUST 从召回类指标中排除并单独计数。

#### Scenario: 有 gold 的查询
- **WHEN** 场景给出了 `gold_item_id`
- **THEN** 该条计入 SEH@K 与 SRS

#### Scenario: 无 gold 的查询
- **WHEN** 场景没有既有记忆（ADD 类）
- **THEN** 该条不计入召回指标，但在报告中给出其数量，避免样本量被静默改变

#### Scenario: gold 必须在候选池中
- **WHEN** 构建候选池
- **THEN** `gold_item_id` 必定是池中一员，否则该条记为"池构建失败"并报错

### Requirement: 候选池构建

系统 SHALL 为每条评估场景构建一个包含 gold 与若干干扰项的候选池。
干扰项 MUST 与 gold 的逻辑键互不相同（否则会撞唯一约束），
且池大小 MUST 大于评估用的 K，使排名有意义。

#### Scenario: 池大小可配置
- **WHEN** 指定干扰项数量 N
- **THEN** 池大小为 1 + N，默认 N=20

#### Scenario: 干扰项键不冲突
- **WHEN** 构建池
- **THEN** 任意两条干扰项的 `(subject, relation, condition)` 互不相同

#### Scenario: gold 排名可变
- **WHEN** 在原始（未排序）候选池中定位 gold
- **THEN** 其位置随场景变化，不得恒为同一位置

#### Scenario: 池太小时拒绝评估
- **WHEN** 池大小小于等于 K
- **THEN** 系统报错，而不是给出虚高的 SEH

### Requirement: 三路召回

系统 SHALL 通过三条相互独立的路径召回候选：词面匹配、向量相似、条件兄弟邻接。
每条路径 MUST 可单独关闭，以便测量各自的贡献。
评测入口 MUST 同时调用三条路径，且每条路径的返回条数 MUST 可观测。

#### Scenario: 词面召回
- **WHEN** 用查询调用词面路径
- **THEN** 按 BM25 相关性降序返回候选（不得按版本号或写入序排序）

#### Scenario: 词面索引包含原文
- **WHEN** 一条记忆由某句原文产生
- **THEN** 该原文可被词面检索命中

#### Scenario: 向量召回
- **WHEN** 用查询向量调用向量路径
- **THEN** 按余弦相似度降序返回，跳过无向量的条目

#### Scenario: 条件兄弟邻接
- **WHEN** 查询命中某逻辑键，且该键下存在其他条件的条目
- **THEN** 这些兄弟条目进入候选，用于 BRANCH 场景

#### Scenario: 单路可关闭
- **WHEN** 显式关闭某一路
- **THEN** 结果中不再包含该路候选，其余两路行为不变

#### Scenario: 全部关闭
- **WHEN** 三路全部关闭
- **THEN** 返回空结果而不是报错，使"零召回"可作为基线

#### Scenario: 各路长度一致
- **WHEN** 融合前
- **THEN** 每条路径的返回条数被截断到同一上限

#### Scenario: 评测入口调用三条路径
- **WHEN** 在任意数据集上运行检索评测
- **THEN** 词面、向量、邻接三条路径都被实际调用，融合输入包含三路各自的排名列表

#### Scenario: 向量路径在池内有向量可召回
- **WHEN** 评测为某个查询构建候选池
- **THEN** 池内每一条候选都写入了向量，使向量路径不会因缺向量而返回空

#### Scenario: 三路召回各自返回非空
- **WHEN** 在至少一条有 gold 的查询上运行评测
- **THEN** 三条路径的返回条数都大于 0，且各路径返回条数被记录到结果中

#### Scenario: 只开一路时结果可复现
- **WHEN** 只开启词面路径并重跑同一数据集
- **THEN** 每条 case 的融合排名与重排排名与归档结果逐位相同

### Requirement: RRF 融合

系统 SHALL 用 Reciprocal Rank Fusion 合并多路结果，MUST NOT 直接相加各路原始分数。

#### Scenario: 多路前列优于单路前列
- **WHEN** 某条目在两路中都排前列，另一条目只在一路中排前列
- **THEN** 前者融合分数更高（前提：各列表长度小于 k+2）

#### Scenario: 量纲无关
- **WHEN** 某路分数无界、另一路有界
- **THEN** 融合结果只依赖排名，不依赖原始分数尺度

#### Scenario: 单路退化
- **WHEN** 只开一路
- **THEN** 融合结果与该路排名完全一致

#### Scenario: k 值可配置且影响结果
- **WHEN** 修改 k
- **THEN** 至少两条候选的相对顺序发生变化（在多列表场景下）

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

### Requirement: 语义等价判断

系统 SHALL 判断两条记忆是**等义**、**互补**还是**无关**，并 MUST 通过缓存保证可复现。

#### Scenario: 等义
- **WHEN** 字面不同但含义相同（"每周日凌晨"与"每周日零点"）
- **THEN** 判为等义

#### Scenario: 互补
- **WHEN** 后者是前者的细化（"靠窗那一排"与"C区第三排左数第二个工位"）
- **THEN** 判为互补

#### Scenario: 无关
- **WHEN** 描述不同事实
- **THEN** 判为无关

#### Scenario: 失败降级
- **WHEN** 模型失败或输出不可解析
- **THEN** 按"无关"处理，检索继续，失败次数被记录

#### Scenario: 缓存命中不发起请求
- **WHEN** 对同一对重复判断
- **THEN** 第二次零网络请求且结果相同

#### Scenario: 有明确消费者
- **WHEN** 开启等义判断
- **THEN** 等义候选在去重阶段被合并，且去重后的候选数量可被观测

#### Scenario: 可整体关闭
- **WHEN** 关闭等义判断
- **THEN** 检索仍工作，去重不生效，用于消融

### Requirement: 检索指标

系统 SHALL 报告 SEH@K 与 SRS，并 MUST 给出样本数与配对 bootstrap 区间。

#### Scenario: SEH@K
- **WHEN** gold 位于前 K
- **THEN** 记 1，否则 0

#### Scenario: SRS 定义
- **WHEN** gold 排名为 r（从 1 开始）
- **THEN** SRS = 1/r；未召回时 SRS = 0

#### Scenario: SRS 反映排名
- **WHEN** 两个配置都让 gold 进前 5，排名分别为 1 与 5
- **THEN** 前者 SRS 更高（1.0 vs 0.2），即使 SEH@5 相同

#### Scenario: K 超过池大小时拒绝
- **WHEN** K ≥ 池大小
- **THEN** 报错，而不是给出虚高值

#### Scenario: 配对区间
- **WHEN** 比较两个配置
- **THEN** 用配对 bootstrap 给出 SRS 差异区间

### Requirement: 检索失败归因

系统 SHALL 把每条**检索失败**样本归入三类之一，判定 MUST 规则化（不调用模型）。

#### Scenario: 池外
- **WHEN** gold 不在候选池
- **THEN** 归因为"池构建失败"

#### Scenario: 排序过低
- **WHEN** gold 在池中但排名 > K
- **THEN** 归因为"排序过低"

#### Scenario: 重排丢弃
- **WHEN** gold 进入融合后前 K，但被重排挤出前 K
- **THEN** 归因为"重排丢弃"

#### Scenario: 三分类互斥且完备
- **WHEN** 汇总全部检索失败
- **THEN** 三类计数之和等于失败总数，且任一样本只落一类

#### Scenario: 与判定失败分开
- **WHEN** 报告归因
- **THEN** 只统计检索失败，不复用 C3 的判定错误

### Requirement: 防过拟合的实验协议

系统 SHALL 使用**预注册**的少量权重组合，在 dev 上选型、在 test 上报告，
并给出最小可检测效应。

#### Scenario: 预注册权重
- **WHEN** 开始实验
- **THEN** 权重组合在运行前固定为不超过 5 组，不做事后网格搜索

#### Scenario: 全部组合都报告
- **WHEN** 报告结果
- **THEN** 5 组权重在 dev / test / independent 三个集上的分数全部列出

#### Scenario: 最小可检测效应
- **WHEN** 报告主结论
- **THEN** 说明在当前样本量下能观测到的最小差异，避免把噪声当结论

#### Scenario: 不只报最优
- **WHEN** 某组权重在 test 上最高
- **THEN** 同时给出其余组合的分数，不单独呈现 argmax

### Requirement: 去重输入的完整性

去重阶段 SHALL 接收由**统一规则**构造的可比较文本与**真实排序分数**，
MUST NOT 接收条目标识符、稳定 tag 或聚合标签充当文本，
MUST NOT 接收常数充当分数。

#### Scenario: 传入可比较的文本
- **WHEN** 去重被调用
- **THEN** 两侧文本由同一条规则构造（`subject + relation + value + condition`）
- **AND** 该规则 MUST 同时含 `value` 与 `condition`：
  缺 `value` 无法区分"同 relation 不同答案"，缺 `condition` 无法区分 BRANCH 的两个分支

#### Scenario: 原文缺失时不得回退为标识符
- **WHEN** 条目的原文不可用（干扰项的 `text` 为 `None`）
- **THEN** 仍按统一规则构造文本，MUST NOT 回退到 id 或 tag
- **AND** 该回退曾在 C4 出现（缺陷 8），导致排序退化为字典序

#### Scenario: 传入真实分数
- **WHEN** 去重被调用
- **THEN** 候选分数在同一批候选中存在方差，不是全部相等

#### Scenario: 常数分数不得改变顺序
- **WHEN** 所有候选分数相等且判定全部为"无关"
- **THEN** 去重后的顺序与输入顺序一致，不得按标识符字典序重排

#### Scenario: 池构造已排除同键条目时的行为
- **WHEN** 候选池由 `build_pool` 构造（已按 `owner/scope/subject/relation/condition` 去重）
- **THEN** 去重阶段 MUST NOT 合并任何一对，因为不存在同键条目
- **AND** 候选数量在去重前后 MUST 相同；若不同，说明池构造或去重规则有变

> 此条记录一个**已知的职责重叠**：`build_pool._key` 与 `dedup` 的目标集合相交。
> 实测池内同 key 的对数 = 0（3300 对全查过），所以去重当前一条都不会合并。
> 修缺陷 13（`_key` 加 `value`）时必须同时决定"同 key 同 value 由谁处理"。
> 没有这条 scenario，spec 会让人以为去重正在正常执行。

#### Scenario: 去重位置在重排之前
- **WHEN** 启用去重
- **THEN** 去重作用于融合结果，其输出再交给重排；去重不得推翻重排已确定的顺序
