# Design: 双时态记忆存储

动机见 `proposal.md`，行为契约见 `specs/memory-store/spec.md`。
本文只讲怎么做与为什么。

## Context

C1 的结论直接塑造了这个设计：

- `full-context` 只有 26%，455 条事实里 156 对冲突足以压垮模型 →
  必须能**区分**"哪条有效"，而这要求存储层表达"有效"这个概念
- naive-rag 的 88% 里有 66pp 来自"两条都报" → 存储层必须让"同时存在两条有效值"
  **在物理上不可能**，而不是靠调用方自律

C1 可复用：`memory/config.py`、`memory/tracing`、`memory/eval/metrics.py`。

**本设计经过一次独立审查，并按实测修正了 5 个 P0 缺陷。** 验证脚本的结论见
`docs/store.md`，全部用标准库 `sqlite3` 复现。

## Goals / Non-Goals

**Goals**

- 唯一不变量成为**数据库层面**的约束，任何调用路径都绕不过
- 历史查询（任意时间点、完整时间线）成为一等能力
- 契约测试可零改动套到将来的 Postgres 实现

**Non-Goals**

- 不做冲突判定（C3）
- 不做检索融合与重排（C4）；本变更只**存**向量，不做 ANN
- 不做事务时间（transaction time）查询：v1 的"时间点"只指**现实有效时间**。
  审计链可事后重建事务时间，但本变更不提供 `asof_belief` 接口
- 不做多写者并发调优：SQLite 单写者，`BEGIN IMMEDIATE` 串行化
- 不做 `events` 表归档（C7 再议）

## Decisions

### D1. 不变量靠"部分唯一索引 + NULL 归一"，并有实测依据

```sql
CREATE UNIQUE INDEX ux_active
  ON items(owner, scope, subject, relation, IFNULL(condition, ''))
  WHERE status = 'ACTIVE';
```

**四个键列全部 `NOT NULL` 且 `CHECK(length(trim(x)) > 0)`**，不只是 `condition` 要做 NULL 归一。
实测：不包 `IFNULL` 时，两条 `condition IS NULL` 的 ACTIVE **都能插入**（行数=2）；
包上之后第二条被 `UNIQUE constraint failed: index 'ux'` 拒绝。

**备选**：应用层先 `SELECT` 再 `INSERT`。否决：并发下必有竞态，而评测要反复重跑，
一次双写就会让所有分数不可信。

### D2. 区间重叠由触发器强制，不只靠 `status` 索引

`ux_active` 只约束 ACTIVE 行。审查指出：`resolve_conflict` 让落败者
`CONFLICTED → SUPERSEDED` 时若不写 `valid_to`，它的区间仍是 `[t0, NULL)`，
与胜者重叠，`active_at` 会返回两条。

```sql
CREATE TRIGGER items_no_overlap_ins BEFORE INSERT ON items
WHEN NEW.status != 'RETRACTED'
BEGIN
  SELECT RAISE(ABORT, 'overlapping valid interval')
  WHERE EXISTS (
    SELECT 1 FROM items
    WHERE owner = NEW.owner AND scope = NEW.scope
      AND subject = NEW.subject AND relation = NEW.relation
      AND IFNULL(condition,'') = IFNULL(NEW.condition,'')
      AND status != 'RETRACTED'
      AND NEW.valid_from < COALESCE(valid_to, '9999-12-31T23:59:59+00:00')
      AND COALESCE(NEW.valid_to, '9999-12-31T23:59:59+00:00') > valid_from
  );
END;
```

`UPDATE` 需要对应的触发器。**用 `COALESCE` 而不是裸 `<`**：实测 `5 < NULL` 返回空，
裸比较会让"未结束的区间"永远不参与重叠检测，等于检测失效。

**代价**：任何区间调整都要先清空再写入，写路径稍复杂。接受，因为正确性优先。

### D3. `active_at` 的谓词必须显式处理开区间与状态

审查发现的 P0：`valid_from <= t < valid_to` 在 `valid_to IS NULL` 时返回空，
导致"当前有效的事实"查不到。

```sql
status IN ('ACTIVE','SUPERSEDED')          -- 排除 RETRACTED 与 CONFLICTED
AND valid_from <= :t
AND (:t < valid_to OR valid_to IS NULL)
```

**为什么含 SUPERSEDED**：历史查询必须能返回当时有效、后来被取代的版本，
否则三版本场景里 `active_at(t1)` 会返回空。

**为什么排除 RETRACTED**：撤回的事实从未真正有效，或已被判定为错误，
任何时间点都不该返回。

**为什么排除 CONFLICTED**：冲突未裁决时不提供"当前值"，这正是要传达的信号。

**`t` 在 API 边界强制要求带时区**（`datetime` 必须 `tzinfo is not None`），
统一转 UTC 后格式化为 `...+00:00` 字符串比较。若允许 naive datetime，
在本机 UTC+8 下会静默偏差 8 小时。

