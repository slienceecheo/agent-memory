# Design

## Context

见 `proposal.md` 的 Why。这里只记录实现前必须定下的技术约束。

v2 的现状（实测，不是推测）：

| 项 | 值 |
|---|---|
| `RerankWeights` 字段 | 4 个（`base` / `condition` / `authority` / `status`） |
| 有效特征数（池内实际有方差） | A 轴 3、C 轴 2 |
| `condition` 在 A 轴的值 | 恒为 1.00（`query_condition` 是 `gold.condition` 副本，缺陷 20） |
| `per_case` 是否存特征分 | **否**（只有 `rank_after_rerank` 与 tag） |

**池构造与轴无关**：`select_pool_distractors` 对 A/C 用同一个池（除 gold 外全部记忆），
差别只在 `pool_mode`，而两轴评测都用 `unrelated`。

## Goals / Non-Goals

**Goals**

1. 排序特征从 4 减到 3，且这个"3"由代码强制（不是约定）。
2. 轴的定义能由一个可计算量判定，不依赖数据集的 `axis` 字段自证。
3. `per_case` 同时存排序用的三项特征与审计用的 `condition_score`，使权重敏感性可离线复算。

**Non-Goals**

- 不做区间报告（缺陷 22，独立变更）。
- 不改 `condition_match` 的算法或槽位体系。
- 不迁移 v2 的 15 份结果文件。
- 不决定 C 轴是否扩到 `n ≥ 6`（依赖本变更的轴定义先落地）。

## Decisions

### D1：`condition` 退出加权，但保留在结构里

**做法**：`RerankWeights` 删除 `condition` 权重；`FeatureScores` **保留四个字段**，
`rerank()` 只用三项加权。

**为什么保留字段而不删**：`condition` 的分布是判断"条件能否被查询侧获得"的唯一依据。
v2 的 `implicit` 查询 0/10 含条件词，这个事实只有在有 `condition` 取值时才能持续观测。

**职责分离**：`FeatureScores` 描述"这条候选有哪些可观测特征"，
`RerankWeights` 描述"这次排序用哪些特征打分"。**删字段等于用策略裁剪事实。**

**备选**：

| 方案 | 问题 |
|---|---|
| 保留 `condition` 权重但固定 0 | 权重仍参与"和为 1"的约束，语义混乱 |
| 彻底删除 `FeatureScores.condition` | 失去审计能力；`diagnose_c4_leak.py` 等构造点要改 |

### D2：轴由"同 relation 竞争者数"定义，且**按 subject 判定**

**做法**：`axis` 成为派生量，由池内与 gold 同 `relation` 的候选数决定：

```
n_competitors(query) = |{ m in pool : relation(m) == relation(gold) }|
axis(query) = "relation_within" if n_competitors > 0 else "relation_cross"
```

**判据（subject 级）**：对每个 subject，分别取 A 轴查询与 C 轴查询的
`n_competitors` **取值集合** `set(A)` 与 `set(C)`：

| 情形 | 返回 | 处置 |
|---|---|---|
| 两轴都有查询，`set(A) == set(C)` | `merged` | 该 subject **合并为一轴**，只报一个轴的分数 |
| 两轴都有查询，`set(A) != set(C)` | `two_axes` | 保留两轴，报告中记录差值 |
| **只有一轴有查询** | `single_axis` | 报该轴；并说明另一轴在该 subject 不存在 |
| **两轴都没有查询** | `no_axis` | 不报轴分数，标注"不可判定" |

**必须区分 `single_axis` 与 `merged`**：两者的报告轴数都是 1，**数字上看不出差别**。
而 `merged` 是"两轴同构，合并后仍代表两轴"；`single_axis` 是"只有一轴存在"。
用一个值表示两者，报告会写出"两轴合并"而实际只有一轴——
**这正是"数字相同所以看不出错"的形态。**

