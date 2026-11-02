# Proposal

## Why

v2 的 A 轴测不出东西，而且这不是数据问题。

实测：`billing` 的 A 轴 `SEH@1 = 1.0000`（F24 门禁失败），`ledger` 的 A 轴同样接近饱和。
根因是结构性三角约束：

| # | 约束 | 后果 |
|---|---|---|
| 1 | 每条 A 轴查询都必须指定 `query_condition` | — |
| 2 | 它必须等于 `gold.condition`，否则 gold 在条件上先输 | `condition_match = 1.00` 恒成立 |
| 3 | `base` 差要 > 0.25 才能让 condition 不决定胜负 | 同 key 的 value 相近项进不了池（缺陷 13） |

**只要 `condition` 参与排序，A 轴就必然接近满分。** 所以 v3 的第一步是改装置，不是改数据。

而在动任何数据之前，必须先回答一个决定数据集定义的问题：**去掉 `condition` 之后，A 轴与 C 轴是否还是两个能力维度？**

## What Changes

**新增评测装置规范 `retrieval-apparatus`**，把"用哪个排序特征、轴怎么定义"从隐含约定变成可验收的规格。

具体包含三件事：

1. **排序加权只用三项**（`base` / `authority` / `status`）。`FeatureScores` **保留四个字段**，
   `condition` 仍在结构里但**不进入加权求和**。**BREAKING**：`RerankWeights` 删除 `condition`
   权重字段，因此 v2 的 `weights.condition` 在 v3 结果中不再存在。
2. **轴的重新定义**：因为 `condition` 不再影响排序，"A 轴 vs C 轴"的旧定义失效（实测见下）。
   轴改为由"池内与 gold 同 `relation` 的候选数"派生，且**该判据按 subject 分别计算**。
3. **引用完整性要求**：`per_case.features` 必须存 `base` / `authority` / `status` 三项，
   另在 `per_case.condition_score` 单独存 `condition` 的取值（可为 `null`）。
   这样权重敏感性可离线复算，而条件分布仍可审计。

### 为什么 `FeatureScores` 保留四字段

两种实现都能自洽：

| 方案 | 改动 | 代价 |
|---|---|---|
| 删 `condition` 字段 | `FeatureScores` 三字段，`per_case` 另算一次 `condition_match` | 审计值需要重复计算；`diagnose_c4_leak.py` 等构造点要改 |
| **保留四字段，只改加权** | `rerank()` 不读 `features.condition`；`per_case` 直接序列化 | **diff 更小**；结构不变，旧构造点不用改 |

**选后者**：`FeatureScores` 是"这条候选的全部可观测特征"，而 `RerankWeights` 是
"这次排序用哪些特征"。**两者职责不同——前者描述数据，后者描述策略。**
把特征从数据结构里删掉，等于用策略裁剪事实，而 D1 正需要保留这个事实用于审计。

### 为什么这条变更可以独立验收

它不改检索算法（不碰 `lexical` / `vector` / `fusion` / `dedup`），只改**排序特征集与轴定义**。
验收标准是纯行为断言：给定同一批池，三特征排序下的结果可预测、可复算。

## Capabilities

### New Capabilities

- `retrieval-apparatus`: 评测装置的定义——排序用哪些特征、每个特征由什么决定、轴如何划分、权重敏感性如何离线复算。

### Modified Capabilities

- `memory-retrieval`: `四特征排序` 这条 Requirement 的 `condition` 项被移除，改为三特征；`条件槽位抽取` 的用途从"参与排序"改为"仅做召回过滤"。
- `evaluation-harness`: `检索质量的度量` 增加"`per_case` 必须含逐条特征分"的要求（当前缺口，缺陷 22 的同类）。

## 关键实测：选 c 之后两轴是否仍可分

**结论：分不了，而且在 `billing` 上完全退化。**

池 = 除 gold 外的全部记忆。去掉 `condition` 后，两轴的唯一可能差别是"池中有几个同 `relation` 的对手"。