### D4. `supersede` 是一个原子操作，不是"先插后关"

审查发现的 P0：若 `insert` 与 `supersede` 分离，新条目要么不能是 ACTIVE（撞唯一索引），
要么关闭旧条目后存在"无有效值"的窗口，崩溃还会留下断链。

```python
def supersede(self, old_id: ItemId, new: MemoryItem, *, reason: str, actor: str) -> MemoryItem:
    # 单事务内：关旧（valid_to/SUPERSEDED/superseded_by）→ 插新 ACTIVE → 写事件
```

`insert` 只用于"该键当前没有 ACTIVE"的情形，否则返回 `ActiveExists` 错误
（引导调用方改用 `supersede`）。

**`old.valid_to` 用 `COALESCE(old.valid_to, new.valid_from)`**：若旧条目已因自然到期
而关闭，不能覆盖它已有的 `valid_to`，否则会伪造出一个更长的有效区间。

**必须显式 `BEGIN IMMEDIATE`**：Python `sqlite3` 默认的隐式事务管理不会为
`SELECT` 加写锁，`MAX(ordinal)+1` 的读与写之间会被插入别的写入。
连接以 `isolation_level=None` 打开，手工控制事务。

### D5. `ordinal` 是全局单调，外加逻辑键内的 `version`

审查指出 D4 的原方案（按逻辑键重置）与 spec 的"连续写入 5 条 → 严格递增"矛盾。

**决定**：
- `ordinal INTEGER PRIMARY KEY`（即 rowid）：全局写入序，天然唯一、单调
- `version INTEGER NOT NULL`：同一 `(owner, scope, subject, relation, condition)` 内的 1..n
- `UNIQUE(owner, scope, subject, relation, IFNULL(condition,''), version)`

时间线按 `version` 读更直观，跨键比较用 `ordinal`。
两者在同一事务内分配，都在 `BEGIN IMMEDIATE` 保护下。

### D6. 幂等只对"当前版本"生效

审查发现的 P0：A → B → A 会丢失。原来只要指纹命中就 NOOP，但命中的可能是
已被取代的旧 A，于是新 A 永远不会成为 ACTIVE。

**修正**：指纹命中时**先看该行的状态**：
- 若命中的行是 `ACTIVE` → 返回其 id，记 NOOP
- 若命中非 ACTIVE → **视为新版本**，走 `supersede` 路径

指纹组成（不含 `status`、不含 `valid_from`、不含 `recorded_at`）：
`sha256(owner|scope|subject|relation|condition|value|authority)`

**`authority` 的归属**：上面用的是**顶层** `authority` 字段，不再藏进 `source`。
审查指出 proposal 写顶层、D8 写 `source.authority`、tasks 写顶层，三处不一致——
统一为顶层 `MemoryItem.authority`。`source` 只承载 `session_id` / `turn_id` / `speaker`。

**为什么不含 `valid_from`**：同一事实带两个互不重叠的有效期（例如"再次入职"）
应各成一条版本，这由 `supersede` 的区间逻辑处理，不该靠指纹区分；
把 `valid_from` 纳入指纹会让"重复确认同一事实"每次都产生新行，幂等失效。

### D7. 状态迁移是完整矩阵，并允许撤回任何非撤回态

审查指出原集合有两个问题：`SUPERSEDED` / `CONFLICTED` 无法撤回（发现历史记录是伪造的
却删不掉），以及同状态重试会抛异常（一次瞬时失败后无法安全重试）。

**完整合法集合**：

| 从 \ 到 | ACTIVE | SUPERSEDED | CONFLICTED | RETRACTED |
|---|---|---|---|---|
| ACTIVE | 幂等空操作 | ✅ | ✅ | ✅ |
| SUPERSEDED | ❌ | 幂等空操作 | ❌ | ✅ |
| CONFLICTED | ✅ | ✅ | 幂等空操作 | ✅ |
| RETRACTED | ❌ | ❌ | ❌ | 幂等空操作 |

同状态调用是**幂等空操作并写一条事件**，不是错误。这样重试安全。
`RETRACTED` 是终止态：撤回是"这条记录作废"的强声明，若能复活，审计就没有意义。

### D8. 审计事件用整数主键，字段足够表达 SUPERSEDE

审查指出原事件只有单个 `item_id`，无法表达"旧 id → 新 id"。

```sql
CREATE TABLE events (
    seq            INTEGER PRIMARY KEY,     -- 追加序，at 可能相同
    item_id        TEXT NOT NULL,
    related_item_id TEXT,                   -- SUPERSEDE 时存旧条目 id
    decision       TEXT NOT NULL CHECK (decision IN
                     ('ADD','NOOP','SUPERSEDE','CONFLICT','BRANCH','RETRACT',
                      'RESOLVE','CORRECTION','MERGE')),
    reason         TEXT NOT NULL,
    actor          TEXT NOT NULL,
    at             TEXT NOT NULL
);
```

