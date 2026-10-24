# 设计：冲突感知长期记忆层 v1

> 状态：草案，待拍板 · 2026-10-24
> 对应需求：`docs/requirements/agent-memory.md`

## 1. 一句话设计

写入时用**确定性状态机**裁决冲突，读取时用**冲突感知重排**选择证据，
两侧都按**五类冲突**打标签，使每一次失败都能归因到具体环节。

## 2. 数据模型

### 2.1 记忆条目（MemoryItem）

```python
class MemoryItem(BaseModel):
    id: str                        # ulid
    subject: str                   # 归一化后的实体（如 "project:agent-memory"）
    relation: str                  # 归一化后的谓词（如 "package_manager"）
    value: str
    condition: str | None          # 条件冲突用；None 表示无条件成立
    scope: Scope                   # user / project / task / lesson
    owner: str                     # 命名空间（v1 单用户，固定 "default"，但字段先留）
    ordinal: int                   # 单调递增写入序，用于 FactConsolidation 的"较新事实序号更大"
    status: Status                 # ACTIVE / SUPERSEDED / CONFLICTED / RETRACTED
    valid_from: datetime           # 现实中开始有效（默认=对话时间）
    valid_to: datetime | None      # 现实中失效；None 表示仍然有效
    recorded_at: datetime          # 系统写入时间（双时态的另一半）
    stated_time: str | None        # 用户原话中的时间表述，原样保留
    source: Source                 # session_id / turn_id / speaker / authority
    superseded_by: str | None
    linked_ids: list[str]          # 与本次变更相关的其他条目（对照/冲突/条件分支）
    confidence: float
```

`Status` 语义：

| 状态 | 含义 | 何时进入 |
|---|---|---|
| `ACTIVE` | 当前有效 | 新增且无冲突，或条件分支 |
| `SUPERSEDED` | 被更新的真值取代 | 判定为 SUPERSEDE 且 `valid_to` 已写入 |
| `CONFLICTED` | 与既有事实矛盾但无法裁决 | 判定为 CONFLICT（来源不明 / 权威相当） |
| `RETRACTED` | 用户显式撤回 | 用户说"忘掉 / 不算" |

**关键不变量**：`(owner, scope, subject, relation, condition)` 在任一时刻最多只有一个
`ACTIVE` 条目。这条不变量由数据库唯一索引 + 事务保证，而不是靠代码自觉。
`scope` 必须进索引：否则 `project:agent-memory` 的包管理器与 `user` 级偏好会互相污染。

`CONFLICTED` 不占 `ACTIVE` 位：声明冲突时，**旧条目保持 ACTIVE**（它是已被确认的
历史真值，查询仍应返回它），新条目进入 `CONFLICTED` 并通过 `linked_ids` 指向旧条目。
读路径把 `CONFLICTED` 作为"存在分歧"的信号，用来降置信度和触发追问，而不是
把它当作当前有效值。这样唯一索引与"冲突仍可检索"两个要求不打架。

### 2.2 为什么不用 `UPDATE` 覆盖

mem0 v1 用 UPDATE/DELETE，v3 改成 ADD-only，两者都在走极端：

- `UPDATE` 覆盖：丢掉历史，无法回答"上个月这个值是什么"，也无法审计"为什么改的"
- `ADD-only`：新旧并存，把裁决推给检索排序，而排序只看语义相似度，不看时间

双时态 + `SUPERSEDED` 让"当前值"是一次**查询**（`WHERE valid_to IS NULL`），
而不是一次破坏性写入。这同时满足了审计和正确性。

## 3. 写路径

```
原始对话
   │
   ▼ ① 抽取（LLM，可缓存）
candidates: [(subject, relation, value, condition, stated_time)]
   │
   ▼ ② 归一化（确定性，无 LLM）
canonical: subject/relation 别名表 + 大小写/复数/中英归一
   │
   ▼ ③ 冲突判定（确定性规则优先，LLM 仅兜底边界）
Decision ∈ {NOOP, MERGE, SUPERSEDE, CONFLICT, BRANCH}
   │
   ▼ ④ 落库（单事务，保证不变量）
新条目 + 旧条目状态迁移 + linked_ids + 审计事件
   │
   ▼ ⑤ 发事件（Langfuse span）
```

### 3.1 判定规则（按顺序短路，前一条命中即返回）

判定集合是 **6 类**，且必须**完备**（任何输入都有唯一出口）：

