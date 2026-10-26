# Spec Delta

## MODIFIED Requirements

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

## ADDED Requirements

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
