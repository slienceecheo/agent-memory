# memory-store Specification

## Purpose
定义记忆条目的持久化契约：一条事实如何被表示、如何被取代、如何在任意时间点被正确查询，
以及如何保证"同一组事实在同一时刻最多只有一个有效值"这条不变量不被任何调用方绕过。
它不关心冲突怎么判定，只关心判定结果一旦产生，存储层能否无损、可审计地表达它。

## Requirements

### Requirement: 双时态条目表示

系统 SHALL 为每条记忆同时记录两种时间：现实世界的有效区间（`valid_from` / `valid_to`）
与系统得知它的时刻（`recorded_at`）。两者 MUST 可独立设置。
所有时间 MUST 带时区，系统内部统一以 UTC 存储与比较。

#### Scenario: 补录一条过去有效的事实
- **WHEN** 写入一条 `valid_from` 早于 `recorded_at` 的条目
- **THEN** 该条目被接受，且 `active_at(过去某时刻)` 能查到它

#### Scenario: 撤销一条错误录入
- **WHEN** 一条条目的录入被发现是错的，执行撤回
- **THEN** 该条目状态变为 RETRACTED，`recorded_at` 保持原值不变，
  且历史查询仍能看到它曾经存在

#### Scenario: 未结束的有效期
- **WHEN** 条目仍然有效
- **THEN** `valid_to` 为空，且被判定为"当前有效"

#### Scenario: 不接受无时区的时间
- **WHEN** 调用方传入一个不带时区的 `datetime`
- **THEN** 系统报错并要求带时区，而不是假定为本地时区（会导致静默的时区偏差）

#### Scenario: 结束时间不得早于起始时间
- **WHEN** 传入的 `valid_to` 早于或等于 `valid_from`
- **THEN** 系统拒绝写入，因为零长度或负长度区间既查不到又占着有效位

### Requirement: 唯一有效值不变量

系统 SHALL 保证在任意时刻，同一 `(owner, scope, subject, relation, condition)`
最多只有一条 ACTIVE 条目。该不变量 MUST 由存储层强制，而不能依赖调用方自觉。
所有键列 MUST NOT 为空。

#### Scenario: 插入第二条同键有效条目
- **WHEN** 已存在一条同键 ACTIVE 条目时再尝试插入 ACTIVE
- **THEN** 系统抛出 `InvariantViolation`，且该次写入整体回滚，库内不留下任何部分写入

#### Scenario: 无条件事实同样受约束
- **WHEN** 两条条目的 `condition` 均为空
- **THEN** 仍然只能有一条 ACTIVE——空值不得绕过唯一性

#### Scenario: 键列为空被拒绝
- **WHEN** 尝试写入 `owner` / `scope` / `subject` / `relation` 中任一为空的行
- **THEN** 系统在数据库层面拒绝，而不只是在应用层校验

#### Scenario: 条件不同可共存
- **WHEN** 两条条目的 subject 与 relation 相同，但 `condition` 不同
- **THEN** 两条均可为 ACTIVE，互不冲突

#### Scenario: 作用域不同不互相污染
- **WHEN** 同一 subject/relation 分别存在于 `project` 与 `user` 两个 scope
- **THEN** 两者互不影响，各自的 ACTIVE 约束独立生效

#### Scenario: 被取代后腾出位置
- **WHEN** 旧条目的 `valid_to` 被写入且状态转为 SUPERSEDED
- **THEN** 同键可以再插入一条新的 ACTIVE 条目

### Requirement: 有效区间不得重叠

系统 SHALL 保证同一逻辑键下任何两条未撤回条目的有效区间不重叠，
且该约束 MUST 由存储层强制。

#### Scenario: 插入与现有区间重叠的历史条目
- **WHEN** 新条目的有效区间与同键已存在的未撤回条目相交
- **THEN** 系统拒绝写入并指出发生重叠

#### Scenario: 未结束的区间参与重叠检测
- **WHEN** 已有一条 `valid_to` 为空的条目，再插入一条起始更晚的条目
- **THEN** 判定为重叠并拒绝（未结束的区间必须被视为延伸到无穷远）

#### Scenario: 更新区间同样受限
- **WHEN** 通过更新条目把区间改成与另一条重叠
- **THEN** 系统拒绝该更新

#### Scenario: 任意时刻至多一条有效
- **WHEN** 对库中随机取一个时间点查询
- **THEN** `active_at` 返回零条或一条，绝不返回多条

### Requirement: 取代是原子操作

系统 SHALL 把"关闭旧版本 + 打开新版本 + 记录审计"作为一个不可分割的操作。
MUST NOT 暴露需要调用方分两步完成的取代接口。

#### Scenario: 取代成功
- **WHEN** 用新条目取代一条 ACTIVE 条目
- **THEN** 旧条目变为 SUPERSEDED、`valid_to` 被设为新条目的 `valid_from`、
      `superseded_by` 指向新条目，新条目为 ACTIVE，整个过程在一个事务内完成

