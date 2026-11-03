# evaluation-harness Specification

## Purpose
定义评测骨架的行为契约：如何加载基准数据、如何运行一条基线、如何计算指标与置信区间，
以及如何保证同一份输入在重复运行时给出完全相同的数字。它不关心记忆系统内部实现，
只关心"同一把尺子"是否可信、可复现、可归因。

## Requirements

### Requirement: 基准数据加载

系统 SHALL 能从 FactConsolidation 格式的数据集中加载样本，并保留每条事实的原始序号。
加载器 MUST 支持按长度子集（6K / 32K / 64K / 262K）与单跳/多跳（SH / MH）筛选。

#### Scenario: 加载 6K 单跳子集
- **WHEN** 调用方指定 `length=6k` 且 `hop=sh`
- **THEN** 返回的样本数大于 0，且每条样本包含有序事实列表与对应问题、标准答案

#### Scenario: 序号被保留
- **WHEN** 一条样本含 5 条事实
- **THEN** 每条事实携带其在原文中的位置序号，且序号在样本内单调递增

#### Scenario: 不存在的子集
- **WHEN** 调用方指定一个数据集不包含的长度子集
- **THEN** 系统报出明确错误，列出可用子集，而不是返回空列表

#### Scenario: 数据文件缺失
- **WHEN** 指定的数据集文件不存在
- **THEN** 系统报错并给出下载地址，且**不自动联网下载**（保证离线可复现）

### Requirement: 基线运行器

系统 SHALL 提供三种可独立运行的基线：`no-memory`、`full-context`、`naive-rag`。
每次运行 MUST 产出一份结构化结果，包含每条样本的预测、是否命中、以及 token 用量。

#### Scenario: 三种基线均可运行
- **WHEN** 对同一数据集分别运行三种基线
- **THEN** 各产出一份结果 JSON，且三者使用完全相同的样本集合与顺序

#### Scenario: 结果包含逐样本记录
- **WHEN** 查看任一基线结果
- **THEN** 其中包含每条样本的 id、预测答案、是否命中、以及输入/输出 token 数

#### Scenario: 未知基线名
- **WHEN** 调用方指定一个未注册的基线名
- **THEN** 系统报错并列出所有可用基线名

#### Scenario: 基线共享同一生成路径
- **WHEN** 三条基线处理同一条样本
- **THEN** 它们使用完全相同的系统提示词与生成函数，唯一差别是喂入上下文的构造方式

#### Scenario: 系统提示词不得泄露解法
- **WHEN** 检查任一条基线发出的系统提示词
- **THEN** 其中不包含"编号大者更新""取最新"之类提示冲突消解规则的措辞，
  否则基线会免费获得被测方法的核心思路，导致比较失去意义

### Requirement: 答案匹配指标

系统 SHALL 实现 `substring_exact_match`：去除首尾空白、做 NFKC 归一并折叠大小写后，
标准答案作为预测答案的子串出现即为命中。

#### Scenario: 完全一致
- **WHEN** 标准答案为 `"Paris"`，预测为 `"Paris"`
- **THEN** 判定命中

#### Scenario: 大小写与空白差异
- **WHEN** 标准答案为 `"paris"`，预测为 `"  Paris  "`
- **THEN** 判定命中

#### Scenario: 预测包含额外说明
- **WHEN** 标准答案为 `"Paris"`，预测为 `"The answer is Paris."`
- **THEN** 判定命中

#### Scenario: 空预测
- **WHEN** 预测为空字符串或 null
- **THEN** 判定未命中，且不抛异常

#### Scenario: 空标准答案
- **WHEN** 标准答案为空字符串或仅含空白
- **THEN** 系统明确报错，因为空标准答案无法用于子串匹配

#### Scenario: 中文答案
- **WHEN** 标准答案为 `"北京"`，预测为 `"北京。"`
- **THEN** 判定命中

#### Scenario: 数字前缀的已知误判
- **WHEN** 标准答案为 `"42"`，预测为 `"421"`
- **THEN** 判定为命中——这是该指标口径的已知弱点，由测试显式锁定，
  不允许被"顺手优化"成词边界匹配，否则与官方分数不可比

### Requirement: 配对 bootstrap 置信区间

系统 SHALL 用配对重采样计算指标差异的 95% 置信区间，重采样次数默认 10000，
随机种子可配置。

#### Scenario: 全部命中
- **WHEN** 100 条样本全部命中
- **THEN** 返回的准确率为 1.0，区间为 `[1.0, 1.0]`

#### Scenario: 各占一半
- **WHEN** 100 条样本中恰好 50 条命中
- **THEN** 返回的准确率为 0.5，且置信区间覆盖 0.5

