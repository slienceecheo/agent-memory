# Tasks

> TDD 顺序：每组先写会失败的测试，再写实现。
> 设计决策见 `design.md`；行为契约见 `specs/memory-store/spec.md`。
> 本版按一次独立审查的结果重写——原版有多条测试会静默通过。

## 1. 数据模型

- [x] 1.1 先写测试：`MemoryItem` 拒绝无时区时间、拒绝 `valid_to <= valid_from`、
      把 `condition` 空串归为 `None`、`scope` 只接受四个值、
      `authority` 只接受四个枚举级别，
      验证：`uv run pytest tests/store/test_models.py -q` 全绿
- [x] 1.2 实现 `src/memory/store/models.py`（`MemoryItem` / `Status` / `Scope` /
      `Authority` / `Source` / `ItemId`），
      验证：`uv run pytest tests/store/test_models.py -q` 全绿且 `mypy` 无错
- [x] 1.3 先写测试：指纹对 `(owner,scope,subject,relation,condition,value,authority)`
      敏感；对 `session_id`、`turn_id`、`recorded_at`、`status`、`valid_from` 不敏感，
      验证：`uv run pytest tests/store/test_fingerprint.py -q` 全绿
- [x] 1.4 实现 `fingerprint()`（`authority` 取**顶层字段**，不取 `source.authority`），
      验证：`uv run pytest tests/store/test_fingerprint.py -q` 全绿

## 2. 存储协议与异常

- [x] 2.1 先写测试：协议含 `insert` / `supersede` / `retract` / `resolve_conflict` /
      `active_at` / `timeline` / `get` / `count`，**所有写入方法都要求 `reason` 与 `actor`**，
      验证：`uv run pytest tests/store/test_protocol.py -q` 全绿
- [x] 2.2 实现 `src/memory/store/base.py`，异常含
      `InvariantViolation` / `InvalidTransition` / `DimensionMismatch` / `NotFound` /
      `ActiveExists` / `StoreBusy`，
      验证：`uv run pytest tests/store/test_protocol.py -q` 全绿

## 3. 建表、约束与不变量

- [x] 3.1 先写测试：建库后四张表与 `meta` 存在；直接执行 SQL 插入两条同键 ACTIVE 失败；
      对每条键列（`owner`/`scope`/`subject`/`relation`）分别尝试插入空值，全部失败，
      验证：`uv run pytest tests/store/test_schema.py -q` 全绿
- [x] 3.2 实现建表语句：键列 `NOT NULL` + 非空 CHECK，
      唯一索引用 `IFNULL(condition,'')`，
      验证：`uv run pytest tests/store/test_schema.py -q` 全绿
- [x] 3.3 先写测试：同键重叠区间被拒绝（插入与更新两个方向都要测）、
      `valid_to` 为空的区间被视为延伸到无穷远而参与重叠判定、
      RETRACTED 条目被排除在重叠检测外，
      验证：`uv run pytest tests/store/test_overlap.py -q` 全绿
- [x] 3.4 实现插入与更新两个重叠触发器，用 `COALESCE(valid_to, 哨兵)` 比较，
      验证：`uv run pytest tests/store/test_overlap.py -q` 全绿
- [x] 3.5 先写测试：`events` 的 UPDATE 被拒、DELETE 被拒、
      **`INSERT OR REPLACE` 覆盖已有 seq 也被拒**、
      且连接打开后 `PRAGMA recursive_triggers` 为 ON，
      验证：`uv run pytest tests/store/test_audit_immutable.py -q` 全绿
- [x] 3.6 实现三个触发器 + `connect()` 中统一设置 pragma，
      验证：`uv run pytest tests/store/test_audit_immutable.py -q` 全绿
- [x] 3.7 先写测试：`meta` 声明 `embedding_dims`，写入长度不符的向量抛
      `DimensionMismatch`（不是 `InvariantViolation`），
      验证：`uv run pytest tests/store/test_dimensions.py -q` 全绿
- [x] 3.8 实现维度校验，
      验证：`uv run pytest tests/store/test_dimensions.py -q` 全绿

## 4. 写入路径