**而 `single_axis` 不是边角情形，是必然出现的形状**：proposal 的路 2 允许
subject 没有 cross 轴，而 `billing` 三个 relation 全多分支，永远产生不了 cross 查询。

**为什么是 subject 级而不是数据集级**：v2 的两个 subject 结论相反（见 proposal 的实测表），
而"数据集级合并"会把 `ledger` 的可分性一起丢掉。

**为什么用集合，而不是中位数、不是分布**：

| 判据 | 问题 |
|---|---|
| 中位数 | 漏掉尾部：`A=[1,1,1,1,9]` 与 `C=[1,1,1,1,1]` 中位数都是 1，但结构不同 |
| 有序列表（含长度） | **混入样本量**：`billing` 的 A 有 9 条、C 有 3 条，`[2]×9 != [2]×3` 只是查询条数不同 |
| 标签集合（within/cross） | 太粗：`{1}` 与 `{7}` 都是 `{within}`，但难度完全不同 |
| **取值集合 `set(n)`** | ✅ 忽略样本量，保留结构差异与尾部（空轴另按上表处置） |

**`axis`（报告用）与 `policy`（实现用）是两个不同用途**：
`axis` 保持二元（`relation_within` / `relation_cross`），
`policy` 用集合比较决定是否合并。**不让同一个量承担两个用途。**
`n_competitors` 逐条记入 `per_case`，**深度信息不丢**。

**为什么**：v2 的 `axis` 是数据标注字段，与池的实际结构脱钩。
实测 `billing` 的 3 条 C 标注查询在池结构上都是 `within`（标注不一致 **3/12**），
即该 subject **不存在 cross 轴**。

**这个定义会立刻暴露"标注与结构脱钩"**：`billing` 按**派生**轴分组得 `single_axis`
（within 有 9 条、cross 0 条），而按**标注**分组会得 `merged`（A={2}、C={2}）。
**两者报告轴数都是 1，数字上看不出差别**——所以 policy 必须区分这两个值，
否则报告会写"两轴合并"，而事实是"只有一轴"。

**备选**：

| 方案 | 问题 |
|---|---|
| 保留 `axis` 为标注字段 | 无法发现"两轴同构"，v2 已经证明 |
| 用 `pool_size` 定义轴 | 池大小不是能力维度（proposal 已论证） |
| 用 gold 的 `relation` 在 subject 内的稀有度定义 | 引入主观阈值（"稀有"要到多少） |

### D3：`per_case` 分字段存特征、整池特征与审计值

**做法**：

```python
{
  "features": {           # gold 的三项排序特征；未召回时为 None
    "base": float,
    "authority": float,
    "status": float,
  } | None,
  "features_by_tag": {    # 整池每条候选的三项；不为空
    "<tag>": {"base": float, "authority": float, "status": float},
  },
  "condition_score": float | None,   # 审计用，不参与排序
  "n_competitors": int,              # 轴的定义量
  "axis": str,                       # 逐条派生轴（二元）
}
```

**为什么 `features` 不含 `condition`**：它与 `RerankWeights` 的三个权重一一对应，
可直接 `FeatureScores(**features)` 后调用 `rerank()` 复算，不需要字段过滤。

**为什么必须有 `features_by_tag`**：**名次是相对的**。
只存 gold 自己的分，复算不出"它为什么排第 3"——
验收 1（`rank_after_rerank` 可复算）会退化成"只验分数、不验名次"。

**为什么 gold 未召回时 `features` 是 `None` 而不是 `{}`**：
`{}` 是"存在但没有键"的对象，与"不存在"无法区分。
`None` 与"`features_by_tag` 里没有 gold tag"是**同一事实的两种表达**，
两者必须同时成立——否则就是一份数据两种说法。

**为什么 `condition_score` 用 `None` 而不是 `0.0`**：
`null` 表示"查询侧没有条件"，`0.0` 表示"有条件但完全不匹配"。
两者混同会让"条件覆盖率"统计失真——这正是 v2 的 `0 vs null` 原则。