`{NOOP, ADD, MERGE, SUPERSEDE, CONFLICT, BRANCH}`

| 顺序 | 条件 | 结论 |
|---|---|---|
| 1 | 同 key 存在 ACTIVE，且归一化后 value 相同 | `NOOP` |
| 2 | 同 key **不存在** ACTIVE | `ADD` |
| 3 | 同 `(s, r)` 但 condition 不同（或无条件的 ACTIVE 已存在） | `BRANCH` |
| 4 | 同 key，value 不同，且新值是旧值的**扩展**（旧值仍为真，如 "pnpm" → "pnpm，前端用 workspace"） | `MERGE` |
| 5 | 同 key，value 不同，authority **不低于**旧值，且被判定为"陈述新状态" | `SUPERSEDE` |
| 6 | 同 key，value 不同，authority **低于**旧值 | `CONFLICT` |
| 7 | 其余（同 key、value 不同、权威相当、但无法确认是状态变更） | `CONFLICT` |

第 7 条是兜底：它保证表格完备，也保证**永远不会因为判定不明而写坏唯一索引**——
不确定时选择"并存 + 标记分歧"，而不是猜一个覆盖。

`authority` 是枚举而非自由文本：

| 级别 | 来源 | 例 |
|---|---|---|
| 3 | 用户直接陈述 | 对话中用户自己说 |
| 2 | 用户提供的文档 | 用户上传的规范、README |
| 1 | 系统/agent 推断 | 从代码里推断出的约定 |
| 0 | 第三方记录 | 工单备注、他人转述 |

`MERGE` 与 `SUPERSEDE` 的区别在于**旧值是否仍然为真**：`MERGE` 的旧值仍成立
（只是不完整），`SUPERSEDE` 的旧值已失效。两者都写入 `valid_to`，但
`events.reason` 不同，时间线上可以区分"补充"和"改主意"。

### 3.2 "语义上是变更"如何判定（唯一允许 LLM 参与裁决的地方）

只有一处：判断新语句是**在陈述新状态**（"现在改用 npm 了"）还是
**在重复旧状态**（"我们用 npm"）。做法：

- 优先用正则/词表匹配变更标记（"改成 / 现在 / 不再 / 以前是…现在是…"）
- 无标记时，用 LLM 做一次二分类，输出 `{"is_update": bool, "confidence": float}`
- **该判断的准确率单独报告**，并且提供"完全不用 LLM"的对照（纯规则）作为消融

这样即使 LLM 判断错了，也能在报告里看见损失了多少，而不是含糊地归因"模型不行"。

## 4. 读路径

```
query + 任务上下文
   │
   ├─ ① BM25（SQLite FTS5，中英混排用 bigram）
   ├─ ② dense（qwen3.7-text-embedding-flash，text_type=query，1024 维）
   └─ ③ 实体邻接（同 subject 的其他 relation，用于多跳）
   │
   ▼ ④ 融合（RRF，k=60）
   │
   ▼ ⑤ fitness-for-use 重排
score = w1·relevance + w2·temporal_validity + w3·condition_match
      + w4·source_authority + w5·recency
   │
   ▼ ⑥ 冲突裁决 + 动作策略
   - 唯一 ACTIVE → 直答
   - 多条 ACTIVE 且 condition 不同 → 带前提回答
   - 存在 CONFLICTED 兄弟条目 → 降置信度 + 说明分歧 + 必要时追问
   - 无命中 → 明确说"没有记录"，禁止编造
```

### 4.1 条件匹配怎么算（否则 w3 是死权重）

`condition` 是自由文本，但**不交给 LLM 每次判断**（不可复现）。做法：

1. 抽取时把 condition 归一化到少量结构化槽位，如
   `{"activity": "coding"} / {"time": "morning"} / {"task_type": "review"}`
2. 查询侧同样抽取槽位（同一次 LLM 调用顺带产出）
3. `condition_match` = 槽位重叠度（Jaccard）；任一侧缺失则取 0.5（中性），而不是 0
   （避免"没说条件"被当成"条件不匹配"）

无条件的 ACTIVE 条目与条件分支同时存在时：**都返回**，无条件的作为默认值，
条件分支作为"如果当前是 X 场景则更适用"的补充。这也正是"开会我喜欢早上 /
写代码我喜欢深夜"应有的行为。

### 4.2 冲突之后怎么复原

`CONFLICTED` 是等待裁决的中间态，出口有三条（写进同一变更的后续任务）：