#### Scenario: 同种子可复现
- **WHEN** 用相同种子连续计算两次
- **THEN** 两次返回的区间端点完全相同

#### Scenario: 两组配对的差异
- **WHEN** 传入两组一一对应的逐样本结果
- **THEN** 返回两组准确率之差及其置信区间，而非两个独立区间

#### Scenario: 配对比独立更窄
- **WHEN** 两组结果高度正相关且差异极小时
- **THEN** 配对区间必须显著窄于把两组当独立样本得到的区间

### Requirement: 可复现性保证

系统 SHALL 在缓存完整时保证同一输入产生完全相同的指标数值。
任何 LLM 或 embedding 调用 MUST 经过磁盘缓存，且在缓存命中时 MUST NOT 发起网络请求。

#### Scenario: 热缓存下重跑
- **WHEN** 完成一次运行后，以相同参数再次运行
- **THEN** 两次的结果 JSON 逐位相同，且第二次的网络调用数为 0

#### Scenario: 缓存完整性校验
- **WHEN** 执行缓存检查命令且两类缓存均完整
- **THEN** 退出码为 0

#### Scenario: 缓存缺失或不完整
- **WHEN** 任一缓存不存在、为空或含损坏条目
- **THEN** 退出码非零，并指出是哪一类缓存的哪个条目出了问题

#### Scenario: 冷缓存首次运行
- **WHEN** 缓存为空时运行
- **THEN** 系统仍能产出结果，并明确记录本次产生了多少次网络调用

### Requirement: 运行追踪

系统 SHALL 在每次运行中把每个样本的处理过程写成 JSONL 事件，字段至少包含
样本 id、阶段名、耗时、输入输出 token 数、网络调用数、以及错误类型（若有）。

#### Scenario: 事件可追溯
- **WHEN** 完成一次运行
- **THEN** 输出的 JSONL 中每条样本至少有一条事件，且事件可通过样本 id 关联到结果 JSON

#### Scenario: 失败样本不被静默丢弃
- **WHEN** 某条样本在处理中抛出异常
- **THEN** 该样本在结果中标记为错误并记录错误类型，而不是从结果集中消失

#### Scenario: 未知阶段被拒绝
- **WHEN** 写入一个未定义的阶段名
- **THEN** 系统立即报错，而不是接受任意字符串导致后续聚合报表漏数据

### Requirement: 分类质量的度量

系统 SHALL 为多类别判定任务提供：逐类混淆矩阵、macro-F1、以及逐类的配对 bootstrap 区间。
指标 MUST 对类别不均衡稳健，且 MUST NOT 只报总体准确率。

#### Scenario: 六类混淆矩阵
- **WHEN** 对一批判定结果计算质量
- **THEN** 输出 6×6 混淆矩阵，行是人工确认的期望类别，列是系统给出的判定

#### Scenario: macro-F1 不偏向多数类
- **WHEN** 某个类别只有 3 条样本且全部判错，其余类别全对
- **THEN** macro-F1 因该类的 0 分而明显下降，而不是被总体准确率掩盖

#### Scenario: 逐类区间
- **WHEN** 报告某一类的 F1
- **THEN** 同时给出该类的样本数与 bootstrap 区间，样本数过少时明确标注区间不可靠

#### Scenario: 单类无样本
- **WHEN** 某个类别在评估集中没有样本
- **THEN** 该类在矩阵中显示为 0 样本，且不计入 macro-F1 的分母，
  而不是被当作 0 分拉低整体

#### Scenario: 同种子可复现
- **WHEN** 用相同种子重复计算
- **THEN** 混淆矩阵与全部区间逐位相同

#### Scenario: 标注不一致的条目单列
- **WHEN** 两名标注者的标签不一致
- **THEN** 这些条目在报告中单列，且不静默采用任意一方

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

### Requirement: 路径贡献的可测性

系统 SHALL 能给出"全部召回路径开启"与"仅开启部分路径"两种配置的指标对比，
使新增路径是否有贡献成为可观测事实，而不是靠"是否被调用"推断。

#### Scenario: 配置对比
- **WHEN** 在同一数据集上分别运行"三路全开"与"只开词面"
- **THEN** 输出两组指标及其配对差异区间，而不是只给单组分数

#### Scenario: 差异为零也是一种结论
- **WHEN** 两种配置的指标完全相同
- **THEN** 报告中明确写出"新增路径在该数据上没有可观测贡献"，
  不得省略该对比、也不得把它记作通过

#### Scenario: 单路基线不因多路接入而改变
- **WHEN** 只开启词面路径并重跑历史数据集
- **THEN** 每条 case 的排名与历史归档结果逐位相同，
  证明新增路径没有改动既有排序逻辑

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

### Requirement: 门禁的适用域