| subject | 轴 | 同 `relation` 对手数 | 与另一轴可分？ |
|---|---|---|---|
| `ledger` | A（n=10） | 2–3 | ✅ |
| `ledger` | C（n=2） | **0** | ✅ |
| `billing` | A（n=9） | **2** | ❌ |
| `billing` | C（n=3） | **2** | ❌ |

`ledger` 的 C 轴能分开，只因为它的 `package_manager` / `test_command` 在池中各只有 1 条记忆（gold 自己）。
而 `billing` 的每个 relation 都有 3 条（gold + 2 个 condition 分支），所以 A 与 C 结构完全相同。

**这是"两轴在 c 下不可分"的直接证据**，且它决定了 v3 要造几种查询。

## 本次不做什么（范围边界）

| 不做 | 理由 |
|---|---|
| 不改 `condition_match` 的算法 | 它退出排序后只做过滤，"杭州 → 华东"这类语义映射不再是阻塞项 |
| 不补 19 个条件值的槽位体系 | 同上——槽位只影响过滤召回率，不影响排序可分性 |
| 不扩 C 轴到 n ≥ 6 | 那是数据工作，依赖本条先定下轴定义；否则按旧定义造的数据在新装置下无意义 |
| 不实现区间报告 | 缺陷 22，独立变更；本条只要求 `per_case` 存特征分使其**可**复算 |
| 不动 v2 的 15 份冻结结果 | v2 已冻结，本条只影响 v3 的新产物 |

## Impact

**代码**：

- `src/memory/retrieval/rerank.py`：`RerankWeights` 去掉 `condition` 权重；`rerank()` 只用三项加权；
  `FeatureScores` **保持四字段**（结构即事实）
- `src/memory/retrieval/condition.py`：`condition_match` 保留，不再被 `rerank` 调用
- `evals/run_retrieval.py`：`per_case` 增加 `features`（三键）与 `condition_score`
- `tests/retrieval/`：现有依赖四权重的断言需要调整

**数据**：v3 新数据集的 `axis` 改为由池结构派生，且**按 subject 分别判定**（见下）。

### v3 产物的放置（本条变更必须定义）

`results/` 顶层现在是 **v2 档案**：48 个 json、9 类、15 份共享指纹 `47e4785-dirty / 36e9c165`。
**这三条断言本身就是 v2 归档的一部分，不应随 v3 增长而改写。**

所以 v3 产物写到**独立子目录**，按路径分区断言：

| 路径 | 归属 | 断言 |
|---|---|---|
| `results/*.json` | **v2 档案，冻结** | 9 类、加总 48、15 份共享指纹（**不变**） |
| **`results/v3/*.json`** | **v3 评测产物** | 独立分类，数量在 v3 冻结时确定 |
| **`results/features/*.json`** | 逐条特征分（若独立成文件） | 必须带指纹，且与主文件同源 |

**配套改动：三条检查必须从 `glob` 改成 `rglob` + 路径前缀分区**：

| 测试 | 现状 | 改为 |
|---|---|---|
| `test_result_shapes` | `RESULTS.glob("*.json")` | `rglob` 后按 `parent` 分区 |
| `test_every_result_file_is_classified` | 只看顶层 `v2-*` | 分区后分别断言 |
| `test_unified_fingerprint` | 15 份共享指纹 | v2 组 15 份、v3 组各一组 |

**为什么不是"顶层加 `v3-*` 前缀"**：

| 方案 | 后果 |
|---|---|
| 进顶层 | 48 → 49/50/51…，每次新增都要改 `= 48`，**v2 的历史事实被覆盖** |
| **进 `results/v3/`** | **`results/*.json` 永远是 48**，v2 冻结在目录结构上可见 |

**这与 v2 早期那次"11 份结果混三次代码状态"是同一形态**：
不同装置的产物混在同一层，指纹断言必然红——而红的原因不是"指纹错了"，
是"混进了不同版本的产物"。**分区是防止同一个错误第三次发生。**

