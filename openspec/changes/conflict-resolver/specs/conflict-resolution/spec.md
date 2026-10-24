# Spec Delta

## Purpose

定义"一条候选事实应当如何影响既有记忆"的判定契约：把输入归一化到可比较的形式，
按固定优先级决定它属于六类之一，并驱动存储层产生对应的状态迁移。
它不负责检索与作答，只负责在写入前把含糊的自然语言陈述收敛为一个确定的决定。

## ADDED Requirements

### Requirement: 主体与关系的归一化

系统 SHALL 在比较前把主体与关系归一化为规范形式，且归一化 MUST 不改变语义。
归一化 MUST 覆盖大小写、首尾空白、全角半角、常见复数形式与已登记的别名。

#### Scenario: 大小写与空白
- **WHEN** 两条事实的主体分别为 `"Project:Agent-Memory"` 与 `"  project:agent-memory  "`
- **THEN** 归一化后两者相同

#### Scenario: 别名映射到同一规范名
- **WHEN** 别名表登记了 `"包管理器"` 与 `"package manager"` 同义
- **THEN** 两者归一到同一个规范关系名

#### Scenario: 未登记的别名不猜
- **WHEN** 遇到别名表未登记的表达
- **THEN** 保留原值（仅做基础归一），并在判定结果中标记 `normalized = false`，
  而不是强行映射到一个可能错误的名字

#### Scenario: 归一化不合并不同主体
- **WHEN** 两个主体的归一化结果不同
- **THEN** 它们被视为不同的事实，绝不互相覆盖

#### Scenario: 空主体被拒绝
- **WHEN** 主体或关系归一化后为空
- **THEN** 判定过程报错，不产生任何写入

### Requirement: 六类判定

系统 SHALL 把每次候选事实判定为且仅判定为以下六类之一：
`NOOP`（无变化）、`ADD`（全新）、`MERGE`（补充，旧值仍成立）、
`SUPERSEDE`（取代，旧值失效）、`CONFLICT`（矛盾且无法裁决）、
`BRANCH`（条件不同，并存）。

#### Scenario: 重复陈述
- **WHEN** 当前已有 ACTIVE 条目，候选的值、条件与权威级别与它完全相同
- **THEN** 判定为 `NOOP`

#### Scenario: 全新事实
- **WHEN** 该逻辑键下不存在任何条目
- **THEN** 判定为 `ADD`

#### Scenario: 旧值仍然成立
- **WHEN** 候选值包含旧值的信息且旧值并未失效（例如旧值 `"pnpm"`，候选 `"pnpm 加 workspace"`）
- **THEN** 判定为 `MERGE`

#### Scenario: 旧值被取代
- **WHEN** 候选值不同、权威级别不低于旧值，且被判定为"陈述新状态"
- **THEN** 判定为 `SUPERSEDE`

#### Scenario: 权威不足的相反陈述
- **WHEN** 候选值的权威级别低于既有条目
- **THEN** 判定为 `CONFLICT`，既有条目保持 ACTIVE

#### Scenario: 条件不同
- **WHEN** 同一主体与关系下已有 ACTIVE 条目，但候选携带不同的条件
- **THEN** 判定为 `BRANCH`，两者并存

#### Scenario: 无法确认是否为新状态
- **WHEN** 权威级别相当、值不同，且变更识别无法确认它是新状态
- **THEN** 判定为 `CONFLICT`（兜底），而不是猜测覆盖

### Requirement: 规则优先级与完备性

系统 SHALL 按固定顺序评估规则，命中即短路返回。
规则集合 MUST 完备：任何合法输入都必须落入六类之一，不得有无出口的情形。

#### Scenario: 多规则同时匹配时按序短路
- **WHEN** 一条候选同时满足"重复"与"条件不同"的表面条件
- **THEN** 按登记顺序取第一条命中的规则，结果可预测

#### Scenario: 兜底保证完备
- **WHEN** 前六条规则均未命中
- **THEN** 返回 `CONFLICT`，而不是抛出异常或返回未定义值

#### Scenario: 规则顺序不可静默改变
- **WHEN** 有人调整规则顺序
- **THEN** 至少一条断言顺序的测试失败，指出哪条规则被移动

### Requirement: 变更识别与归因

系统 SHALL 区分"陈述新状态"与"重复旧状态"，并记录该判断来自规则还是模型。

