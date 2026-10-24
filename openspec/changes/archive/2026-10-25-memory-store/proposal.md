# Proposal: 双时态记忆存储（memory-store）

## Why

C1 已经证明了两件事：naive 做法会把 88% 的分数误当成能力，而其中 66 个百分点来自
"把冲突答案都报出来"；而 full-context 只有 26%，说明把事实全塞进去反而更差。

要真正裁决冲突，先得有一个能**表达冲突**的存储层。当前仓库只有评测骨架，
没有任何地方能回答这三个问题：

1. 某个 `(主体, 关系)` 现在有效的是什么？（不是"最相似的"，是"有效的"）
2. 上个月有效的是什么？（历史查询，用于审计与时间线）
3. 这两条为什么同时存在？（冲突未裁决 vs 条件不同）

mem0 v3 的 ADD-only 架构答不了第 1 和第 2 个——它把裁决推给检索排序，
而排序只看语义相似度。本变更建立**双时态 + 唯一不变量**的存储，
为 C3 的判定状态机提供不可绕过的地基。

## What Changes

- 新增 `MemoryItem` 数据模型：双时态字段（`valid_from`/`valid_to` 表示现实有效区间，
  `recorded_at` 表示系统何时知道）、`ordinal`（单调写入序）、`owner` / `scope`（命名空间）、
  `status`（ACTIVE / SUPERSEDED / CONFLICTED / RETRACTED）、`linked_ids`、`source`、`authority`
- 新增 `MemoryStore` 协议与 SQLite 实现（`items` / `items_fts` / `vec_items` / `events` 四表）
- 新增**唯一不变量**：`(owner, scope, subject, relation, condition) WHERE status='ACTIVE'`
  只能存在一条，由数据库唯一索引 + 事务保证
- 新增 `timeline()` / `active_at()` / `retract()` 三个查询接口
- 新增审计事件表：每次写入记录 `(item_id, decision, reason, actor, at)`
- 新增契约测试套件（供将来的 Postgres 实现复用同一组断言）
- 新增 hypothesis 属性测试：写入顺序无关性、幂等、不丢历史

**本次不做**

- 不做冲突判定（C3 负责；本变更假定调用方已决定写什么）
- 不做检索排序（C4 负责；本变更只提供 FTS 与向量表的**存储**，不做融合与重排）
- 不做 embedding 调用（向量由调用方传入）
- 不做 MCP / UI（C7）

## Capabilities

### New Capabilities

- `memory-store`：双时态记忆条目的持久化契约——不变量、状态迁移、
  时间点查询、审计事件、跨实现的契约测试。

### Modified Capabilities

（无。现有 `evaluation-harness` 与 `llm-and-embedding-io` 的行为不变。）

## Impact

**新增代码**

| 路径 | 作用 |
|---|---|
| `src/memory/store/models.py` | `MemoryItem`、`Status`、`Scope`、`Authority`、`Source` |
| `src/memory/store/base.py` | `MemoryStore` 协议与异常类型 |
| `src/memory/store/sqlite.py` | SQLite 实现（含唯一索引与迁移） |
| `src/memory/store/contract.py` | 契约测试的公共断言集 |
| `tests/store/` | 单元测试 + 契约测试 + 属性测试 |

**依赖**：`hypothesis`（已在 dev 依赖中）。**不新增**任何数据库依赖——
SQLite 是标准库。向量列用 BLOB 存 float32 裸字节，与 C1 的缓存格式一致；
`sqlite-vec` 扩展在 C4 需要真正检索时再引入。

**对后续变更的影响**：C3 直接依赖本变更的不变量与状态迁移；C4 依赖
`items_fts` 与 `vec_items` 两表的结构；C5 依赖 `timeline()` 做失败归因。

## 验收标准

| 编号 | 标准 | 判定方式 |
|---|---|---|
| B1 | 唯一不变量不可绕过 | 尝试插入第二条同键 ACTIVE → 抛 `InvariantViolation`，且事务回滚，库内无残留 |
| B2 | 双时态可重建历史 | 写入 3 个版本后，`active_at(t1/t2/t3)` 各返回当时正确的那一条 |
| B3 | 不丢历史 | `timeline()` 返回全部版本（含 SUPERSEDED），顺序稳定 |
| B4 | 状态迁移合法 | 非法迁移（如 RETRACTED → ACTIVE）被拒绝并给出原因 |
| B5 | 审计完整 | 每次写入产生一条 `events` 记录，含 decision 与 reason |
| B6 | 写入顺序无关性 | 同一组写入以不同顺序应用（在合法前提下）得到相同的最终状态 |
| B7 | 幂等 | 相同条目重复写入不产生重复行，也不改变 ordinal |
| B8 | 契约可复用 | 契约测试通过参数化 fixture 跑，新增实现只需注册 fixture |
| B9 | 质量门禁 | `pytest`、`ruff`、`mypy`、`openspec validate --strict` 全绿 |
