## 我在 C1 跑基线时发现的问题（必须记录）

日期：2026-10-24

### 现象

用官方口径 `substring_exact_match` 跑 FactConsolidation-6K-SH（100 题）：

| 基线 | 准确率 | reasoning 浪费 |
|---|---|---|
| no-memory | 18% | 93.8% |
| naive-rag (top-5) | **87%** | 89.9% |

论文里 naive-rag/BM25 一类方法是 **48%**。差了一倍。

### 根本原因：模型把两个冲突答案都说了

看实际预测：

```
Q: Which sport is goaltender associated with?
gold: pesäpallo
pred: "ice hockey and pesäpallo"     → 记为正确
```

```
Q: Which country was rugby union created in?
gold: India
pred: "England and India"            → 记为正确
```

数据集里 455 条事实含 **156 对冲突**（同一主语两个值，编号大者为"新"）。
naive-rag 把两条都召回，模型不知道哪条有效，于是**两个都报**。

而 `substring_exact_match` 的规则是"gold 作为 prediction 的子串 → 命中"。
"两个都报"必然包含 gold，所以**必然得分**。

这不是我的实现 bug，是官方指标在这个任务上的结构性问题：
它奖励"把候选全报一遍"这种策略，而对真正的冲突消解没有任何区分力。

### 这为什么对我们的项目重要

1. **不能用 87% 当基线去对比**。否则我们的系统做到 85% 反而"更差"，
   而实际上是把冲突消解对了。
2. 这印证了我调研时读到的那篇批评（`arxiv 2610.09193`）：
   MemoryAgentBench 的 Conflict Resolution 分数不能按聚合值读，要按 item 拆开看。
3. **我们需要补充一个"单一答案"指标**：预测里只能出现一个候选值。
   否则整个 C3（冲突消解）的价值无法被测量。

### 待办（进入 C3 前必须解决）

- [ ] 新增指标 `single_answer_exact_match`：预测中若出现多个冲突候选值，
      记为**错误**（无论是否包含 gold）
- [ ] 报告里同时给两个口径的分数，并说明差异
- [ ] 用"是否识别出冲突"作为单独的中间指标，与最终答案正确率分开
- [ ] 在 C1 报告里如实记录：naive-rag 的 87% 是**指标高估**，不是真实能力

### 附带发现

`no-memory` 的 18% 与论文里 Mem0 的 18.0% 数量级一致，说明
"不给事实时靠常识猜"大致就是两成——这个数字是可信的。