#### Scenario: 取代中途失败
- **WHEN** 取代过程中任意一步失败
- **THEN** 整个操作回滚，旧条目仍为 ACTIVE，新条目不存在，不留断链

#### Scenario: 旧条目已自然到期
- **WHEN** 被取代的条目原本已有 `valid_to`
- **THEN** 保留其原有 `valid_to`，不被新条目的起始时间覆盖

#### Scenario: 该键已有有效值时不能直接插入
- **WHEN** 对一个已有 ACTIVE 条目的键调用 `insert`
- **THEN** 系统返回 `ActiveExists` 错误并提示改用 `supersede`，而不是抛出底层数据库异常

#### Scenario: 读者不会看到无有效值的瞬间
- **WHEN** 取代操作执行期间另一个连接查询该键
- **THEN** 它要么看到旧版本，要么看到新版本，绝不看到"没有有效值"

### Requirement: 状态迁移合法性

系统 SHALL 只允许以下状态迁移，其余组合 MUST 被拒绝并说明原因：
ACTIVE → SUPERSEDED / CONFLICTED / RETRACTED；
CONFLICTED → ACTIVE / SUPERSEDED / RETRACTED；
SUPERSEDED → RETRACTED。
RETRACTED 是终止态。同状态调用 MUST 视为幂等空操作并记录事件，而不是报错。

#### Scenario: 合法迁移
- **WHEN** 一条 ACTIVE 条目被取代
- **THEN** 状态变为 SUPERSEDED，`valid_to` 被写入，`superseded_by` 指向新条目

#### Scenario: 非法迁移被拒绝
- **WHEN** 试图把 RETRACTED 条目改回 ACTIVE
- **THEN** 系统抛出 `InvalidTransition`，错误信息同时包含当前状态与目标状态

#### Scenario: 撤回一条历史记录
- **WHEN** 发现一条已 SUPERSEDED 的历史记录是伪造的，执行撤回
- **THEN** 允许迁移到 RETRACTED

#### Scenario: 撤回一条未裁决的冲突记录
- **WHEN** 一条 CONFLICTED 条目被确认是错误信息，执行撤回
- **THEN** 允许迁移到 RETRACTED

#### Scenario: 重复调用同一操作
- **WHEN** 对已是 SUPERSEDED 的条目再次执行取代，或对已是 RETRACTED 的条目再次撤回
- **THEN** 不改变状态，返回成功并记录一条事件（使重试安全）

#### Scenario: 冲突条目被裁决
- **WHEN** 一条 CONFLICTED 条目经裁决后成为有效值
- **THEN** 状态变为 ACTIVE，原有效条目转为 SUPERSEDED

### Requirement: 时间点查询

系统 SHALL 支持按**现实时间**查询某 `(owner, scope, subject, relation, condition)`
在当时有效的条目。查询 MUST 包含后来被取代的版本，MUST 排除已撤回与未裁决冲突的版本。

#### Scenario: 三个版本的历史
- **WHEN** 同一键依次写入 v1（有效至 t2）、v2（有效至 t3）、v3（至今）
- **THEN** `active_at(t1)` 返回 v1，`active_at(t2 之后)` 返回 v2，`active_at(现在)` 返回 v3

#### Scenario: 当前有效的事实能被查到
- **WHEN** 查询一个 `valid_to` 为空的条目
- **THEN** 必须返回它，而不是因为区间未结束而被过滤掉

#### Scenario: 该时间点无记录
- **WHEN** 查询的时间早于该键的第一条记录
- **THEN** 返回空，而不是返回最早的那条

#### Scenario: 已撤回的事实任何时刻都不返回
- **WHEN** 一条条目已被撤回
- **THEN** 对任意时间点查询都不返回它，但它仍出现在时间线里

#### Scenario: 冲突未裁决时不返回当前值
- **WHEN** 该键只有 CONFLICTED 条目而没有 ACTIVE 条目
- **THEN** 返回空，表明"当前值未定"

#### Scenario: 条件为空时的查询
- **WHEN** 查询时不指定 condition
- **THEN** 只返回 `condition` 为空的条目，不把条件分支混入无条件事实

### Requirement: 完整时间线

系统 SHALL 按版本顺序返回某 `(owner, scope, subject, relation)` 下的全部版本，
包含已被取代与已撤回的条目。

#### Scenario: 时间线包含全部版本
- **WHEN** 一个键经历 3 次变更后查询时间线
- **THEN** 返回 3 条，按版本号升序，且每条带有其状态与变更原因

#### Scenario: 时间线包含条件分支
- **WHEN** 同键存在一个无条件条目与一个条件分支
- **THEN** 时间线同时返回两者，并标明各自的 condition

#### Scenario: 空键的时间线
- **WHEN** 查询一个从未写入过的键
- **THEN** 返回空列表，不抛异常

#### Scenario: 同一值再次出现（A→B→A）
- **WHEN** 某键依次写入 A、被 B 取代、再写回 A
- **THEN** 产生第三条版本且其为 ACTIVE，而不是因为"内容与旧版本相同"被当作重复而丢弃