- [x] 4.1 先写测试：`insert` 分配全局单调 `ordinal` 与键内从 1 开始的 `version`、
      写 ADD 事件（reason/actor 落库）、返回条目 id，
      验证：`uv run pytest tests/store/test_insert.py -q` 全绿
- [x] 4.2 实现 `insert`（`isolation_level=None` + 显式 `BEGIN IMMEDIATE`），
      验证：`uv run pytest tests/store/test_insert.py -q` 全绿
- [x] 4.3 先写测试：同键已有 ACTIVE 时 `insert` 抛 `ActiveExists` 且提示改用 `supersede`；
      库内无新增条目、无新增事件，
      验证：`uv run pytest tests/store/test_invariant.py -q` 全绿
- [x] 4.4 实现 `ActiveExists` 前置检查（在事务内做，避免竞态），
      验证：`uv run pytest tests/store/test_invariant.py -q` 全绿
- [x] 4.5 先写测试：内容指纹命中且命中的行是 ACTIVE → 返回其 id、条数与 version 不变、写 NOOP 事件，
      验证：`uv run pytest tests/store/test_idempotent.py -q` 全绿
- [x] 4.6 实现"仅对当前版本生效"的幂等，
      验证：`uv run pytest tests/store/test_idempotent.py -q` 全绿
- [x] 4.7 先写测试：A → B → A 产生第三条版本且为 ACTIVE（不被旧指纹吞掉），
      验证：`uv run pytest tests/store/test_aba.py -q` 全绿
- [x] 4.8 实现"指纹命中但行非 ACTIVE 时走新版本"的路径，
      验证：`uv run pytest tests/store/test_aba.py -q` 全绿
- [x] 4.9 先写测试：唯一冲突（`ux_active`）、非空约束、CHECK 约束三类错误
      分别映射为 `InvariantViolation`、`ValueError`、`ValueError`，互不混淆，
      验证：`uv run pytest tests/store/test_error_mapping.py -q` 全绿
- [x] 4.10 按 `sqlite_errorcode` 精确映射（2067+索引名 / 1299 / 275），
      验证：`uv run pytest tests/store/test_error_mapping.py -q` 全绿

## 5. 状态迁移

- [x] 5.1 先写测试：完整 4×4 迁移矩阵的 **16 个格子逐个断言**
      （合法者成功、非法者抛 `InvalidTransition`、同状态为幂等空操作并写事件），
      验证：`uv run pytest tests/store/test_transitions.py -q` 全绿
- [x] 5.2 实现迁移表校验与三个入口 `supersede` / `retract` / `resolve_conflict`，
      验证：`uv run pytest tests/store/test_transitions.py -q` 全绿
- [x] 5.3 先写测试：`supersede` 正确设置 `valid_to` / SUPERSEDED / `superseded_by` /
      SUPERSEDE 事件（同时能查到新旧 id）、
      新条目 `valid_from` 与旧条目 `valid_to` **相邻**（无缝隙、无重叠）、
      **旧条目原本已有 `valid_to` 时不被覆盖**、
      中途失败整体回滚（用注入异常模拟），
      验证：`uv run pytest tests/store/test_supersede.py -q` 全绿
- [x] 5.4 实现原子 `supersede`（单事务：关旧 → 插新 → 写事件），
      验证：`uv run pytest tests/store/test_supersede.py -q` 全绿
- [x] 5.5 先写测试：`retract` 只改状态与写 RETRACT 事件（含 reason），
      不改 `recorded_at`、不改 `valid_to`、可作用于 ACTIVE/SUPERSEDED/CONFLICTED 三种状态，
      验证：`uv run pytest tests/store/test_retract.py -q` 全绿
- [x] 5.6 实现 `retract`（含 RETRACTED 终止态保护），
      验证：`uv run pytest tests/store/test_retract.py -q` 全绿
- [x] 5.7 先写测试：`resolve_conflict` 让胜者 ACTIVE、败者 SUPERSEDED 且
      **败者的 `valid_to` 被写入**（防止区间重叠导致 active_at 返回两条）、
      写 RESOLVE 事件，
      验证：`uv run pytest tests/store/test_resolve.py -q` 全绿