`reason` 与 `actor` 是**必填参数**，不是可选。没有原因的事件在审计时没有价值。

### D9. 审计只追加，而且要挡住 `INSERT OR REPLACE`

审查发现的 P1：`INSERT OR REPLACE` 的隐式删除**不会**触发 `BEFORE DELETE`，
除非 `recursive_triggers` 打开。

**实测**：`recursive_triggers=OFF` 时覆盖成功（值被改写）；`ON` 时被拒绝。

因此连接打开时必须执行 `PRAGMA recursive_triggers = ON`，并额外加
`BEFORE INSERT` 触发器拒绝已存在的 `seq`。三个触发器一起才真正只追加。

**纠正路径**：允许追加 `CORRECTION` 事件，用 `related_item_id` 指向被纠正的事件。
错误不能被抹掉，只能被新的记录覆盖语义。

### D10. 错误映射只针对 `ux_active` 唯一冲突

审查指出把一切 `IntegrityError` 都映射成 `InvariantViolation` 会掩盖真 bug。

**实测**：`sqlite_errorcode` 可精确区分：unique=**2067**、notnull=**1299**、check=**275**。

因此只把 `2067` 且消息含 `ux_active` 的映射为 `InvariantViolation`；
`2067` 但来自 `ux_version` 映射为 `OrdinalConflict`；其余原样抛出。

### D11. FTS5 必须自己做中文 bigram，不能指望分词器

审查指出 FTS5 的 `unicode61` 把整段中文当一个 token。

**实测**：`项目使用包管理器` 对 `包管理` / `包管理器` / `项目` 三种查询**全部 0 条命中**。

**方案**：写入时把正文切成"连续中文按 2 字滑窗 + 英文按词"的空格分隔 token，
存进 `items_fts.raw_tokens` 影子列；查询时用同一个函数切词。
纯 Python 实现，约 10 行，无扩展依赖。

**代价**：索引体积约为原文的 2 倍。可接受。

### D12. 契约测试用 fixture 参数化，且断言覆盖 B1–B7 全部

审查指出 7.1 声称"B1–B7 全部断言"但实际只有三条属性。

**方案**：`contract.py` 里每个 `check_*` 函数对应一条验收标准，并有一个
`run_all_contract_checks(store)` 聚合入口。fixture 用 `params=["sqlite"]`。

同时明确 B6（写入顺序无关性）的口径：**只对互不冲突的逻辑键**成立，
且比较"最终有效值集合"，不比较 `ordinal` / `recorded_at` 这类必然不同的字段。
否则该性质要么空洞、要么为假。

### D13. 并发测试必须确定性，不能靠"几乎同时"

审查指出 setTimeout 式的并发测试既不稳定，又会被唯一索引"顺便救活"。

**方案**：用两个显式连接制造确定交错——
A `BEGIN IMMEDIATE` 并插入；B 以 `timeout=0` 尝试写入，必须收到 `SQLITE_BUSY`；
A 提交后 B 重试成功，且 `version` 为 2。把 busy 映射成可重试错误
（`StoreBusy`），而不是伪装成 `InvariantViolation`。

## Risks / Trade-offs

| 风险 | 应对 |
|---|---|
| 重叠触发器让区间调整变复杂 | 写路径统一走 `supersede`，不做原地改区间；加测试锁定"改区间必须先关旧" |
| 全局 `ordinal` 用 rowid，`VACUUM` 后不变（rowid 稳定）但显式插入会破坏 | 不暴露 `ordinal` 写入接口；`ordinal` 由数据库分配，只读 |
| `recursive_triggers` 是连接级 pragma，忘记设置就失效 | 在 `connect()` 里统一设置，并加一条测试断言该 pragma 为 ON |
| bigram 索引让"单字查询"无法命中 | 单字查询降级为 `LIKE` 前缀匹配；在 `docs/store.md` 写明这个限制 |
| 只追加的 `events` 会无限增长 | v1 接受；C7 再议归档 |
| 契约测试能否真的移植到 Postgres | 契约里只断言语义（不变量、迁移、查询结果），不依赖 SQLite 特性；`BEGIN IMMEDIATE` 相关的并发用例标为"实现可自定义串行化方式" |

## Migration Plan

不适用：新增表，无历史数据。

回滚：删除 `src/memory/store/` 与 `tests/store/`，不影响 C1。

## Open Questions

- `scope` 的第四個枚举值：proposal 写四种（`user` / `project` / `task` / `lesson`），
  spec 示例只出现两种。**已定为这四个**，写进模型作为 `Literal`。
- `condition` 保持不透明字符串（去空白、空串转 `None`）。结构化槽位属于 C4 读路径。
