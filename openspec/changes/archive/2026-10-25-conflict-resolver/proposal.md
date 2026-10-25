# Proposal: 冲突判定状态机（conflict-resolver）

## Why

C2 建好了能表达冲突的存储层，但**没有任何东西决定该写什么**：

- 用户说"改用 npm 了" → 应该取代旧值
- 用户重复说"我们用 pnpm" → 不应该产生新版本
- 工单备注说"客户喜欢花生酱" → 不应该覆盖用户自述的花生过敏
- "开会我喜欢早上"与"写代码我喜欢深夜" → 应该并存，不是矛盾

当前这四种情形在代码里无法区分。C2 的 `insert` 只会抛 `ActiveExists`，
把判断责任全部推给了调用方。

同时 C1 留下一个未解的问题：官方 `substring_exact_match` 奖励"把两个冲突答案
都报出来"，导致 naive-rag 的 88% 里 66 个百分点是假的。**在写路径上，这个问题的
正解就是"必须做出唯一裁决"**——不支持"两个都留"作为默认行为。

本变更实现六类判定状态机，把"该写什么"变成可测量、可归因的确定性过程。

## What Changes

- 新增**归一化层**：subject / relation 的别名表、大小写折叠、中英同义词、复数归一
- 新增**六类判定**：`NOOP` / `ADD` / `MERGE` / `SUPERSEDE` / `CONFLICT` / `BRANCH`
- 新增**七条有序规则**（含兜底），规则优先、LLM 仅在"是否陈述新状态"这一处兜底
- 新增**变更标记识别**：正则识别"改成 / 现在 / 不再 / 以前…现在…"，未命中时用 LLM 二分类
- 新增 `ConflictResolver` 编排：判定 → 调用 C2 的对应写入方法 → 返回判定结果
- 新增 **60 条场景集**（dev 40 / test 20），含六类判定的均衡分布
- 新增**标注工具**：生成待标注条目、逐条确认命令、双人一致性（Cohen's κ）计算
- 新增判定指标：六类 macro-F1、逐类混淆矩阵、配对 bootstrap 区间
- 新增消融：`--no-llm` 只用规则，报告 LLM 兜底贡献了多少

**本次不做**

- 不做检索与重排（C4）
- 不做答案生成与多答案指标（C5）
- 不做跨任务 lesson 抽取（C6）
- 不做 MCP / UI（C7）
- **不做自动历史回溯修复**：已被错误取代的条目只提供 `timeline` 查证 + 手动 `retract`

## Capabilities

### New Capabilities

- `conflict-resolution`：把一条候选事实判定为六类之一，并驱动存储层产生正确状态迁移的契约。
  含归一化、规则优先级、变更识别、审计归因。

### Modified Capabilities

- `evaluation-harness`：新增"判定质量"这一指标族（六类 macro-F1、混淆矩阵、逐类配对区间）。
  现有三条基线、指标实现与可复现性要求不变。

## Impact

**新增代码**

| 路径 | 作用 |
|---|---|
| `src/memory/resolver/normalize.py` | subject/relation 归一、别名表、中英同义 |
| `src/memory/resolver/rules.py` | 七条有序规则与判定结果类型 |
| `src/memory/resolver/change_marker.py` | 正则变更识别 + LLM 兜底（带缓存） |
| `src/memory/resolver/resolver.py` | `ConflictResolver` 编排与存储调用映射 |
| `evals/datasets/conflict_set.py` | 场景集加载与 schema 校验 |
| `evals/tools/label.py` | 标注 / 确认 / κ 计算命令行 |
| `evals/metrics/classification.py` | macro-F1、混淆矩阵、逐类区间 |
| `data/conflict-set/*.jsonl` | 60 条场景（含 `label_status`） |

**依赖**：复用 C1 的 LLM 客户端与缓存、C2 的 storage。**不新增**第三方依赖。

**对后续变更的影响**：C5 的答案策略直接复用本变更的判定结果来生成"冲突感知的回答"；
C6 的跨任务记忆依赖 `lesson` 作用域下的判定。

## 验收标准

| 编号 | 标准 | 判定方式 |
|---|---|---|
| D1 | 六类判定均可产生 | 每类至少一条端到端用例，断言 `Decision.kind` |
| D2 | 规则优先级正确 | 构造多规则同时匹配的场景，断言按序短路 |
| D3 | 判定驱动正确的存储迁移 | 六类各自的 `apply` 后，库状态符合 C2 不变量 |
| D4 | 归一化不丢语义 | 别名/大小写/中英/复数四种变体归一到同一键 |
| D5 | 变更识别可归因 | 规则命中与 LLM 兜底分别标记，报告各自的贡献 |
| D6 | 判定质量可测量 | test 集六类 macro-F1 ≥ 0.85（**人工确认标签**后才生效） |
| D7 | 消融可复现 | `--no-llm` 与全量模式的分数差异有区间 |
| D8 | 标注可协作 | 双人标注后给出 Cohen's κ；κ < 0.7 时报告标注不一致的具体条目 |
| D9 | 质量门禁 | `pytest`、`ruff`、`mypy`、`openspec validate --strict` 全绿 |

## 关于标签状态的诚实声明

60 条场景的**期望判定必须由人确认**。本变更会：

1. 生成场景并附上机器提议的标签，字段 `label_status = "proposed"`
2. 提供 `label.py` 逐条确认，确认后置为 `"confirmed"`，记录确认者与时间
3. **D6 只在 `confirmed` 子集上计算**；`proposed` 条目的分数单独列出并标注
   "未确认，仅供参考"

这样在标签确认前，仓库里既有可跑通的实现，也不会把机器标签伪装成人工结论。
