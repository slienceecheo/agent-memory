# C1 基线报告：FactConsolidation-6K-SH

> 生成日期：2026-10-24
> 数据：`ai-hyz/MemoryAgentBench` → `Conflict_Resolution` → `factconsolidation_sh_6k`
> 规模：455 条事实（含 156 对冲突），100 个问题
> 模型：DeepSeek V4.1 Flash（本地网关，强制 SSE）
> 复现：`uv run python -m evals.run --baseline <name>`

## 主表

| 基线 | 准确率（官方口径） | 多答案率 | 单答案时准确率 | reasoning 浪费 |
|---|---|---|---|---|
| `no-memory` | 18.0% | 3% | 16.5% (16/97) | 93.2% |
| `naive-rag` (top-5) | **88.0%** | **66%** | **64.7%** (22/34) | 89.4% |
| `full-context` | 26.0% | 2% | 25.5% (25/98) | 97.2% |

n = 100，0 个错误样本。

**可复现性**：LLM 响应已按请求哈希缓存（`data/cache/responses.db`），
热缓存下重跑的结果 JSON **逐位一致**且网络调用为 0。
自动验证见 `tests/test_reproducibility.py`。

## 最重要的发现：88% 是指标高估，不是真实能力

`substring_exact_match` 的规则是"标准答案是预测的子串即命中"。
而模型遇到冲突事实时会**把两个候选都报出来**：

```
Q: Which sport is goaltender associated with?
gold: pesäpallo
pred: "ice hockey and pesäpallo"      → 官方口径记为正确
```

拆解 naive-rag 的 88 分：

| 构成 | 题数 | 占比 |
|---|---|---|
| 答对且**只给一个**答案 | 22 | 22% |
| 答对但**同时给出两个冲突值** | 66 | **66%** |
| 答错 | 12 | 12% |

**66 个百分点来自"把候选全说一遍"。** 这类回答在真实场景里不可用——
用户问"我们用什么包管理器"，系统答"pnpm 和 npm"没有任何价值。

只看它给出单一答案的 34 题：准确率 **64.7%**。这才是真实的冲突消解能力。

## 三条基线说明了什么

1. **no-memory = 18%** 与论文里 Mem0 的 18.0% 同量级，说明"不给事实时靠
   常识猜"大约就是两成。这个数字可信，也侧面验证了适配器没搞错。
2. **full-context = 26%**：455 条事实里塞进 156 对冲突，上下文越长越被干扰。
   塞得更多不等于更好——这是"需要检索 + 裁决"而非"需要更大上下文"的直接证据。
3. **naive-rag 的高分是假的**。它召回了正确事实，但同时召回冲突的另一半，
   然后用"两个都报"绕过裁决。

## 对后续变更的直接约束

C3（冲突消解）若要证明自己有价值，**不能拿 88% 当基线**。必须先补一个
把"多答案"判错的指标，否则会出现"我们做对了反而分数更低"的荒谬结论。

四条待办见 `docs/reports/c1-findings.md`。

## 成本

| 指标 | 值 |
|---|---|
| 推理 token 占生成 token 比例 | 89.4% ~ 97.2% |

推理内容占了绝大部分生成开销，而我们的设计是**全部丢弃、只统计**。
若换成按输出 token 计费的真实场景，这部分几乎是纯浪费。

**工程结论**：抽取类任务不该用带长推理的模型，或应显式关闭推理。

## 已知偏差与限制

1. **只有 6K + SH 一格**。32K / 64K / 262K 与 MH 未跑（C5 负责）。
2. **单次采样，无置信区间**。n=100 且只采一次会低估真实方差。
   正式报告会在 C5 做多次采样并给区间。
3. **`substring_exact_match` 对数字有已知误判**（`42` 是 `421` 的子串）。
   本数据集答案以实体名为主，影响有限，但已在
   `tests/test_metrics.py::test_numeric_prefix_is_a_known_false_positive` 中锁定。
4. **多答案判定是启发式的**（依赖 `and` / `or` / 逗号）。
   66% 这个数字有噪声，但方向明确；C3 会用结构化指标替代它。

## 一次被作废的测量

第一次跑出的 naive-rag 是 87.0%，但那份数据的系统提示词里写了
"prefer the one with the larger number, which is newer"——**把核心解法泄露给了基线**。
删除该行后重跑得到现在的 88.0%，并把"提示词不得包含解法关键词"写成了测试
（`test_system_prompt_does_not_leak_the_conflict_rule`）。

## 原始结果

- `results/no-memory-6k-sh.json`
- `results/naive-rag-6k-sh.json`
- `results/full-context-6k-sh.json`

逐样本追踪写 `results/events-*.jsonl`（不入库，可重跑生成）。
