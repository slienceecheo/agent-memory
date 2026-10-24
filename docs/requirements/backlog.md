# 变更清单：第一批（拍板用）

> 2026-10-24。原则：每个变更都能独立验收、单独跑出一组数字。
> 顺序即依赖顺序，一次只做一个。

## C1 · `eval-harness-baseline`

**目标**：建立可复现的评测骨架，并在**没有记忆层**的情况下先跑出三条基线。

**为什么先做**：如果 D1 拿不到数字，后面所有改进都无法证明。这一步同时验证
benchmark adapter 能不能用，避免第 4 天才发现接口对不上。

**范围**

- `uv` 项目骨架、`pytest`、`ruff`、`mypy` 配置
- `Embedder` 协议 + DashScope 实现 + **强制磁盘缓存**（sha256 键）
- `Tracer` 协议 + `JsonlTracer`（默认）
- 三个 baseline：`no-memory`、`full-context`、`naive-rag`
- FactConsolidation adapter（最小样例：单 hop，6K 长度）
- 指标：`substring_exact_match` + 配对 bootstrap CI 工具

**不做**：不做状态机、不做 MemConflict、不做 UI

**验收**：`uv run python -m evals.run --bench factconsolidation --baseline naive-rag`
输出一个 JSON + 一张 markdown 表；且第二次运行 embedding 缓存命中率 100%

---

## C2 · `memory-store`

**目标**：双时态存储 + 唯一不变量，不涉及任何判定逻辑。

**范围**

- `MemoryItem` schema（含 `ordinal`、`owner`、`scope`、`linked_ids`）
- `MemoryStore` 协议 + SQLite 实现（items / fts / vec / events 四表）
- 唯一索引 `(owner, scope, subject, relation, condition) WHERE status='ACTIVE'`
- `timeline` / `active_at` / `retract`
- 契约测试（供将来 Postgres 实现复用）
- 属性测试：写入顺序无关性、幂等、不丢历史

**不做**：不做冲突判定（写入时假定调用方已决定）、不做检索排序

**验收**：`uv run pytest tests/store -q` 全绿；hypothesis 跑 200 例无失败

---

## C3 · `conflict-resolver`

**目标**：实现 6 类判定状态机，这是项目的技术核心。

**范围**

- 归一化层（subject/relation 别名表、中英归一、大小写/复数）
- 规则表（设计文档 3.1 的 7 条，含兜底）
- `authority` 枚举与映射
- 变更标记的规则识别 + LLM 兜底二分类（带缓存）
- `events` 审计写入
- 60 条标注集（dev 40 / test 20）+ macro-F1 报告

**不做**：不做检索、不做答案生成

**验收**

- `uv run pytest tests/resolver -q` 全绿
- `uv run python -m evals.run --bench conflict-set --split test` 输出 6 类混淆矩阵
  与 macro-F1（目标 ≥ 0.85）
- 消融：`--no-llm` 只用规则，报告差多少

---

## C4 · `retrieval-and-rerank`

**目标**：读路径，含三路召回与 fitness-for-use 重排。

**范围**

- FTS5（bigram 切分，中英混排）+ dense + 实体邻接三路召回
- RRF 融合
- 5 个重排特征（含 condition 槽位匹配）
- dev 集网格搜索权重，test 集报结果
- 时间线 API（供 UI 与人工验收）

**不做**：不做 UI 页面、不做 MCP

**验收**：自建 60 条集上 SEH@K 与 SRS 均优于 naive-rag（配对 CI）；权重敏感性曲线出图

---

## C5 · `answer-policy`

**目标**：把"检索到"变成"回答对"，并实现冲突感知的动作策略。

**范围**

- 四种动作：直答 / 带前提回答 / 降置信+追问 / 明确无记录
- 四类失败归因脚本
- 端到端接入 FactConsolidation（resolver-only 与 end-to-end 两条曲线）
- 接入 MemConflict（最小可用：只跑 dynamic 一类，跑通再扩）

**验收**：端到端 FactConsolidation-SH ≥ 0.80；四类失败分布出表

---

## C6 · `cross-task-memory`

**目标**：证明跨 session 有真实收益，这是"harness 长期记忆"的落点。

**范围**

- 20 条依赖链任务集 + 固定 repo 模板 + 容器执行
- 三组对照（empty / naive-rag / ours）
- `lesson` 层记忆的抽取与注入
- 配对 bootstrap 报告

**不做**：不接 harness2（放 C8 可选）

**验收**：三组成功率表 + 配对 CI；CI 下界 > 0 才算达标

---

## C7 · `observability-and-mcp`

**目标**：能被人和 agent 真正用起来。

**范围**

- JSONL 事件 schema 定稿 + 校验测试
- Langfuse 自托管（Docker Compose）+ 导入脚本
- MCP server：`memory_add` / `memory_search` / `memory_timeline`
- 单页时间线 UI（读 `events.jsonl`）

**验收**：Claude Code 或 OpenCode 接入后，能跨 session 记住一条约定；
UI 上能看到该条目的完整历史

---

## C8 · `rsi-replay`（延伸，可选）

**目标**：用自己累积的运行日志做 replay，离线搜召回策略。对应 Dream-RSI 的机制。

**范围**

- 把 `--k` 次 search 的候选与最终选择记录成可重放轨迹
- 策略即代码（候选数 / 融合方式 / 阈值），在历史日志上离线评估
- 选出的策略再上线跑一轮，比较

**验收**：离线搜出的策略在下一轮线上评测中不劣于手写策略（否则如实报告失败）

---

## 暂不排期

- Postgres + pgvector 实现（有 SQLite 就能交付；等 C4 稳定后再说）
- harness2 集成（C6 跑通再看，避免被外部依赖拖住）
- 多语言（中英已覆盖，其余不做）
