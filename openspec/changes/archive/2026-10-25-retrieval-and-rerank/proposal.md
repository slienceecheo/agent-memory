# Proposal: 三路召回与 fitness-for-use 重排（retrieval-and-rerank）

## Why

C3 的独立场景集给出了这个项目最重要的一次测量：**自写场景 100%，独立场景 50.0%**。
15 条错误里 9 条是"语义等价或互补，但字面毫不相干"：

- `"靠窗那一排"` vs `"C区第三排左数第二个工位"` → 应为 MERGE
- `"每周日凌晨"` vs `"每周日零点"` → 应为 NOOP

同时 C2 建好的 `items_fts` 与 `vec_items` 从未被读过：`search_text()` 按
`version DESC` 排序而非相关性，且只索引 `subject + relation + value`，
**不含产生这条记忆的原文**。

本变更把读路径建起来。但在设计审查中发现，**此前的评测设计有一个致命缺口**：
三份场景文件都没有 `query`，也没有 `gold_item_id`。没有 gold 就无法计算召回，
没有 query 就无法定义"检索得对不对"。因此本变更必须先补齐评测的因变量，
再谈召回与重排。

## What Changes

### 第一部分：让检索可被测量（前置，不可省）

- 为三份场景文件（dev / test / independent）**补充 `query` 与 `gold_item_id`**
- 新增**候选池构建**：每条场景 = 1 条 gold + N 条干扰项（默认 N=20，键互不相同），
  使排名有真实意义
- 修正 `items_fts`：**索引原文**（`text`），并**按 `bm25()` 排序**
- 新增 `text` 字段到 `MemoryItem`（C2 缺失，导致原文不可追溯）

### 第二部分：召回与重排

- 三路召回：词面（bm25）/ 向量（暴力余弦）/ **条件兄弟邻接**
- RRF 融合（k 可配，默认 60）
- **四个** fitness-for-use 特征：`rrf_norm` / `condition_match` / `source_authority` / `status_penalty`
  （去掉 `temporal_validity` 与 `recency`——在 ACTIVE-only 候选集上恒为常数）
- 语义等价判断接入**去重与合并**，有独立的开关与配对级指标

### 第三部分：评测协议

- **预注册 5 组权重**，不做 1001 组合的网格搜索（在 40 条 dev 上必选噪声）
- 全部 5 组在 dev / test / independent 上都报告，不只报 dev 最优
- 报告最小可检测效应，避免把噪声当结论

**本次不做**

- 不做答案生成（C5）
- 不做 ANN：候选池 21 条，暴力余弦无意义地快
- 不改 C3 写路径判定。**本变更不会让 C3 的 50% 上升**
- 不做跨会话检索调度

## Capabilities

### New Capabilities

- `memory-retrieval`：从存储中找出与查询相关的记忆并排序的契约。含候选池构建、
  三路召回、RRF 融合、四特征重排、条件匹配、语义等价去重、检索指标与归因。

### Modified Capabilities

- `memory-store`：`MemoryItem` 增加 `text`（产生该记忆的原文），
  且 `items_fts` 索引原文并按 `bm25()` 排序。这是对既有存储契约的修改，
  因此需要 delta。

## Impact

| 路径 | 作用 |
|---|---|
| `src/memory/store/models.py` | 增加 `text` 字段（可空，兼容旧数据） |
| `src/memory/store/sqlite.py` | FTS 索引原文；`search_text` 改 `bm25()` |
| `src/memory/retrieval/pool.py` | 候选池构建（gold + 干扰项） |
| `src/memory/retrieval/{lexical,vector,adjacency}.py` | 三路召回 |
| `src/memory/retrieval/fusion.py` | RRF |
| `src/memory/retrieval/rerank.py` | 四特征重排 |
| `src/memory/retrieval/equivalence.py` | 语义等价（去重与合并用） |
| `src/memory/retrieval/{metrics,attribution}.py` | SEH@K / SRS / 三分类归因 |
| `evals/tools/annotate_retrieval.py` | 为场景补 query 与 gold |
| `evals/run_retrieval.py` | 评测入口（预注册权重，多集报告） |

**依赖**：复用 C1 的 embedder 与 LLM 缓存、C2 存储、C3 场景集。不新增第三方依赖。

## 验收标准

| 编号 | 标准 | 判定方式 |
|---|---|---|
| E1 | 每条场景都有 query 与 gold | 三份文件 100% 覆盖；ADD 类 gold 为空且单独计数 |
| E2 | 候选池有真实排名空间 | 每条场景候选数 ≥ 21，gold 排名在 1..21 之间可变 |
| E3 | 词面召回能桥接词汇差异 | 词面召回在独立集上的 SEH@5 显著高于随机（21 选 5 ≈ 0.24） |
| E4 | 三路融合优于最佳单路 | 融合的 SRS 优于任一单路（配对 CI 不含 0） |
| E5 | 重排优于纯融合 | 四特征重排的 SRS 优于纯 RRF（配对 CI 不含 0） |
| E6 | 条件匹配有效 | BRANCH 场景在候选池含 ≥2 条件下，gold 排名优于中性权重 |
| E7 | 语义等价分类有效 | 9 对真实样本上，MERGE 类 ≥5/6、NOOP 类 ≥2/3 分别报告 |
| E8 | 语义等价有消费者 | 开关它会导致去重后的候选数变化，且该变化可测 |
| E9 | 归因不重不漏 | 三类归因互斥，计数之和等于失败总数 |
| E10 | 不过拟合 | 预注册 5 组权重全部报告；给出最小可检测效应 |
| E11 | 可复现 | 同种子两次运行逐位一致 |
| E12 | 质量门禁 | `pytest`、`ruff`、`mypy`、`openspec validate --strict` 全绿 |

## 与上一版设计的差别（审查后修正）

上一版设计有六个会导致"测不出任何东西"的缺陷，全部经独立审查发现并核实：

| 缺陷 | 后果 | 修正 |
|---|---|---|
| 场景无 query / gold | SEH@K 与 SRS 无定义 | 补两个字段（第一部分） |
| 候选池只有 1 条 | 排名恒为 1，SRS 恒为 1.0 | 建 1+N 干扰池 |
| FTS 按 version 排序且不含原文 | 词面召回是噪声，且对 C3 的词汇差异结构性失明 | 索引原文 + `bm25()` |
| 五个特征有四个在 ACTIVE-only 上恒为常数 | 重排与纯 RRF 完全等价，E3 恒为 0 | 删到四个，且每个必须有方差 |
| `relevance` 未定义 | "全关"与"只开 relevance"排序相同 | 改为显式的 `rrf_norm` 基础项 |
| 1001 组权重搜索 | 在 40 条上必选噪声 | 预注册 5 组 |