- 用户澄清 → 被选中的分支转 ACTIVE，另一条转 SUPERSEDED（`reason=user_resolved`）
- 更高 authority 来源出现 → 按 3.1 规则重新判定
- 长期未裁决 → 保持 CONFLICTED，读路径持续降置信

### 4.3 为什么用 RRF 而不是加权分数

BM25 分数无界、cosine 有界，直接加权需要归一化，而归一化参数会随数据集漂移，
导致换 benchmark 就要重调。RRF 只用排名，跨数据集稳定，代价是丢掉"差多少"的信息——
对我们这种要跑三个 benchmark 的场景，稳定性更重要。

### 4.4 重排权重的确定方式

**不手调**。用自建 60 条冲突集做小规模网格搜索，报告最优权重及其置信区间，
并把"手写默认权重"作为对照。这样权重是**测出来的**，不是拍的。

## 5. 存储

```python
class MemoryStore(Protocol):
    def add(self, item: MemoryItem) -> AddResult: ...
    def search(self, q: Query, k: int) -> list[Scored]: ...
    def timeline(self, subject: str, relation: str) -> list[MemoryItem]: ...
    def active_at(self, s: str, r: str, c: str | None, t: datetime) -> MemoryItem | None: ...
```

- 默认实现：SQLite（`items` 表 + `items_fts` 虚表 + `vec_items` 虚拟表 + `events` 审计表）
- 可选实现：Postgres + pgvector
- 两套实现共享同一组契约测试，换库不改数字

`events` 表记录每次写入的 `(item_id, decision, reason, actor, at)`，
是时间线 UI 和审计的数据源。

## 6. 评测设计

### 6.1 外部基准怎么接（先说清度量口径）

| 基准 | 角色 | 口径 |
|---|---|---|
| **FactConsolidation-SH/MH** | 主力：证明"确定性裁决"有效 | 用官方 `substring_exact_match`；**两条曲线分别报告**：`resolver-only`（绕过 LLM 抽取，直接把有序事实流喂给状态机）与 `end-to-end`（走完整抽取）。前者对齐 80.25% 的公开结果，后者才是"系统效果"。**G4 指的是 end-to-end ≥ 0.80** |
| **MemConflict** | 主力：证明三类冲突都能处理 | 用官方脚本的 AA 与 SEH@K；adapter 只在 D1 做最小样例验证，接口不匹配就降级为"只报 AA + 自建集" |
| **LongMemEval** | 辅助：证明不是只会做题 | 官方 LLM-judge；judge 结果**必须缓存**（见 6.3） |
| 自建 60 条冲突集 | 主力：G2 + 权重搜索 | 见 6.2 |
| 自建 20 条依赖链 | 主力：G5 | 见 6.4 |

FactConsolidation 的序号语义映射到 `ordinal` 字段（写入序），不依赖 `recorded_at`，
因为 benchmark 的"较新"是**列表位置**而不是真实时间。

### 6.2 自建 60 条冲突集：一个数据集，两种用法

- **内容**：每条形如 `(多轮对话片段, 抽取后应有的 (s,r,v,c), 期望判定, 查询, gold 记忆 id, gold 答案)`
- **判定标签分布**：6 类各 10 条（60 条），确保 `MERGE` / `BRANCH` 这些稀有类有样本
- **划分**：dev 40 / test 20。**权重搜索只用 dev，G2 与主表只报 test**
- **κ**：第二标注者是我的独立二次标注（隔天、不看第一遍结果），如实说明是
  "same-annotator retest" 而不是双人；κ 达不到 0.7 就重标，达不到就降低 G2 的声明强度

### 6.3 判定与评测的可复现性

| 组件 | 是否确定性 | 处理 |
|---|---|---|
| 状态机 / 检索 / 打分 | 是 | 直接可比 |
| LLM 抽取 | 否 | 结果按 `sha256(model|prompt|input)` 缓存并提交到 `data/cache/` |
| LLM judge | 否 | 同上；judge 模型固定版本，缓存随仓库提交 |
| Embedding | 否（实测漂移） | 100% 预生成并提交，评测路径**禁止冷启动** |

因此 G6 的口径修正为：**"warm cache 下逐位一致"**，并额外提供一个
`--check-cache` 命令验证缓存完整性。这是可测试的，也是诚实的。

### 6.4 自建 20 条依赖链任务

