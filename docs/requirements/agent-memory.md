# 需求：冲突感知的长期记忆层（Conflict-Aware Memory）

> 版本 v1 · 2026-10-24
> 用途：求职作品集项目。目标是在 Agent 应用实习面试中，用**可复现的数字**说明
> "我理解长期记忆真正难在哪，并且解决了一个具体问题"。

## 1. 要解决的问题

LLM Agent 的长期记忆在这两件事上系统性失效：

1. **写路径**：用户改主意后，新旧事实同时留在库里，检索时谁排前面谁赢，模型于是
   自相矛盾。mem0 v3 明确采用 ADD-only（维护者称 by design），冲突只靠
   `linked_memory_ids` 和检索排序兜底；MemoryAgentBench 的 FactConsolidation 上
   mem0 只有 18.0%（BM25 48.0%，HippoRAG-v2 54.0%），而一个"同一 (subject,
   relation) 取最大序号"的确定性规则就能到 80.25%。
2. **读路径**：答案对不代表检索对。MemConflict 把冲突分成 dynamic（真更新）、
   static（不该覆盖的稳定事实）、conditional（条件不同）三类，发现现有系统的
   "答案正确率"与"检索命中率 / 排序正确率"经常背离；TANGLE 进一步指出，部分冲突
   根本没有唯一答案，正确行为是保留备选、校准置信度、必要时追问。

**核心主张：抽取可以交给 LLM，但"哪条记忆现在有效"必须由符号化的状态跟踪裁决。**

## 2. 目标（v1 必须达成）

| 编号 | 目标 | 可验收标准 |
|---|---|---|
| G1 | 写路径不丢历史、不静默覆盖 | 同一 (subject, relation) 的每次变更都产生一条带 `valid_from/valid_to` 的新记录，旧记录转为 `SUPERSEDED`；任意时刻可重建"某时间点的有效值" |
| G2 | 五类冲突判定准确 | 自建 60 条人工标注冲突集，判定 macro-F1 ≥ 0.85 |
| G3 | 冲突场景检索优于基线 | MemConflict dynamic/static/conditional 三类上，AA 与 SEH@K 均显著优于 naive-RAG 与 last-write-wins（配对 bootstrap，95% CI 不含 0） |
| G4 | 事实整合达到规则上限 | FactConsolidation-SH 准确率 ≥ 0.80（对齐手写确定性 resolver 的水平） |
| G5 | 跨任务召回有真实收益 | 自建 20 条依赖链编码任务：有记忆层 vs 无记忆层，任务成功率提升 ≥ 15pp |
| G6 | 可复现 | 同一 seed 重跑，指标逐位一致；embedding 缓存命中率 ≥ 95% |
| G7 | 可观测 | 每次 add/search/resolve 在 Langfuse 可见，能按 conflict_type 分桶看指标 |

## 3. 非目标（v1 明确不做）

- 不做多模态记忆（图像 / 音频）
- 不做分布式 / 多副本 / 在线扩缩容
- 不做通用知识库 RAG（只做"关于用户与任务的事实"）
- 不做自主反思生成（reflection）的复杂调度，只保留最小可用的 lesson 抽取
- 不追求 SOTA，追求**可解释、可归因、可复现**

## 4. 反目标（做了就等于失败）

- 引入向量数据库服务（Milvus/Qdrant/Neo4j）而收益无法量化
- 用 LLM 直接决定"覆盖还是保留"却拿不出与规则的对照实验
- 只报单点分数，不给置信区间和消融
- 依赖联网才能复现评测（数据集与 embedding 必须可缓存）

## 5. 约束

| 约束 | 内容 |
|---|---|
| 环境 | Windows 11 开发，目标跨平台；Python 3.12，`uv` 管理 |
| LLM | DeepSeek V4.1 Flash，走本地 OpenAI 兼容网关 `127.0.0.1:3211` |
| LLM 网关限制 | **即使 `stream=false` 也只返回 SSE**，客户端必须自行收拢；`tool_calls` 可用；`embeddings` 不可用（401） |
| Embedding | 阿里云百炼 `qwen3.7-text-embedding-flash`，1024 维，**仅北京端点**（`dashscope-intl` 401） |
| Embedding 非确定性 | 同一文本重复调用**不保证逐位一致**（实测出现 3 个变体，跨变体余弦 0.9976）→ 缓存是正确性要求，不是优化 |
| Embedding 批大小 | 实测 21 条可过，官方标称 20；按 10 条一批保守实现 |
| 网络 | 直连可达 DashScope 与本地网关；GitHub/HuggingFace 需代理（`127.0.0.1:7897`），代码中代理为可选配置 |
| 存储 | 默认 SQLite（FTS5 + sqlite-vec），可选 Postgres + pgvector；同一 `MemoryStore` 协议 |
| 预算 | API 不限量，但评测必须缓存，避免重复计费与结果漂移 |

## 6. 尚未拍板的问题

1. 跨任务任务集用"自建 20 条"还是接 harness2？→ 默认自建，harness2 作为延伸
2. 是否要 MCP server 进 v1？→ 默认要（让真实 agent 能用起来，demo 更有说服力）
3. 时间语义：`valid_from` 取"对话发生时间"还是"用户陈述的有效时间"？→ 默认取对话发生时间，并保留 `stated_time` 原文字段
4. 是否支持"撤回"（用户说"忘掉这个"）？→ 默认支持，映射为 `RETRACTED`

## 7. 交付物

1. `agent-memory` Python 包：`add` / `search` / `answer` / `timeline`
2. MCP server（供 Claude Code / OpenCode 接入）
3. 评测报告：主表 + 4 组消融 + 置信区间；可一键重跑
4. 记忆时间线 UI（单页）
5. README + 一篇技术博客