**键数：25 → 30**（不是原计划的 27）：

| 增量 | 键数 |
|---|---|
| v2 最新批基线 | 25 |
| `+features`（嵌套三键算一个） | 1 |
| `+features_by_tag` | 1 |
| `+condition_score` | 1 |
| `+n_competitors` | 1 |
| `+axis` | 1 |
| **合计** | **30** |

原计划的 27 只算了本条变更的 2 个键，漏掉 2.4a/2.4b 的 2 个与 `features_by_tag`。

**风险**：这会改变 `per_case` 的键集合，
而 v2 的"记录格式 9 类"分析依赖键数。**所以新字段只能进 v3 的产物，v2 不动。**

**陷阱：`Ranked` 的相等性包含 `features`。**

`Ranked` 是 `(item_id, score, features)` 的三元组——**它携带输入**。
所以"比较两条候选的排序结果"不能写成 `rerank([a], w) == rerank([b], w)`：

```python
# 错：features.condition 不同 -> 永远 False，实现改了也不会变绿
assert rerank([a], w) == rerank([b], w)

# 对：只比得分
assert rerank([a], w)[0].score == rerank([b], w)[0].score
```

**这与 D1 的职责分离是同一个问题**：`FeatureScores` 是输入，`Ranked` 是"输出 + 输入"，
而"排序结果"只应该由 `score` 表达。

**测试里凡是断言"排序结果相同/不同"的，都必须比 `score`（或 `item_id` 序列），不比 `Ranked`。**

### D4：离线复算走独立函数，不重跑 `evaluate`

**做法**：新增

```python
def recompute_order(
    candidates, *, weights: RerankWeights, fusion_tags: list[str] | None
) -> list[str]:
    """按 evaluate_case 的两步裁决复算名次；不碰 store、不调模型。"""
```

**复算需要三个输入，不是一个**：

| 输入 | 作用 | 缺了会怎样 |
|---|---|---|
| `features_by_tag` | 每条候选的三项 -> 每条的 score | 无分数可算 |
| `fusion_tags` | 并列时的次序 | 退回 tag 字典序（`d-*` 恒在 `gold-*` 前） |
| 同一组 `weights` | 加权 | 分数不可比 |

**为什么 `fusion_tags` 不是可选的**：`evaluate_case` 实际是两步——

```python
ranked = rerank(candidates, weights)                        # 按 score
ranked = sorted(ranked, key=(-score, fused_position[tag]))  # 并列用融合顺序
```

只复现第一步，在**无并列的数据上永远绿**；而 `rerank` 内部的并列判据是
`item_id`（tag 字典序），会让 `d-<case>-0` 恒排在 `gold-<case>` 之前
（`"d" < "g"`）——**一个固定偏向，看起来却像排序结果。**

**为什么原设计（`recompute_ranks(per_case, weights)` 只读 `features`）不成立**：
`features` 只是 **gold 自己**的三项，而名次是相对于**整池**的。
只读 `features` 复算不出"gold 为什么排第 3"——
验收 1（`rank_after_rerank` 可复算）会退化成"只验分数、不验名次"。
所以 `per_case` 必须同时带 `features_by_tag` 与 `fusion_tags`。

**验证方式分两层**：

| 层 | 测试 | 证明什么 |
|---|---|---|
| 构造 | 人为造并列，两种裁决给出相反名次 | 规则对 |
| 真实 | 用 `features_by_tag` + `fusion_tags` + 权重复算整池 | 数据记全了 |

**缺任何一层都不够**：构造测试证明"规则对"但不证明"数据全"，
真实测试证明"数据全"但不证明"规则在并列时也对"。

**强度约束**：池只有 1 条的 case，任何实现都"复算一致"。
所以测试必须断言"池 > 1 的 case 数量 ≥ 5"，否则是空转。

## Risks / Trade-offs