**兼容性**：**BREAKING** —— v2 的 `results/*.json` 里 `weights.condition` 字段在新代码下不可解析。保留 v2 结果为历史产物，不做迁移。

**验收标准**（可测量）：

| # | 指标 | 阈值 |
|---|---|---|
| 1 | 三特征排序在给定池上的结果 | 与手算逐条一致（`per_case` 的 `rank_after_rerank` 可复算） |
| 2 | `per_case` 字段完整性 | **100% 记录满足两条**：`features` 含 `base`/`authority`/`status` 三个 float；`condition_score` 字段存在（`float` 或 `null`） |
| 3 | 权重敏感性离线复算 | 不改权重时复算结果与原结果逐条相同（0 差异） |
| 4 | 轴判据按 subject 判定 | 对每个 subject 按**派生轴**分组，取两轴 `n_competitors` 的**取值集合**：两轴都有查询时 `set` 相等 -> `merged`、不等 -> `two_axes`；只有一轴有查询 -> `single_axis`；两轴都没有 -> `no_axis` |

**验收 4 的实测（已由 `evaluate` 的 `axis_policy` 产出并测试锁定）**：

| subject | 派生 within 取值 | 派生 cross 取值 | `axis_policy` |
|---|---|---|---|
| `ledger` | `[3,3,3,3,2,2,2,2,2,2]` -> `{2,3}` | `[0,0]` -> `{0}` | **`two_axes`** |
| `billing` | `[2]×9` -> `{2}` | **不存在**（0 条） | **`single_axis`** |

**`billing` 不是 `merged`，是 `single_axis`**——两者报告轴数都是 1，但语义相反：

| policy | 含义 | `billing` 是否成立 |
|---|---|---|
| `merged` | 两轴都存在且结构同构，合并后仍代表两轴 | ❌ 没有 cross 轴可合并 |
| **`single_axis`** | **只有一轴存在** | ✅ |

**若按数据集的 `axis` 标注分组，`billing` 会得到 `merged`**（A={2}、C={2}）——
而那是把 3 条错标成 C 的查询当成了 cross 轴。**两种分组的轴数都是 1，
数字上看不出差别**，这是本条必须显式记下 `single_axis` 的理由。

**关键事实：`billing` 的 3 条 C 标注查询，池结构上都是 `relation_within`（每条都有 2 个同 relation 对手）。**

也就是说，**v2 的 `axis` 标注在 `billing` 上错了 3 条**（3/12）：

| subject | 标注与派生不一致 |
|---|---|
| `ledger` | **0/12** |
| `billing` | **3/12**（`billing-c1` / `c2` / `c3`） |

**这不是"两轴合并"，是"那 3 条 query 从来就不属于 C 轴"**——
它们的 gold relation 在池中各有 2 个对手，测的是"同 relation 多值选择"。

**所以 `billing` 的 policy 是 `single_axis`：该 subject 只有 within 一轴，不存在 cross 轴。**

**而 `ledger` 的 C 轴能对上 `cross`，只因为 `package_manager` / `test_command` 在池中是单值关系。**

### v3 的数据设计约束（本条变更必须写进数据要求）

> **`cross` 轴查询存在 <=> 该 subject 至少有一个"池中只有 gold 一条"的 relation。**

| subject | 单值 relation | 可产生的 cross 查询 |
|---|---|---|
| `ledger` | `package_manager`、`test_command` | ✅ 2 条 |
| `billing` | **无**（三个 relation 都是 3 分支） | ❌ 0 条 |

**而这条约束与 F21a 冲突**，冲突必须写清而不是绕过：

| 门禁 | 内容 | v2 实测 |
|---|---|---|
| **F21a** | 每个 subject 的 relation 数 ∈ **[2, 3]** | `ledger` **5** 个 -> **已红**（正确的失败）；`billing` 3 个 -> 绿 |

