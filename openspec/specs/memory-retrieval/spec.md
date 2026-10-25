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

系统 SHALL 用四个特征对候选重排：融合分、条件匹配、来源权威、状态惩罚。
每个特征 MUST 返回 [0,1]，且 MUST 可单独关闭以支持消融。

#### Scenario: 基础项为融合分
- **WHEN** 只有融合分特征启用
- **THEN** 排序与纯 RRF 完全一致

#### Scenario: 条件匹配
- **WHEN** 查询带条件，候选分为条件相同与不同
- **THEN** 相同者得更高分

#### Scenario: 条件缺失时为中性
- **WHEN** 查询或候选任一方无条件
- **THEN** 该特征返回 0.5，而非 0

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
- **WHEN** 四个特征全部关闭
- **THEN** 退化为融合分排序，且不因权重校验失败

### Requirement: 条件槽位抽取

系统 SHALL 把自由文本条件归一为结构化槽位，且**写入侧与查询侧 MUST 使用同一套词表**。

#### Scenario: 常见条件被识别
- **WHEN** 条件包含时间、场景、环境类表达
- **THEN** 抽出对应的槽位键值

#### Scenario: 中英表达归一到同一槽位
- **WHEN** 同一条件以中文与英文分别表达（如"应酬"与"client dinner"）
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