- [x] 5.8 实现 `resolve_conflict`，
      验证：`uv run pytest tests/store/test_resolve.py -q` 全绿

## 6. 查询路径

- [x] 6.1 先写测试：三版本历史下 `active_at(t1/t2/now)` 各返回正确版本、
      早于首条记录返回空、
      **`valid_to` 为空的当前版本必须被返回**（防 `t < NULL` 陷阱）、
      RETRACTED 条目不返回、只有 CONFLICTED 时返回空、
      未指定 condition 时只返回无条件条目（fixture 里同时放无条件与条件各一条），
      验证：`uv run pytest tests/store/test_active_at.py -q` 全绿
- [x] 6.2 实现 `active_at`（`status IN ('ACTIVE','SUPERSEDED')`
      + `valid_from <= t` + `(t < valid_to OR valid_to IS NULL)`），
      验证：`uv run pytest tests/store/test_active_at.py -q` 全绿
- [x] 6.3 先写测试：`timeline` 返回全部版本按 `version` 升序、
      含条件分支、空键返回空列表、含 A→B→A 的三条，
      验证：`uv run pytest tests/store/test_timeline.py -q` 全绿
- [x] 6.4 实现 `timeline`，
      验证：`uv run pytest tests/store/test_timeline.py -q` 全绿
- [x] 6.5 先写测试：**中文双字词查询能命中**（如用 `包管理` 查 `项目使用包管理器`）、
      英文词查询命中、被取代与撤回的条目不出现在当前检索结果但仍在时间线、
      单字查询按文档的降级策略行为一致，
      验证：`uv run pytest tests/store/test_fts.py -q` 全绿
- [x] 6.6 实现 `items_fts` + Python bigram 切词（写入与查询共用同一函数），
      验证：`uv run pytest tests/store/test_fts.py -q` 全绿

## 7. 契约测试与属性测试

- [x] 7.1 编写 `src/memory/store/contract.py`：为 B1–B7 每条验收标准写一个
      `check_*` 断言函数，并提供一个聚合入口，
      验证：`uv run pytest tests/store/test_contract.py -q` 全绿，
      且 `grep -c "^def check_"` 数量与验收标准条数一致
- [x] 7.2 用 `pytest.fixture(params=["sqlite"])` 注册实现，
      验证：`uv run pytest tests/store/test_contract.py -q` 显示参数化通过
- [x] 7.3 先写属性测试：任意合法写入序列下"同键 ACTIVE 条数 ≤ 1"、
      "条数只增不减"、"全局 ordinal 严格递增"、"键内 version 连续无跳号"，
      验证：`uv run pytest tests/store/test_properties.py -q`（hypothesis 200 例）全绿
- [x] 7.4 先写属性测试：`supersede` 后旧条目 `valid_to` 必不为空、
      新条目 `valid_from` 与旧条目 `valid_to` 相等、
      `active_at(该边界点)` 返回新条目、
      **任意随机时间点 `active_at` 至多一条**，
      验证：`uv run pytest tests/store/test_properties.py -q` 全绿
- [x] 7.5 先写测试：确定性并发交错——连接 A 开 `BEGIN IMMEDIATE` 并插入，
      连接 B 以 `timeout=0` 尝试写入必须收到 `StoreBusy`；
      A 提交后 B 重试成功且 version 为 2，
      验证：`uv run pytest tests/store/test_concurrency.py -q` 全绿

## 8. 文档与交付

- [x] 8.1 编写 `docs/store.md`：数据模型、不变量、状态迁移矩阵、
      四个实测坑（NULL 绕过唯一索引 / `t < NULL` / `INSERT OR REPLACE` 绕过触发器 /
      FTS5 无中文分词）、单字查询的限制，
      验证：文档中每条 SQL 片段都可在 `sqlite3` 中执行并复现所述结论
- [x] 8.2 全量门禁：`uv run pytest -q`、`uv run ruff check`、`uv run mypy src`、
      `openspec validate memory-store --strict`，
      验证：四条命令均以 0 退出并贴出原始输出

## Workflow follow-up

- 审稿通过后归档该变更，确认 `openspec list` 无活动变更。