| 风险 | 缓解 |
|---|---|
| `condition` 退出排序后，A 轴与 C 轴合并，v3 只剩一个轴 | **这正是本变更要暴露的事实**。合并后记录在 proposal 与 spec 里，不靠命名维持两轴假象 |
| 删 `RerankWeights.condition` 会让 v2 结果不可解析 | v2 冻结不动；新代码不承诺读 v2 格式，测试只覆盖 v3 |
| `per_case` 加字段会破坏"记录格式 9 类"分析 | v3 产物单独统计；v2 的 48 个文件保持不变 |
| **本变更同时改了"特征集"与"各组权重"，两个变量混在一起** | **见下方专节：v2/v3 的差异不可只归因于 condition** |
| 三特征下 `authority` 的权重可能压过 `base`（缺陷 19/21） | 缺陷 19 仍存在（`penalty 0.30 > advantage 0.036`），只是算式改成三权重；**本变更不修它**，权重问题由 v3 的消融独立处理 |
| 轴由池结构派生，而池构造本身可能有缺陷（缺陷 13） | 缺陷 13 是独立缺陷，本变更不掩盖它；`n_competitors` 的计算直接读池，缺陷 13 会导致计数偏小，这一点写进 tasks 的验收 |

### v2/v3 的差异**不可只归因于 condition**（必须写明）

**原先这里写的是"本变更不调权重，只减特征"——那句话是错的。** 实测四组权重全改了：

| 组 | v2 四权重 | 去 cond 后重新归一化 | **实际 v3** | 一致？ |
|---|---|---|---|---|
| `uniform` | 0.25 / 0.25 / 0.25 / 0.25 | 0.333 / 0.333 / 0.333 | **0.4 / 0.3 / 0.3** | ❌ |
| `base_heavy` | 0.7 / 0.1 / 0.1 / 0.1 | 0.778 / 0.111 / 0.111 | **0.8 / 0.1 / 0.1** | ❌ |
| `auth_heavy` | 0.2 / 0.1 / 0.6 / 0.1 | 0.222 / 0.667 / 0.111 | **0.2 / 0.7 / 0.1** | ❌ |
| `status_only` | 0.2 / 0.1 / 0.1 / 0.6 | 0.222 / 0.111 / 0.667 | **0.2 / 0.1 / 0.7** | ❌ |

**所以 v2 -> v3 的任何分数差异，同时包含两个来源**：

| 来源 | 能否拆开 |
|---|---|
| (a) `condition` 退出加权 | 否 |
| (b) 四组权重全部重排 | 否 |

**后果**：不存在"v3 因为去掉 condition 掉了多少"这个量。要得到它，
必须构造一个"去 condition 但权重按 renorm 重新归一化"的对照组——
**而那个对照组现在不存在**。

**所以**：

- 报告 MUST NOT 把 v2/v3 的差异表述为"condition 的贡献"
- 若需要那个量，MUST 另做一次只改特征集、不改权重的消融（属于后续变更）
- 缺陷 19 的净差从 v2 的 `0.1025` 变成 v3 的 `0.2640`，
  **其中一部分来自权重重排，不全是三特征的结果**

## Migration Plan

**BREAKING**：新旧产物不兼容。

| 步骤 | 内容 |
|---|---|
| 1 | 代码改 `rerank` / `FeatureScores` / `RerankWeights`，旧测试同步调整 |
| 2 | 跑 v3 第一批数据，产生带 `features` 的 `per_case` |
| 3 | 用 `recompute_order` 验证 0 差异（含并列 case 与池 > 1 的强度约束） |
| 4 | v2 的 15 份结果保持原样，不迁移、不重跑 |

**回滚**：本变更只动 `src/memory/retrieval/rerank.py` 与 `evals/`，
回滚即 `git revert`；v2 数据与结果不受影响。

## Open Questions

**无。** 轴合并与否由 D2 的实测结果决定，而那个结果在实现时立刻可算，
不需要额外决策——它是本变更的产出，不是前置未知。
