# 存储层：双时态与唯一不变量

本文记录数据模型、不变量与**四个用真库验证过的坑**。所有 SQL 片段都可在
`sqlite3` 中直接执行并复现所述结论。

## 为什么是双时态

一条事实有两种时间，混在一起就无法正确回答"当时是什么"：

| 字段 | 含义 | 用途 |
|---|---|---|
| `valid_from` / `valid_to` | 事实在**现实世界**中有效的区间 | 时间点查询、时间线 |
| `recorded_at` | 系统**得知**它的时刻 | 审计、补录识别 |
| `ordinal` | 全局写入序 | 跨键比较写入先后 |
| `version` | 同一逻辑键内的 1..n 版本号 | 时间线排序 |

`valid_to` 为 `NULL` 表示"仍然有效"。

## 核心不变量

> 同一 `(owner, scope, subject, relation, condition)` 在任一时刻最多只有一条 ACTIVE 条目。

由**部分唯一索引**强制，不是靠代码自觉：

```sql
CREATE UNIQUE INDEX ux_active
    ON items(owner, scope, subject, relation, IFNULL(condition,''))
    WHERE status = 'ACTIVE';
```

## 坑 1：NULL 会绕过唯一索引

SQLite 在唯一索引里把 `NULL` 视为互不相等。所以下面两条都能插入成功：

```sql
CREATE TABLE t (owner TEXT, cond TEXT, status TEXT);
CREATE UNIQUE INDEX ux ON t(owner, cond) WHERE status='ACTIVE';
INSERT INTO t VALUES ('o', NULL, 'ACTIVE');
INSERT INTO t VALUES ('o', NULL, 'ACTIVE');
SELECT COUNT(*) FROM t;   -- 2
```

包上 `IFNULL(cond,'')` 后第二条会被拒绝：

```sql
CREATE UNIQUE INDEX ux2 ON t(owner, IFNULL(cond,'')) WHERE status='ACTIVE';
```

**这条是本设计里最关键的一行。** 无条件事实是最常见的情形，少了它，不变量在最常见的场景下失效。

## 坑 2：`t < NULL` 恒为 NULL

把"仍然有效"的条目过滤掉的最隐蔽方式：

```sql
SELECT 1 WHERE 5 < NULL;                      -- 空
SELECT 1 WHERE 5 < NULL OR NULL IS NULL;      -- 1
```

所以时间点查询必须写成：

```sql
status IN ('ACTIVE','SUPERSEDED')
AND valid_from <= :t
AND (:t < valid_to OR valid_to IS NULL)
```

`status` 的取舍：包含 `SUPERSEDED`（历史查询要能返回当时有效的版本），
排除 `RETRACTED`（撤回的事实任何时刻都不成立）与 `CONFLICTED`（未裁决时"当前值未定"）。

## 坑 3：`INSERT OR REPLACE` 绕过 `BEFORE DELETE` 触发器

审计表要"只追加"，只加 UPDATE/DELETE 两个触发器还不够：

```sql
CREATE TABLE ev (id INTEGER PRIMARY KEY, txt TEXT);
CREATE TRIGGER no_del BEFORE DELETE ON ev
BEGIN SELECT RAISE(ABORT, 'append-only'); END;
INSERT INTO ev VALUES (1, 'original');

PRAGMA recursive_triggers = OFF;
INSERT OR REPLACE INTO ev VALUES (1, 'overwritten');
SELECT txt FROM ev WHERE id=1;   -- overwritten  ← 被改写了
```

打开 pragma 后同一操作会被拒绝：

```sql
PRAGMA recursive_triggers = ON;
INSERT OR REPLACE INTO ev VALUES (1, 'overwritten');  -- append-only 错误
```

因此连接打开时必须执行 `PRAGMA recursive_triggers = ON`，
并额外加 `BEFORE INSERT` 触发器拒绝重复 `seq`。三个触发器缺一不可。

## 坑 4：FTS5 没有中文分词