### Requirement: 审计事件

系统 SHALL 为每次写入产生一条审计事件，包含条目 id、相关条目 id、判定类型、
**必填的原因**、操作者与时间。审计记录 MUST 只可追加。

#### Scenario: 新增产生 ADD 事件
- **WHEN** 写入一条全新条目
- **THEN** 产生一条 `decision=ADD` 的事件，且可关联到该条目

#### Scenario: 取代产生 SUPERSEDE 事件
- **WHEN** 一条旧条目被新条目取代
- **THEN** 产生 `decision=SUPERSEDE` 的事件，同时能查到旧条目 id 与新条目 id

#### Scenario: 撤回产生 RETRACT 事件
- **WHEN** 执行撤回
- **THEN** 产生 `decision=RETRACT` 事件，并记录撤回原因

#### Scenario: 裁决产生 RESOLVE 事件
- **WHEN** 一条冲突被裁决
- **THEN** 产生 `decision=RESOLVE` 事件，记录裁决依据

#### Scenario: 缺少原因被拒绝
- **WHEN** 调用写入接口但不提供原因
- **THEN** 系统报错，因为没有原因的审计记录无法用于追责

#### Scenario: 事件不可修改
- **WHEN** 试图更新或删除一条已写入的审计事件
- **THEN** 系统拒绝该操作

#### Scenario: 事件不可被覆盖写入
- **WHEN** 使用"插入或替换"式语句尝试覆盖已有事件
- **THEN** 系统同样拒绝，审计记录只可追加

#### Scenario: 错误可以纠正但不可抹除
- **WHEN** 发现某条审计事件的内容有误
- **THEN** 系统允许追加一条 `CORRECTION` 事件指向它，但不允许修改原事件

### Requirement: 幂等与序号

系统 SHALL 为每条新条目分配全局单调递增的写入序，并为同一逻辑键分配递增的版本号。
对**当前有效**的相同内容重复写入 MUST NOT 产生新的条目。

#### Scenario: 重复写入相同内容
- **WHEN** 当前已有 ACTIVE 条目，其键、值、条件、权威级别与再次写入的完全相同
- **THEN** 返回已存在的条目 id，条数与版本号均不变，且记录一条 `decision=NOOP` 事件

#### Scenario: 内容相同但旧版本已被取代
- **WHEN** 写回一个曾经存在、但已被取代的旧值
- **THEN** 创建新版本并使其成为 ACTIVE，而不是返回那条旧的 SUPERSEDED 条目

#### Scenario: 写入序全局单调
- **WHEN** 连续写入 5 条不同条目（可以是不同键）
- **THEN** 它们的写入序严格递增

#### Scenario: 版本号在键内递增
- **WHEN** 同一键经历 3 次变更
- **THEN** 三个版本的版本号依次为 1、2、3

#### Scenario: 并发写入不为同键产生两条有效条目
- **WHEN** 两个事务同时为同一键写入 ACTIVE 条目
- **THEN** 只有一个成功，另一个收到明确的冲突错误（不得伪装成超时或其他错误）

### Requirement: 存储实现可替换

系统 SHALL 通过一个协议暴露存储能力，并提供一组与实现无关的契约测试。
新增实现 MUST 能通过同一组契约测试，无需修改测试代码。

#### Scenario: 注册新实现
- **WHEN** 为契约测试套件注册一个新的存储实现
- **THEN** 全部契约断言自动在其上运行，测试代码不改动

#### Scenario: 违反不变量的实现被发现
- **WHEN** 某个实现允许同键两条 ACTIVE
- **THEN** 契约测试失败并指出是哪条不变量被破坏

#### Scenario: 契约覆盖全部验收标准
- **WHEN** 审阅契约测试套件
- **THEN** 每条验收标准都有对应的断言函数，且存在一个聚合入口统一运行

### Requirement: 向量与全文索引的存储

系统 SHALL 提供全文索引与向量列的存储能力，供后续检索变更使用。
本变更只负责存储与基本查询，MUST NOT 实现融合排序。

#### Scenario: 写入时同步索引
- **WHEN** 写入一条带文本与向量的条目
- **THEN** 全文索引与向量列同时可用，且可通过词面查询命中该条目

#### Scenario: 中文词面查询可命中
- **WHEN** 用两个汉字组成的词查询中文正文
- **THEN** 能命中包含该词的条目（不得因为分词器把整句当一个 token 而全部落空）

#### Scenario: 索引与主表一致
- **WHEN** 条目被取代或撤回
- **THEN** 它不再出现在"当前有效"的全文检索结果中，但仍保留在时间线里

#### Scenario: 向量维度不符
- **WHEN** 写入的向量长度与存储声明的维度不一致
- **THEN** 系统报错并拒绝写入，而不是静默截断或补零

#### Scenario: 单字查询的已知限制
- **WHEN** 用单个汉字查询
- **THEN** 行为按文档所述的降级策略执行，且该限制被明确记录，而不是静默返回空
