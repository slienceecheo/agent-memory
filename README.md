# 冲突感知的长期记忆层

> 抽取交给 LLM，"哪条记忆现在有效"交给符号化状态跟踪。

LLM Agent 的长期记忆有一个反复出现、且被实测证实的失效：用户改了主意，新旧事实
一起留在库里，检索时谁分高谁赢，模型于是自相矛盾。

这不是精度问题，是**裁决权归属**问题。本项目的做法是把两者分开：

- **LLM 只负责抽取**：把对话变成 `(subject, relation, value, condition, source, valid_from)`
- **确定性状态机负责裁决**：同一 `(subject, relation, condition)` 上谁有效，由规则决定
- **检索负责相关性**：三路召回 + fitness-for-use 重排，并按冲突类型归因失败

## 为什么这么做

有可测量的证据支撑这个分工：

| 系统 | FactConsolidation-SH |
|---|---|
| Mem0 / Contriever | 18.0% |
| BM25 | 48.0% |
| HippoRAG-v2 | 54.0% |
| Zep / Graphiti（双时态知识图谱） | 7.0% |
| **手写确定性 resolver（同 key 取最大序号）** | **80.25%** |

一个不含任何模型、只会"同一事实取最新"的规则，就能超过所有已发表的记忆系统。
说明瓶颈不在抽取质量，而在**没有人做状态跟踪**。

## 设计要点

1. **双时态**：`valid_from` / `valid_to` 表示事实在现实中的有效区间，
   `recorded_at` 表示系统何时知道。两者分离才能处理"补录过去"和"撤销错误录入"。
2. **不静默删除**：被取代的记忆写入 `valid_to` 并标 `SUPERSEDED`，保留审计链。
3. **五类冲突**：重复（NOOP）、补充（MERGE）、取代（SUPERSEDE）、未决矛盾（CONFLICT）、
   条件冲突（BRANCH）。第三类以外的都不许直接覆盖。
4. **读路径按冲突类型归因**：答案错、检索没命中、排序错、还是模型没用好检索结果，
   四种失败分开统计。
5. **embedding 必须缓存**：上游同文本重复调用不保证逐位一致（实测跨变体余弦 0.9976），
   不缓存则实验不可复现。

## 状态

项目刚起步。规格见 `openspec/specs/`，变更记录见 `openspec/changes/`。

## 开发环境

```bash
uv sync
cp .env.example .env   # 填 DASHSCOPE_API_KEY
uv run pytest
```

## 文档

- 需求：`docs/requirements/agent-memory.md`
- 工作流约定：`AGENTS.md`
- **交接说明（新会话必读）**：`docs/HANDOFF.md`
- 实验报告：
  - `docs/reports/c1-baselines.md`
  - `docs/reports/c3-resolver.md`（自写 100% vs 独立 50%）
  - `docs/reports/c4-retrieval.md`（为什么满分不能证明能力）
  - `docs/reports/c4-pool-limitation.md`
