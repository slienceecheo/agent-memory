# Proposal: 评测骨架与基线（eval-harness-baseline）

## Why

这个项目的所有主张最终都要靠数字支撑，而目前一条数字都没有。如果先写记忆逻辑再补评测，
就会出现两个典型问题：一是改进无法证明（没有 before/after 的同一把尺子），二是外部
benchmark 的接口到第 4 天才发现对不上，前面的工作全部返工。

因此第一步只做一件与"记忆"无关的事：**把尺子立起来**，并先在完全没有记忆层的情况下
量出三条基线的位置。这三条基线同时也是后续所有变更的对照组。

另一个直接动机来自环境探测：阿里云 embedding 对同一文本重复调用**不保证逐位一致**
（实测出现 3 个向量变体，跨变体余弦 0.9976）。这意味着一份没有缓存的评测脚本，
跑两次会得到两个不同的分数。**缓存不是性能优化，而是可复现性的前提。**

## What Changes

- 建立 Python 项目骨架：`uv` 管理依赖，`pytest` + `hypothesis` 测试，`ruff` + `mypy` 静态检查
- 新增 `Embedder` 协议与 DashScope 实现（`qwen3.7-text-embedding-flash`，1024 维），
  **强制磁盘缓存**，缓存键为 `sha256(model|dims|text_type|text)`
- 新增 `Tracer` 协议与 `JsonlTracer` 默认实现，把每次调用写成可提交、可 CI 校验的 JSONL
- 新增 LLM 客户端：处理本地网关"即使 `stream=false` 也只返回 SSE"的行为，
  收拢 SSE 后返回标准 `chat.completion`；丢弃 `reasoning_content` 并记录其 token 数
- 新增三条基线：`no-memory`、`full-context`、`naive-rag`
- 新增 FactConsolidation adapter（先只支持 single-hop，6K 长度）与官方
  `substring_exact_match` 指标
- 新增配对 bootstrap 置信区间工具（10000 次重采样，95% CI）
- 新增 `--check-cache` 命令，验证缓存完整性与命中率

**本次不做**：不实现记忆存储、不实现冲突判定、不实现检索重排、不接 MemConflict /
LongMemEval / harness2、不做 UI、不做 MCP。

## Capabilities

### New Capabilities

- `evaluation-harness`：评测骨架本身的行为契约——数据加载、基线运行、指标计算、
  置信区间、缓存与可复现性的保证。
- `llm-and-embedding-io`：对外部模型服务的调用契约——SSE 收拢、`reasoning_content`
  处理与浪费统计、embedding 缓存与 `query`/`document` 双模式、失败重试与错误分类。

### Modified Capabilities

（无。这是项目第一个变更，`openspec/specs/` 目前为空。）

## Impact

**新增代码**

| 路径 | 作用 |
|---|---|
| `src/memory/embedding/` | `Embedder` 协议、DashScope 实现、缓存 |
| `src/memory/llm/` | SSE 收拢客户端、`reasoning_content` 统计 |
| `src/memory/tracing/` | `Tracer` 协议、`JsonlTracer` |
| `src/memory/eval/` | 指标、bootstrap CI |
| `evals/` | benchmark adapter、三条基线、运行入口 |
| `tests/` | 单元测试 + hypothesis 属性测试 |
| `data/cache/` | 提交进仓库的 embedding / LLM 缓存（小体积、可重建） |

**依赖**：`httpx`（SSE 与 HTTP）、`pydantic`、`numpy`、`pytest`、`hypothesis`、
`ruff`、`mypy`。**不引入**任何向量数据库、LangChain、LangGraph。

**外部服务**：阿里云 DashScope（唯一联网依赖）、本地 LLM 网关 `127.0.0.1:3211`。

**对后续变更的影响**：C2（存储）、C3（判定）、C4（检索）都复用本变更的
`Embedder` / `Tracer` / 指标 / CI 工具，因此这里的接口形态会被反复引用，
必须在审稿阶段定准。

## 验收标准

| 编号 | 标准 | 判定方式 |
|---|---|---|
| A1 | 三条基线在 FactConsolidation-SH（6K）上各产出一份结果 | `uv run python -m evals.run --bench factconsolidation --baseline {no-memory,full-context,naive-rag}` 各输出 JSON |
| A2 | 结果可复现 | 连续运行两次，指标数值逐位相同；`--check-cache` 退出码 0 |
| A3 | 缓存即时生效 | 第一次运行的 LLM/embedding 网络调用数 > 0，第二次为 0（用 tracer 计数断言） |
| A4 | SSE 处理正确 | 对本地网关发一次 `stream=false` 请求，仍能解析出完整文本与 usage |
| A5 | `reasoning_content` 浪费可量化 | 结果 JSON 含 `reasoning_tokens` 与 `reasoning_waste_ratio` 字段 |
| A6 | 指标正确 | `substring_exact_match` 有单元测试覆盖空串、大小写、标点、中文、部分匹配 |
| A7 | CI 可信 | bootstrap CI 在已知分布（如 100 条全对）上返回 `[1.0, 1.0]`；在 50/100 时区间覆盖 0.5 |
| A8 | 质量门禁 | `uv run pytest -q` 全绿；`uv run ruff check` 与 `uv run mypy src` 无错 |