```sql
CREATE VIRTUAL TABLE fts USING fts5(body);
INSERT INTO fts VALUES ('项目使用包管理器');
SELECT COUNT(*) FROM fts WHERE fts MATCH '包管理';    -- 0
SELECT COUNT(*) FROM fts WHERE fts MATCH '项目';      -- 0
```

`unicode61` 把整段连续中文当成**一个 token**，任何子串查询都落空。

本实现的解法：写入时把正文切成"中文双字滑窗 + 英文词"的空格分隔 token，
查询时用同一个函数切词。单字查询不是 bigram，降级为 `LIKE` 前缀匹配。

**已知限制**：单字查询走 `LIKE`，大数据量下会慢。v1 的数据规模可接受。

## 状态迁移矩阵

| 从 \ 到 | ACTIVE | SUPERSEDED | CONFLICTED | RETRACTED |
|---|---|---|---|---|
| ACTIVE | 幂等 | ✅ | ✅ | ✅ |
| SUPERSEDED | ❌ | 幂等 | ❌ | ✅ |
| CONFLICTED | ✅ | ✅ | 幂等 | ✅ |
| RETRACTED | ❌ | ❌ | ❌ | 幂等 |

同状态调用是**幂等空操作并写事件**，不是错误——这样一次瞬时失败后重试是安全的。

`RETRACTED` 是终止态：撤回是"这条记录作废"的强声明，若能复活，审计就没有意义。

`SUPERSEDED → RETRACTED` 是允许的：发现一条历史记录是伪造的，必须能撤回，
否则脏数据永远留在时间线里。

## 写入为什么必须原子

`supersede` 若拆成"先关闭旧条目，再插入新条目"两步：

- 中间存在**没有有效值**的窗口，并发读者会看到"这个事实不存在"
- 中途崩溃留下 `superseded_by` 指向不存在条目的断链

因此它是一个事务：

```python
with store._write() as conn:          # BEGIN IMMEDIATE
    close_old(conn)                   # valid_to / SUPERSEDED / superseded_by
    insert_new(conn)                  # ACTIVE
    audit(conn)                       # SUPERSEDE 事件（含新旧 id）
```

`BEGIN IMMEDIATE` 不可省：Python `sqlite3` 默认的隐式事务不会为读加写锁，
`MAX(ordinal)+1` 的读与写之间会被插入别的写入。

## 同一时刻改主意会怎样

`supersede` 要求新区间不与旧区间倒挂。若调用方传入的 `valid_from` 不晚于旧起点，
实现会自动推进 1 微秒，而不是报错：

```python
v1 = store.insert(item(value="pnpm", valid_from=T0), ...)
v2 = store.supersede(v1.id, item(value="npm", valid_from=T0), ...)
v2.valid_from > v1.valid_from        # True（差 1 微秒）
```

理由：同一分钟内改两次是正常场景，把时间合理性检查变成调用方的负担没有价值。

## 幂等只对"当前版本"生效

内容指纹 = `sha256(owner|scope|subject|relation|condition|value|authority)`。

刻意**不含** `session_id`（同一事实换个会话说一遍仍是同一事实）、
`recorded_at`（否则每次写入都不同）、`status`、`valid_from`（否则"再次确认"会造新版本）。

但 A → B → A 必须产生第三条版本：指纹命中的是已 `SUPERSEDED` 的旧 A，
若直接返回它，用户改回旧值时记忆会消失。所以幂等**只看当前 ACTIVE 条目**。

## 错误映射

`sqlite3.IntegrityError` 覆盖所有约束类型，笼统映射会掩盖真 bug。
实测 `sqlite_errorcode` 可精确区分：

| 类型 | code |
|---|---|
| UNIQUE | 2067 |
| NOT NULL | 1299 |
| CHECK | 275 |

只把 `2067` 且涉及 `ux_active` 的映射为 `InvariantViolation`；
`CHECK` / `NOT NULL` 抛 `ValueError`；其余原样抛出。

## 验证

```bash
uv run pytest tests/store -q          # 168 passed
uv run pytest tests/store/test_properties.py -q   # hypothesis 每项 200 例
```