读结果文件的门禁 MUST 区分**两件不同的事**，且 MUST 分别回答：

| 问题 | 必须由什么回答 |
|---|---|
| 当前代码是哪一代装置？ | 一个**显式常量**（MUST NOT 从产物推） |
| 这份文件能不能回答当前装置的问题？ | **常量与文件签名的比较** |

**只判断第一个问题是错的**：常量在任意一次运行内恒定，所以
`CURRENT_APPARATUS == "v3"` 这类条件**恒为真**，会让"不适用"变成无条件结论。

**只有当判据依赖装置时**才返回"不适用"；判据不依赖装置的门禁 MUST 照常执行。

#### Scenario: 判据依赖装置的门禁返回不适用

- **WHEN** 某门禁的判据依赖排序装置，且文件签名**不等于** `CURRENT_APPARATUS`
- **THEN** 门禁 MUST 返回 `applicable=False`，`passed` MUST 为 False

- **AND** detail MUST 写明**两边**分别是什么（"X 装置产物，当前为 Y"）

- **AND** MUST NOT 因为"当前装置是 v3"就直接判不适用

#### Scenario: 判据不依赖装置的门禁照常执行

- **WHEN** 某门禁的判据与排序装置无关
- **THEN** 它 MUST 照常执行并给出**通过或失败**

- **AND** MUST NOT 因为"产物来自旧装置"就返回"不适用"

#### Scenario: 装置签名只读结构事实

- **WHEN** 需要判断一份结果文件由哪个装置产生
- **THEN** 签名 MUST 由文件自身的结构决定：

  | 格式 | 判据 |
  |---|---|
  | 有 `per_case` | `per_case[0]` 有 `features` -> v3 |
  | 消融聚合（无 `per_case`） | 两轴逐条 rank 相同 -> v3 |

- **AND** MUST NOT 依赖 `apparatus` 之类的常量字段

- **AND** 签名是 `unknown` 时 MUST 保守处置为"不适用"

#### Scenario: 分类写宽时必须被抓住

- **WHEN** 有人把"判据不依赖装置"的门禁也判成"不适用"
- **THEN** MUST 有测试会红

- **AND** 该测试 MUST 断言**哪些**门禁不适用

#### Scenario: 当前装置必须识别为适用

- **WHEN** 断言"当前装置是哪一代"，或对当前代码产出的结果文件跑门禁
- **THEN** MUST 比较 `CURRENT_APPARATUS` 与**当前代码实际产出的签名**

- **AND** MUST NOT 只断言常量值——那是同义反复

- **AND** 同装置签名的文件 MUST 让门禁**执行**；若改回"只看常量"，MUST 有测试变红

#### Scenario: 判据依赖装置不等于判据失效

- **WHEN** 某门禁的判据在 v3 下的**期望值**变了（而非判据本身失效）
- **THEN** MUST 在 v3 下给出**新的期望值并执行**，MUST NOT 永久返回"不适用"

- **AND** 例：`F20` 在 v3 下期望 `drop == 0`（能抓"BREAKING 被回退"）

#### Scenario: 门禁必须能发现所有分区的产物

- **WHEN** 结果文件位于任何**已登记分区**（`results/` 顶层或 `results/v3/` 等）
- **THEN** 门禁 MUST 能发现它

- **AND** 文件发现 MUST NOT 依赖文件名前缀（如 `v2-`）——
  前缀是历史约定，不该成为"能不能被发现"的条件

- **AND** 装置归属 MUST 由 `apparatus_signature` 判断，MUST NOT 由文件名判断

#### Scenario: 找不到文件必须显式区分三件事

- **WHEN** 门禁没有找到可用的结果文件
- **THEN** MUST 区分以下三种情形，且 MUST NOT 混为一种：

  | 情形 | 应有结果 |
  |---|---|
  | 目标分区**为空**（该代尚无产物） | `applicable=False`，写明"尚无产物" |
  | 有文件但**不匹配本数据集** | `passed=False`，写明是配置问题 |
  | 有匹配文件 | 执行判据 |

- **AND** 前两种 MUST NOT 返回 `passed=True`

**为什么这条必须存在**：实测 `F20` 与 `F24` 对"没找到文件"给出**相反**的结论
（`passed=False` vs `passed=True`）。同一个状态两种处置，
而 `passed=True` 让"门禁没跑"伪装成"执行过"。

### Requirement: A 轴饱和判据的分母

`F24`（A 轴 `SEH@1` 不得满分）的分母 MUST 是**已评分**的 A 轴 case 数，
MUST NOT 是全部 A 轴标注数。

未评分的 case（池不足 K 被跳过、`rank_after_rerank` 为 `None`）
MUST 从分母中排除。

#### Scenario: 未评分 case 不计入分母