| 想要 | 需要 | 撞上 |
|---|---|---|
| 有 cross 轴 | 至少 1 个单值 relation | —— |
| F21a 绿 | relation 数 ≤ 3 | —— |
| **两者同时** | **1 个单值 + 1–2 个多分支**，总数 ≤ 3 | 只有这种形状同时满足 |

**所以实现方式必须是"改造既有 relation"，不是"新增 relation"：**

- ❌ `billing` 加第 4 个单值 relation -> relation 数 3 → 4 -> **F21a 由绿变红**
- ✅ `billing` 把 3 个多分支 relation 中的 1 个改成单值 -> 仍是 3 个 -> F21a 保持绿，且产生 cross 轴

**v3 走"路 2"：允许 subject 无 cross 轴。** 即不为了凑 cross 去改 F21a。
代价是 v3 里两种 subject 形状并存，而这正是 D2 的产出（axis policy 是 subject 级属性）：

| 形状 | relation 构成 | F21a | axis policy | 报告 |
|---|---|---|---|---|
| 双轴 | 1 单值 + 1–2 多分支（总数 ≤ 3） | 绿 | `two_axes` | A / C 两轴分别报 |
| 单轴 | 全部多分支（总数 ≤ 3） | 绿 | `single_axis` | 只报一个轴，并说明另一轴不存在 |
| 不可判定 | 两轴都没有查询 | —— | `no_axis` | 不报轴分数 |

**不改 F21a 的理由**：它刚在 v2 里抓到 `ledger` 的 5 个 relation。
在 v3 放宽上界，会让"F21a 抓到 ledger"这件事变成"F21a 上界本来就不对"——
而 `ledger` 的 5 个 relation 确实是问题（C 轴 2 条查询与 A 轴 10 条查询的池结构差别过大）。

### 本变更**不跑** v3 数据（这是决议，不是遗漏）

这条变更改的是**装置**，不是数据。所以：

| 方案 | 为什么不做 |
|---|---|
| 用 `data/retrieval-v2/` 跑出 v3 产物 | 会产生"装置是 v3、数据是 v2"的结果，被误读成"v3 的第一次测量"。**若确实要跑，命名必须是 `v2-under-v3-apparatus-*`，不能用 `v3-*`** |
| 新造满足 F21a + cross 约束的数据 | 那是**数据变更**，不属于本变更范围。而本变更的验收 3（离线复算 0 差异）已用 v2 数据验过，不需要新数据 |

**所以 `results/v3/` 保持为空。** 但"空目录 -> 断言 skip"不能变成"永久 skip"：

| 断言 | 空目录时 | 靠什么证明它将来会生效 |
|---|---|---|
| `test_v3_has_own_fingerprint` | skip（消息写明原因） | `test_v3_fingerprint_check_actually_fires`（`tmp_path`，三种输入） |
| `test_v3_fingerprint_check_actually_fires` | **始终运行** | —— |

**必须分清 `pool_size` 与 `len(fusion_tags)`**（v2 缺陷 3 的同型错误）：

| 量 | `v2-billing-lexical.json` | `v2-billing-lexical-vector-adjacency.json` |
|---|---|---|
| `pool_size` | **9** | **9** |
| `len(fusion_tags)` | **1** | **9** |
| `rank_after_rerank` | 1 | 2 |
| `tie_at_top1` | 0 | **1** |

`billing-c2` 在 lexical-only 里不并列，原因是**融合列表只有 1 条**
（`path_returns = {"lexical": 1, ...}`），不是"池只有 1 条"。
**融合长度 ≠ 池大小**——用前者代替后者，就是缺陷 3 的形态。

**报告要求**：每个 subject **必须报 `axis policy`**（`two_axes` / `merged` / `single_axis` / `no_axis`），
`merged` 的 subject 只报一个轴的分数。

**这是数据设计约束，不是装置约束**——它必须在造数据之前定，否则重演 v2
"数据在装置定型之前造，装置一变数据价值掉一半"。
