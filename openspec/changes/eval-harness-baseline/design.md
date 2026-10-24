# Design: 评测骨架与基线

动机见 `proposal.md`。行为契约见 `specs/evaluation-harness/spec.md` 与
`specs/llm-and-embedding-io/spec.md`。本文只讲怎么做，以及为什么这么选。

## Context

项目目前是空仓库，只有 OpenSpec 流程与需求/设计文档。这个变更要落下第一个可运行的
Python 骨架，并同时解决两个已实测的环境异常：

1. 本地 LLM 网关即使传 `stream=false` 也只返回 SSE 分块。
2. DashScope 的 embedding 对同一文本重复调用不保证逐位一致（实测 3 个变体，
   跨变体余弦 0.9976）。

第二点决定了缓存必须是架构级组件，而不是加在某个函数上的装饰器。

## Goals / Non-Goals

**Goals**

- 三条基线可在同一数据集上跑出可比结果
- 所有外部调用可缓存、可计数、可断言"第二次为 0 次网络请求"
- 指标与置信区间具备单元测试，可信到可以拿来下结论

**Non-Goals**

- 不做记忆层（C2 起）
- 不做并发/性能优化：单进程串行足够，先保证可复现
- 不做重试策略的自适应调优：固定退避即可
- 不引入 pandas：numpy + 原生 dataclass 更轻，也避免隐式类型转换影响可复现性

## Decisions

### D1. 用 `httpx` 而不是官方 SDK 处理 SSE

官方 OpenAI SDK 假定 `stream=false` 就返回普通 JSON，遇到强制分块会得到空响应。
`httpx` 可以直接读字节流，手工按行解析 `data:` 前缀，控制力最强。

**备选**：用 SDK 的 `stream=True` 分支再手工拼装——可行，但 SDK 会做自己的
增量累积与类型校验，出问题时难以定位是网关还是 SDK 的问题。我们的场景里
"看清楚原始字节"比"少写代码"重要。

### D2. 缓存是独立层，不挂在客户端里

`EmbeddingCache` 是独立组件，键为 `sha256(model|dims|text_type|text)`，
值为 float32 二进制 + 元数据 JSON。LLM 响应用同样的思路，但键里多了 prompt 模板哈希。

**为什么必须独立**：如果缓存逻辑长在客户端内部，就无法回答"这次运行发生了多少次
真实网络请求"，而这个数字正是 A3 的验收目标。独立层可以在外面挂计数器与断言。

**备选**：用 `diskcache` 库。否决理由：多一个依赖，且它的键是 pickle，
跨 Python 版本不保证可读；我们自己只需要"键→bytes"，用 `sqlite3` 或裸文件都更可控。
选择：单个 SQLite 文件（`data/cache/cache.db`），自带事务与并发安全，也方便
`--check-cache` 做完整性检查。

### D3. 缓存以内容寻址提交进仓库

`data/cache/` 会提交进 git（体积预计 < 5MB，全是短事实）。这样 `git clone` 后
无需 key 也能跑出与报告完全一致的数字。

**代价**：仓库会变大、缓存需要人工更新。接受，因为"面试官能一键复现"的价值
高于仓库体积。

**备选**：Git LFS。否决：增加使用门槛，而我们的缓存远没到需要 LFS 的量级。

### D4. 三条基线共享同一个 "answer" 函数

三个基线只在"给模型看什么上下文"上不同，生成与匹配逻辑完全共用。这样任何分数差异
都能唯一归因到上下文构造方式。

```python
def answer(question: str, context: list[str]) -> str: ...
```

**备选**：每条基线独立实现，代码更直白但会产生"匹配逻辑不一致"的假差异。否决。

### D5. 指标与 CI 用纯 numpy 实现

配对 bootstrap 只需 20 行：按样本索引重采样、算差值、取分位数。
不引入 `scipy`（只为 `bootstrap` 的话太重），也不引入 `statsmodels`。

**为什么强调"配对"**：两组基线跑的是同一批样本，独立置信区间会高估不确定性，
也可能掩盖"同一批题上 A 稳定优于 B"的事实。评估岗对此很敏感。

### D6. 事件格式先定死再写代码

`events.jsonl` 每行一个 JSON，字段固定：

```json
{"run_id":"...","sample_id":"...","stage":"load|embed|generate|score",
 "started_at":"...","duration_ms":12,"prompt_tokens":0,"completion_tokens":0,
 "reasoning_tokens":0,"network_calls":1,"error":null}
```

**为什么要先定死**：C7 的 UI 与 Langfuse 导入都读这个格式，改一次要动三处。
现在只跑一次 `jsonschema` 校验测试就能锁住。

### D7. FactConsolidation adapter 走"最小可用"路径

先只支持 6K + 单跳。理由：这个子集足以验证"确定性 resolver 能到 80%"这个主张，
而 262K + 多跳的加载与评测成本高一个数量级，留到 C5 再扩。

**风险已记录**：如果 6K 单跳上基线分数与论文差距过大（比如 naive-rag 不是 48% 而是
80%），说明数据版本或解析方式不一致，必须在 C1 内解决，不能带到 C5。

### D8. 配置集中在一个 `Settings` 对象

所有环境变量（key、base_url、模型名、维度、代理、缓存路径）只在一处读取并做校验，
缺失关键项时启动即失败，而不是跑到一半 401。

**备选**：各处 `os.getenv`。否决：这正是"环境陷阱"清单里那类问题的来源。

## Risks / Trade-offs

| 风险 | 应对 |
|---|---|
| 网关行为与官方 OpenAI 不一致，后续换模型时 SSE 解析要改 | 解析层只依赖 `data:` + `[DONE]` 两个约定，不依赖具体字段顺序；单测覆盖 4 种块形态 |
| 缓存提交进仓库后与代码不同步（改了 prompt 但没重建缓存） | 缓存键含 prompt 模板哈希；`--check-cache` 校验"代码声明的键是否都存在" |
| 6K 单跳的基线分数与论文差太多 | A1 里加一条硬性检查：naive-rag 与 full-context 的差必须符合"上下文越长越好"的单调性，否则视为 adapter 有问题 |
| bootstrap 在极小样本上给出退化区间 | 单测覆盖 n=1、全对、全错三种极端；报告里同时给样本数 |
| `reasoning_tokens` 依赖网关返回 | 若字段缺失则记为 `null` 而非 0，避免把"不知道"报成"没浪费" |

## Migration Plan

不适用：这是第一个变更，无历史数据与线上流量。

回滚方式：删除 `src/memory/`、`evals/`、`tests/`、`data/cache/` 即可，
不影响 `openspec/` 与文档。

## Open Questions

- 数据集是否直接随仓库分发？FactConsolidation 的许可证需要确认；若不允许再分发，
  改为首次运行时下载并记录校验和。**这一点不影响任务拆分**，实现时先做"本地文件
  优先，缺失则提示下载"。