- **WHEN** 某 subject 的 A 轴有 10 条标注，其中 6 条因池不足被跳过
- **THEN** 分母 MUST 为 4，MUST NOT 为 10

#### Scenario: 三路配置下的数字不变

- **WHEN** 结果文件里全部 A 轴 case 都被评分
- **THEN** 修改前后 `SEH@1` MUST 相同

#### Scenario: 低报必须可被看见

- **WHEN** 存在一份单路配置的结果文件，其 A 轴有未评分 case
- **THEN** MUST 有测试断言其 `SEH@1` 用正确口径计算

- **AND** 该测试 MUST 用**单路**文件

#### Scenario: 结果侧未跑不得算作通过

- **WHEN** `F24` 没有找到任何结果文件
- **THEN** `passed` MUST 为 False

- **AND** 若该代产物尚无（分区为空），MUST 返回 `applicable=False` 并说明

#### Scenario: 两个池大小必须分别命名

- **WHEN** 计算轴归属或随机基线
- **THEN** MUST 使用对应的量：

  | 量 | 定义 | 用途 |
  |---|---|---|
  | `n_competitors` | 池中与 gold **同 relation** 的候选数（不含 gold） | 轴派生 |
  | `ranking_pool_size` | 实际参与排名的候选数（含 gold） | 随机基线 `1/N` |

- **AND** `ranking_pool_size` MUST 从竞争集定义取，
  MUST NOT 由 `n_competitors + 1` 推算

- **AND** 实测例外（全部是 C 轴）：`ledger-q11/q12`（`n=0, cs=12`）、
  `billing-c1/c2/c3`（`n=2, cs=9`）

#### Scenario: 随机基线必须按派生轴分组

- **WHEN** 计算某装置的随机基线
- **THEN** 轴归属 MUST 由池结构派生，MUST NOT 读数据集的标注字段

- **AND** 基线 MUST 用 `ranking_pool_size` 的 `1/N`

- **AND** 现有 v2 数据的验收值：

  ```
  axis_baseline_derived(sample) ==
      {"relation_within": 0.3000, "relation_cross": 0.0833}
  ```

- **AND** `relation_cross` MUST 是 `1/12`，MUST NOT 是 `1/1`

#### Scenario: 空轴必须返回缺失值，不得返回 0

- **WHEN** 某个派生轴没有任何查询
- **THEN** 该轴的基线 MUST 为 `None`（或缺席），**MUST NOT 为 `0.0`**

- **AND** 调用方 MUST 显式处理 `None`

**为什么**：`0.0` 作为基线意味着"随机命中率是 0"，于是任何实测值
（哪怕也是 0）都会 `ratio <= baseline` 而报红——
**"没有数据"会伪装成"基线是 0"**。

- **AND** 实测：`billing` 的 `relation_cross` 是空组（三个 relation 全多分支），
  MUST 返回 `None`

#### Scenario: v3 下的判据是"比随机好"

- **WHEN** `F24` 在 v3 装置下执行
- **THEN** 结果侧 MUST **同时**满足两档：

  | 档 | 判据 | 违反形式 |
  |---|---|---|
  | 下限 | `ratio > baseline` | 排序比随机还差 |
  | 上限 | `ratio < ceiling`（`0.9999`） | **数据太简单** |

- **AND** MUST NOT 只设下限：v3 数据要求"每 subject 至少一个单值 relation"，
  而单值 relation 意味着池可能很小（`n_competitors=1` -> 池 2），
  `ratio` 容易满分——**只设下限会放行"数据太简单"**

- **AND** 上限在 v3 下的语义是**数据难度**，不是装置语义：
  v2 里满分意味着"指标测不到区分能力"（装置与数据都有关），
  v3 里满分只说明"这份数据太容易"

#### Scenario: v3 的数据侧恒真必须被登记

- **WHEN** `F24` 在 v3 下检查数据侧（基线是否饱和）
- **THEN** MUST 在代码注释与本节写明：**该判据在 v3 下恒真**

- **AND** 理由：派生 within 的池大小 `= n_competitors + 1 >= 2`，
  基线最大 `1/2 = 0.5`，永远小于 `0.9999`

- **AND** MUST 保留该判据：它防的是"池大小退化成 1"这个形状退化
  （`n_competitors` 全为 0 时基线变 1.0）

- **AND** 真正有判别力的是结果侧（下限 + 上限），MUST NOT 让读者以为两段都在验

#### Scenario: 标注与派生的不一致必须被报告

- **WHEN** 报告某 subject 的轴统计
- **THEN** MUST 报"标注与派生不一致 N/M"

- **AND** 该数字 MUST NOT 依赖门禁使用哪套轴

- **AND** 实测基线：`sample` 0/12、`billing` **3/12**