#### Scenario: 规则命中变更标记
- **WHEN** 文本包含"改成""现在""不再""以前…现在…"等标记
- **THEN** 判定为新状态，且 `change_source = "rule"`

#### Scenario: 规则未命中时用模型兜底
- **WHEN** 文本不含任何标记
- **THEN** 调用模型做二分类，且 `change_source = "llm"`

#### Scenario: 模型输出不可解析
- **WHEN** 模型返回的内容无法解析为布尔判断
- **THEN** 视为"无法确认"，走 `CONFLICT` 兜底，并记录 `change_source = "failed"`

#### Scenario: 关闭模型后仍可运行
- **WHEN** 以禁用模型的模式运行
- **THEN** 仅用规则完成判定，未命中标记的候选一律走 `CONFLICT` 兜底，
  且结果中标记 `change_source = "disabled"`

#### Scenario: 归因可统计
- **WHEN** 汇总一批判定结果
- **THEN** 能按 `change_source` 分组统计各来源的占比

### Requirement: 判定驱动存储迁移

系统 SHALL 把判定结果映射为存储层的具体操作，且映射 MUST 维持 C2 的所有不变量。

#### Scenario: NOOP 不改变状态
- **WHEN** 判定为 `NOOP`
- **THEN** 不产生新条目，只写一条 NOOP 审计事件

#### Scenario: ADD 直接插入
- **WHEN** 判定为 `ADD`
- **THEN** 调用插入，新条目为 ACTIVE

#### Scenario: MERGE 产生新版本且旧值仍可查
- **WHEN** 判定为 `MERGE`
- **THEN** 旧条目转为 SUPERSEDED、写入 `valid_to`，新条目为 ACTIVE，
  且时间线能查到两者的 `reason` 分别为"补充"与"被补充"

#### Scenario: SUPERSEDE 是原子取代
- **WHEN** 判定为 `SUPERSEDE`
- **THEN** 走 C2 的原子取代，读者不会看到"无有效值"的瞬间

#### Scenario: CONFLICT 不动既有有效值
- **WHEN** 判定为 `CONFLICT`
- **THEN** 既有条目保持 ACTIVE，新条目以 CONFLICTED 落库并通过关联字段指向它，
  对当前值的查询结果不变

#### Scenario: BRANCH 两条并存
- **WHEN** 判定为 `BRANCH`
- **THEN** 两条均为 ACTIVE 且条件不同，查询各自条件时各返回一条

#### Scenario: 判定失败不留半成品
- **WHEN** 存储操作失败
- **THEN** 整个判定不产生任何写入，错误信息包含判定类型与失败原因

### Requirement: 判定结果的可解释性

系统 SHALL 为每次判定返回足以解释"为什么是这个结论"的信息。

#### Scenario: 结果包含命中规则
- **WHEN** 查看一次判定结果
- **THEN** 其中包含六类判定类型、命中的规则名、归一化后的键、
  被比较的既有条目 id（若有）、以及变更来源

#### Scenario: 结果可序列化
- **WHEN** 把判定结果写入追踪或报告
- **THEN** 能完整序列化为 JSON，字段无语义损失

#### Scenario: 冲突附带分歧说明
- **WHEN** 判定为 `CONFLICT`
- **THEN** 结果中同时给出既有值与候选值，便于上层生成"两种说法"的追问

### Requirement: 场景集的标签状态

系统 SHALL 区分"机器提议的标签"与"人工确认的标签"，且指标 MUST 只在确认子集上
作为验收依据。

#### Scenario: 新生成的场景标记为提议
- **WHEN** 场景集由脚本生成
- **THEN** 每条带 `label_status = "proposed"`，不含确认者信息

#### Scenario: 人工确认后改变状态
- **WHEN** 标注者确认一条场景的期望判定
- **THEN** 该条 `label_status = "confirmed"`，并记录确认者与时间

#### Scenario: 指标区分口径
- **WHEN** 报告判定质量
- **THEN** 确认子集与提议子集的分数分列，且验收结论只引用确认子集

#### Scenario: 双人一致性
- **WHEN** 两名标注者各自确认同一批场景
- **THEN** 报告 Cohen's κ，并列出不一致的具体条目供讨论

#### Scenario: 一致性过低时不宣称结论
- **WHEN** κ 低于 0.7
- **THEN** 报告明确标注"标签一致性不足，结论强度受限"，
  而不是照常给出 macro-F1 并宣称达标