- **形态**：每条 = 3~5 个连续 session 的编码任务，后一个任务**必须**用到前一个
  session 确立的约定（如"测试只跑 pytest"、"迁移脚本命名规则"），否则做不对
- **环境**：固定的小型 repo 模板 + 容器内执行 + 客观测试（不是 LLM 判分）
- **成功判定**：该 session 结束时仓库测试全绿 **且** 满足本 session 的额外断言
- **三组对照**：`empty`（无记忆）/ `naive-rag`（把历史全量塞进 top-k）/
  `ours`（完整记忆层）
- **统计**：n=20 做 15pp 的**点估计是不够的**。改为报告三组的成功率与
  配对 bootstrap CI，并把 G5 的验收标准改成"`ours` 相对 `naive-rag` 的
  配对差异 95% CI 下界 > 0"，而不是硬性 15pp

### 6.5 四类失败归因的判定

每条样本由 harness 自动打一个主标签（规则化，不用 LLM）：

1. `NOT_RECALLED`：gold 记忆 id 不在 top-K
2. `LOW_RANKED`：在 top-K 但不在 top-1，且最终答案错
3. `CONFLICT_MISSED`：存在 CONFLICTED 条目但策略未降置信/未追问，且答案错
4. `GENERATION_ERROR`：检索对且无冲突，答案仍错

这四类覆盖所有"答案错"的情形，且每类都有可复算的判定脚本。

## 7. 非目标（再强调）

- 不做多模态、不做分布式
- 不做通用 RAG
- 不做 reflection 调度
- 不接 harness2 作为主线（延伸项，跑通算加分）
- **v1 单租户**：`owner` 字段先留着，但不做多用户隔离、鉴权、配额
- **不做冲突的自动历史回溯修复**：已被错误 SUPERSEDE 的条目，v1 只提供
  `timeline` 查证 + 手动 `retract`，不自动回滚

## 8. 可观测性（G7 的落地方式）

**关键决定：代码不直接依赖 Langfuse SDK，而是依赖一个 `Tracer` 协议。**

```python
class Tracer(Protocol):
    def span(self, name: str, **attrs) -> ContextManager[Span]: ...
```

- `LangfuseTracer`：环境变量 `LANGFUSE_*` 存在时启用（用 Docker Compose 自托管）
- `JsonlTracer`：默认实现，写 `runs/<run_id>/events.jsonl`，零依赖、可提交、可复现

理由：Langfuse 需要 Docker + 网络，如果评测必须依赖它，CI 就跑不起来，
G6 的"warm cache 可复现"也就无从谈起。JSONL 是主路径，Langfuse 是展示层。

G7 的验收标准相应写成：**"JSONL 里每条 add/search/resolve 都带 conflict_type 与
latency，且同一数据可在 Langfuse 看板复现"**，前者可 CI 校验，后者人工验收。

## 8. 被否决的备选方案

| 方案 | 否决理由 |
|---|---|
| fork mem0 打补丁 | 维护者已把 ADD-only 定为 by design（#4896/#4904 均 close），逆架构改造成本高于自写；且简历叙事变成"我改了 mem0" |
| OpenViking 当后端 | AGPLv3；最有价值的部分是别人的，只能做浅层工作 |
| 用 LLM 端到端裁决冲突 | 无法归因，也无法给出"若不用 LLM 会怎样"的对照，评测岗最忌讳这个 |
| 上 Neo4j / Qdrant | 数据量在 10^4 量级，SQLite/pgvector 完全够；引入等于给自己造运维债 |

## 9. 风险与对策

| 风险 | 对策 |
|---|---|
| 自建 60 条冲突集有主观性 | 隔天二次标注 + 报告一致性；同时给公开 benchmark 结果 |
| MemConflict / MemoryAgentBench adapter 接口对不上 | D1 先跑通最小样例，不通就只保留 FactConsolidation |
| 跨任务任务集说服力弱 | 同时报 LongMemEval；harness2 作为延伸 |
| LLM 抽取不稳定 | 所有抽取结果缓存；失败率单独报告；提供纯规则对照 |
| 权重网格搜索过拟合 | dev/test 划分，只报 test；给出权重敏感性曲线 |
| 自建集量太小（60 条）统计功效低 | 所有结论报 bootstrap CI；不宣称"显著优于"除非 CI 支持；并明确标注 n |
| 自建 20 条任务功效低 | G5 改为"配对 CI 下界 > 0"，并同时给出效应量而非只给 p 值 |
