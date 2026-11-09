# 冲突感知的长期记忆层

> 抽取交给 LLM，"哪条记忆现在有效"交给符号化状态跟踪。

LLM Agent 的长期记忆有一个反复出现、且被实测证实的失效：用户改了主意，新旧事实
一起留在库里，检索时谁分高谁赢，模型于是自相矛盾。

这不是精度问题，是**裁决权归属**问题。本项目的做法是把两者分开：

- **LLM 只负责抽取**：把对话变成 `(subject, relation, value, condition, source, valid_from)`
- **确定性状态机负责裁决**：同一 `(subject, relation, condition)` 上谁有效，由规则决定
- **检索负责相关性**：三路召回 + fitness-for-use 重排，并按冲突类型归因失败

## 为什么这么做

有可测量的证据支撑这个分工。下表是**公开结果**（出处见 `docs/requirements/agent-memory.md`），
不是本项目的实测：

| 系统 | FactConsolidation-SH |
|---|---|
| Mem0 / Contriever | 18.0% |
| BM25 | 48.0% |
| HippoRAG-v2 | 54.0% |
| Zep / Graphiti（双时态知识图谱） | 7.0% |
| **手写确定性 resolver（同 key 取最大序号）** | **80.25%** |

一个不含任何模型、只会"同一事实取最新"的规则，就能超过所有已发表的记忆系统。
说明瓶颈不在抽取质量，而在**没有人做状态跟踪**。

> **本项目尚未跑出 resolver-only 曲线**（G4 要求另行报告以对齐 80.25%）。
> 因此这里不声称达到该数字，只把它作为立项依据。

## 设计要点

1. **双时态**：`valid_from` / `valid_to` 表示事实在现实中的有效区间，
   `recorded_at` 表示系统何时知道。两者分离才能处理"补录过去"和"撤销错误录入"。
2. **不静默删除**：被取代的记忆写入 `valid_to` 并标 `SUPERSEDED`，保留审计链。
3. **六类判定**：`ADD`，以及五类冲突动作——重复（`NOOP`）、补充（`MERGE`）、
   取代（`SUPERSEDE`）、未决矛盾（`CONFLICT`）、条件冲突（`BRANCH`）。
   第三类以外的都不许直接覆盖。
4. **读路径按冲突类型归因**：答案错、检索没命中、排序错、还是模型没用好检索结果，
   四种失败分开统计。
5. **embedding 必须缓存**：上游同文本重复调用不保证逐位一致（实测跨变体余弦 0.9976），
   不缓存则实验不可复现。

## 实现状态

三层产品代码已完成，评测装置的体量大于产品本身——这是有意的，
因为本项目的核心产出是**可复算的数字**，不是功能清单。

```
产品   src/memory/        3.5k 行   store / resolver / retrieval / embedding / llm
评测   evals/             7.4k 行   数据集适配、指标、消融、27 项数据门禁
测试   tests/            28.5k 行   1790 passed, 4 skipped（5 条 network 默认 deselect）
规格   openspec/specs/    6 份      store / resolver / retrieval / harness / io / apparatus
变更   openspec/         36 个已归档变更，每个含 proposal / design / tasks / spec delta
```

| 层 | 关键实现 |
|---|---|
| 存储 | SQLite + FTS5，中文自建 bigram 分词；部分唯一索引保证每个逻辑键仅一条 `ACTIVE` |
| 判定 | 七条有序规则命中即短路，顺序由测试锁定 |
| 召回 | BM25 词面 / 向量余弦 / 条件兄弟，RRF（k=60）融合 |
| 重排 | 三特征加权，每个特征强制落在 `[0,1]`，权重和必须为 1 |

## 可复现性

- LLM 响应与 embedding 双层缓存，键含 `model|dims|text_type|text`；
  热缓存重跑结果 JSON **逐位一致且网络调用为 0**。
- 15 份结果文件带统一代码指纹，由 `test_unified_fingerprint.py` 强制。
- 数据冻结：tag `dataset-v2-frozen`，协议 tag `dataset-v2-protocol-r2`。
- 测试带 5 类自定义标记：`locked_defect`（锁已知缺陷现状，修好后必须变红并提示同步报告）、
  `evidence_lock`（锁 git 归档里的历史数字）、`integrity_check`（检测工作区被污染）、
  `plan_check`（记录方案评估，不锁实现）、`network`（默认不跑）。

## 三条值得读的结论

**1. 官方指标会把"两个都答"算成正确。** FactConsolidation-6K-SH 上 naive-rag 的
88.0% 里，**66 个百分点**来自同时报出冲突的两个值；只统计单答案的 34 题准确率
只有 **64.7%**。no-memory 18.0%、full-context 26.0%，说明塞更多上下文不等于更好。

**2. 自写场景集的 100% 是过拟合。** 60 条自写冲突集上宏 F1 1.000，第三方独立编写的
30 条 held-out 上只有 **50.0%（宏 F1 0.508）**——50 个百分点的落差就是过拟合的量化值。
15 条错误里 9 条是"语义等价但字面不重叠"，是字符串方法的硬天花板，不是调参能解决的。

**3. 三路召回让 top-1 精度低于词面单路。** 配对口径下 `sample` 0.8333 → 0.5000、
`billing` 0.8889 → 0.1111；但召回从 6/10 提升到 10/10。**两个指标方向相反**，
必须分开报——读成"多路召回有害"会导出错误行动。

## 已知局限

这些不是遗漏，是登记在案的缺口：

| 局限 | 说明 |
|---|---|
| 无置信区间 | spec 要求配对 bootstrap，但评测路径未接（缺陷 22）。v2 全部数字是点估计 |
| 只有 2 个 subject | 不足以支撑跨领域一般性；配对样本量仅 6 / 9 |
| 数据有 5 处已登记缺陷 | 保留而非修复，因为"看到分数后不改数据"优先 |
| 无第三方独立性 | 协议要求的第二作者编写未执行，v3 处理 |
| 噪声阈值未定稿 | 检索装置正在改造，`cosine` 的噪声边界尚未收口 |

## 目录

```
src/memory/          产品代码
docs/reports/        实验报告（每个数字都有可复算来源）
docs/HANDOFF.md      交接说明：当前状态、已知缺陷、踩过的坑（149 KB，新会话必读）
openspec/specs/      系统行为的唯一权威
openspec/changes/    变更记录（已归档 36 个）
evals/               评测装置与 27 项数据门禁
results/             48 份结果文件（15 份带统一指纹）
```

## 开发环境

```bash
uv sync
cp .env.example .env   # 填 DASHSCOPE_API_KEY
uv run pytest
```

要求 Python 3.12。`pyproject.toml` 用 hatchling 构建；本机无外网时可加 `--no-sync`。

## 文档入口

- 需求：`docs/requirements/agent-memory.md`
- 工作流约定：`AGENTS.md`
- **交接说明（新会话必读）**：`docs/HANDOFF.md`
- 实验报告：
  - `docs/reports/c1-baselines.md`（88% 为什么是指标高估）
  - `docs/reports/c3-resolver.md`（自写 100% vs 独立 50%）
  - `docs/reports/c4-retrieval.md`（为什么满分不能证明能力）
  - `docs/reports/v2-what-it-measures.md`（五条结论与它们的边界）

## License

MIT
