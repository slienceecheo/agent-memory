# v2 第二个 subject：`project:billing`

> 目的：用与 `ledger` 不同的 domain 铺第二个 subject，验证"门禁不依赖 ledger 的特殊性"。

## 一、数据形状

| 项 | 值 |
|---|---|
| relation | 3 个（`invoice_currency` / `tax_region` / `settlement_cycle`） |
| 多分支 relation | 3 个 × 3 分支 = **9 条记忆** |
| 单值 relation | **0 个** |
| A 轴查询 | **9 条**（implicit 6 + explicit 3 = 67%） |
| C 轴查询 | **3 条**（每 relation 一条） |
| 合计 | 12 条查询 |

**与交接材料示例的差别**：示例是"2 多分支 + 1 单值"，本 subject 是"3 个全多分支"。
这是 F21b 要求的覆盖：`relation = 3` 这一档必须有 5 个 subject。

**首个 subject 不带无条件默认值**（一次只改一个结构变量）。

## 二、门禁结果：23/26

| 未通过 | 性质 |
|---|---|
| F6（第三方 subject ≥ 5） | 构造性：单作者 |
| F19b（implicit 的 gold 真的被召回） | **装置问题**：消融结果文件按 subject 命名，billing 的还没生成 |
| F21b（relation=2/3 各 ≥5） | 构造性：只有 1 个 subject |

**F19b 是装置问题不是数据问题**：`check_f19b` 读的是 `results/v2-sample-condition-ablation.json`
（ledger 的）。billing 的消融结果在 `results/v2-billing-condition-ablation.json`。
两个 subject 共用一份结果文件会让门禁检查错对象——这是 F19b 的设计缺陷。

## 三、第一个失败信号：A 轴 `SEH@1 = 1.0000`

```
A 轴 SEH@1 = 9/9 = 1.0000
A 轴随机基线 = 0.3333
```

**满分。** 按协议 §1.2 与 C4 的教训，这是"数据太简单"的信号。

### 查过了，不是装置问题

逐条看 gold 与第二名的加权总分差：

| case | gold | 第 2 名 | 差 |
|---|---|---|---|
| `billing-a1` | 0.9194 | 0.6666 | **+0.2527** |
| `billing-a2` | 0.8294 | 0.7448 | +0.0846 |
| `billing-a3` | 0.9150 | 0.7462 | +0.1688 |
| `billing-a4` | 1.0000 | 0.7480 | +0.2520 |
| `billing-a5` | 0.9980 | 0.7500 | +0.2480 |
| `billing-a6` | 0.8353 | 0.7500 | +0.0853 |
| `billing-a7` | 0.9189 | 0.7500 | +0.1689 |
| `billing-a8` | 0.9980 | 0.7500 | +0.2480 |
| `billing-a9` | 0.8710 | 0.7500 | +0.1210 |

**差距全部为正（0.085 ~ 0.253），A 轴 0 条并列。**

唯一的并列在 `billing-c2`（**C 轴**），A 轴一条都没有。
所以 A 轴的 9/9 全部由分数差决定，不是判据在起作用。

> 我第一版探测只打印了"gold 与第二名的差"，没检查并列，于是误报"0 条并列"。
> 加 `tie_at_top1` 字段后才发现 C 轴有 1 条。
> **这说明 `tie_at_top1` 不是补充信息，是它测出了我漏掉的东西。**

### 为什么这么容易

`condition_match` 的贡献太大。同 relation 的兄弟只差 `condition`，
而 `condition` 权重是 0.25，`condition_match` 命中给 1.0、不命中给 0.0：

```
命中：  base×0.25 + 1.00×0.25 + auth×0.25 + status×0.25
不命中：base×0.25 + 0.00×0.25 + auth×0.25 + status×0.25
差  = 0.25
```

**只要 base 分差不到 0.25，condition 就一定赢。** 而 billing 的分支间 base 分差很小
（同一个 subject 的三条 Tax 记忆共享大量词面），所以条件一命中就必然排第 1。

ledger 的 A 轴是 0.9000（9/10），因为它有 `q4` 那条失败——
而 `q4` 失败是因为 gold 的 `authority` 被降级（缺陷 18）。

## 四、第二个数字：条件贡献 +0.7778

```
A 轴 SEH@1  有 condition = 1.0000
            消融后     = 0.2222
            掉幅       = +0.7778
```

比 ledger 的 +0.6000 更强。这与"billing 的 A 轴几乎全靠 condition"一致。

| 指标 | billing | ledger |
|---|---|---|
| 有 condition | 1.0000 | 0.9000 |
| 消融后 | 0.2222 | 0.3000 |
| 掉幅 | **+0.7778** | +0.6000 |
| implicit 有/无 | 1.0000 / 0.0000 | 0.7500 / 0.0000 |
| explicit 有/无 | 1.0000 / 0.6667 | 1.0000 / 0.5000 |

## 五、路径贡献：词面这次**有**贡献

| 配置 | A 轴 `SEH@1` |
|---|---|
| `lexical` | **7/9 = 0.7778** |
| `vector` | 9/9 = 1.0000 |
| `lex+vec` | 9/9 = 1.0000 |
| `vec+adj` | 9/9 = 1.0000 |
| 三路全开 | 9/9 = 1.0000 |

**与 ledger 不同**：ledger 的词面单独是 0.6667、且加上词面后无变化（增量 0）。
billing 的词面单独是 0.7778，说明**词面能独立答对 7/9**。

但加上向量后仍是 1.0000——因为向量本来就是 1.0000，天花板效应。
**所以 billing 上"词面贡献"仍无法被观测到**，不是因为它弱，而是因为
向量已经满分，没有提升空间。

## 六、这个 subject 暴露的三个问题

### 问题 1：A 轴 `SEH@1` 满分，协议没有门禁 —— 已补 F24

协议只规定了 `SEH@5` 饱和时怎么办（§7.1），**没规定 `SEH@1 = 1.0000` 时怎么办**。

而 `SEH@1` 满分比 `SEH@5` 饱和更严重：

| 现象 | 原因 | 性质 |
|---|---|---|
| `SEH@5 = 1.0000` | 池小于 K | **数学恒等**，与系统无关 |
| `SEH@1 = 1.0000` | 数据太简单 | **测不到区分能力**，是实验设计失败 |

已加 **F24**：A 轴 `SEH@1` 不得满分。判定分两段：

- 数据侧（不需跑评测）：随机基线 < 1.0
- 结果侧（结果文件存在时）：实测 `SEH@1` 不得满分

这样合格性检查不依赖系统分数（协议 §1.1）。

实测：

| subject | F24 |
|---|---|
| `project:ledger` | ✅ 随机基线 0.3000 |
| `project:billing` | ❌ 实测 9/9 = 1.0000 |

### 问题 2：F19b 按 subject 共享结果文件 —— 已修

`check_f19b` 与 `check_f20` 曾经硬编码读 `v2-sample-condition-ablation.json`。
铺第二个 subject 之后，ledger 的门禁会去查 billing 的 implicit，反之亦然。

实测表现：billing 的 F19b 报"消融结果里没有这些 implicit 的排名"，
而 billing 自己的消融结果明明已生成在 `v2-billing-condition-ablation.json`。

已改为按 subject 集合匹配：找一份 `v2-*-condition-ablation.json`，
其 `with_condition` 覆盖本数据集的全部查询 ID。详情里写明来源文件名。

### 问题 3：`condition` 权重 0.25 让 A 轴太容易

只要 base 分差 < 0.25，condition 命中就必然赢。
而同一 subject 的同 relation 分支 base 分天然接近（共享 subject/relation 词面）。
**这意味着所有"同 subject 同 relation"的 A 轴都容易满分。**

## 七、待决

按协议 §1.2，改数据**不能参照系统分数**。而现在我已经看到了 1.0000。

所以有两件事要分开：

| 项 | 能否现在改 | 理由 |
|---|---|---|
| 加门禁（`SEH@1 = 1.0000` 报警） | ✅ 可以 | 门禁不是数据 |
| 改 billing 数据让它变难 | ❌ 不行 | 已看到分数，改了就污染 |

建议：**保留 billing 数据原样，把 1.0000 作为证据写进报告**，
然后开 `dataset-v2.1` 重新设计 A 轴难度（或降低 `condition` 权重）。

## 八、复算命令

```powershell
uv run --no-sync python -m evals.tools.precheck_implicit_recall --dataset data/retrieval-v2/billing
uv run --no-sync python -m evals.run_retrieval --dataset data/retrieval-v2/billing `
    --no-dedup --paths lexical,vector,adjacency --pool unrelated `
    --out results/v2-billing-lexical-vector-adjacency.json --overwrite
uv run --no-sync python -m evals.tools.ablate_condition --dataset data/retrieval-v2/billing `
    --out results/v2-billing-condition-ablation.json
```
