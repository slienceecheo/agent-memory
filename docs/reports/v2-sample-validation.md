# 数据集 v2 样例：`project:ledger`

> 生成时间：2026-10-26（协议已冻结于 tag `dataset-v2-protocol`）
> 目的：在铺开到 15 个 subject 之前，用**一个最难的 subject** 验证 schema 可行。
> 复算：`uv run --no-sync python -m evals.tools.sample_pool_check`

## 交付物 1：memories（12 条）

| memory_id | relation | condition | branch_nature | 有 embedding |
|---|---|---|---|---|
| `ledger-oncall-1` | oncall_owner | 工作日白天 | natural | ❌ 未写入 |
| `ledger-oncall-2` | oncall_owner | 夜间 | natural | ❌ 未写入 |
| `ledger-oncall-3` | oncall_owner | 周末 | natural | ❌ 未写入 |
| `ledger-oncall-4` | oncall_owner | 法定节假日 | natural | ❌ 未写入 |
| `ledger-deploy-1` | deploy_target | 生产环境 | natural | ❌ 未写入 |
| `ledger-deploy-2` | deploy_target | 本地开发 | natural | ❌ 未写入 |
| `ledger-deploy-3` | deploy_target | 赶进度 | natural | ❌ 未写入 |
| `ledger-style-1` | code_style | 重构 | natural | ❌ 未写入 |
| `ledger-style-2` | code_style | 新功能 | natural | ❌ 未写入 |
| `ledger-style-3` | code_style | 小项目 | natural | ❌ 未写入 |
| `ledger-pkg-1` | package_manager | — | natural | ❌ 未写入 |
| `ledger-test-1` | test_command | — | natural | ❌ 未写入 |

> **本节原先把它标成"有 embedding ✅"，这是错的。**
> `evals/tools/sample_pool_check.py` 与 `evals/datasets/retrieval_v2.py` 里
> **没有任何 embedding 调用**（`grep -c "embed" == 0`）。样例阶段只验证了
> schema 与竞争集，向量一路还没接。
>
> 这条正是 L6b 要防的形态：**把"打算做"写成"已做"**。
> L6b 的判定必须是"池构造时 `embedding=` 的写入次数 ≥ 池大小"，不是"代码里有向量逻辑"。
> 当前状态：**L6b 未验证**，必须在铺开前补上。

**结构**：4 条 oncall 分支、3 条 deploy、3 条 code_style、2 条天然单值。

**`branch_nature` 全部是 `natural`（0% forced）**，满足协议 §3.4 的 ≤20% 门禁。
这不是凑出来的：值班人、部署目标、代码风格在真实项目里本来就有多分支，
而包管理器、测试命令只有一个。

### 一个刻意的取舍

`package_manager` 与 `test_command` **不编造条件分支**。
给"Wi-Fi 密码"编出"在家/在公司/在客户现场"是假数据，
会让 `condition_match` 看起来有效，实际只是记住了词表。

## 交付物 2：queries（12 条，标明 cue_type）

| query_id | axis | cue_type | 查询 | query_condition | gold |
|---|---|---|---|---|---|
| `ledger-q1` | A | explicit | 工作日白天值班该找谁？ | 工作日白天 | `ledger-oncall-1` |
| `ledger-q2` | A | explicit | 周末出问题该联系谁？ | 周末 | `ledger-oncall-3` |
| `ledger-q5` | A | explicit | 生产环境的东西部署到哪？ | 生产环境 | `ledger-deploy-1` |
| `ledger-q6` | A | explicit | 本地开发的时候用什么起服务？ | 本地开发 | `ledger-deploy-2` |
| `ledger-q9` | A | explicit | 新功能提交前需要做什么类型检查？ | 新功能 | `ledger-style-2` |
| `ledger-q10` | A | explicit | 小项目用哪套检查就够了？ | 小项目 | `ledger-style-3` |
| **`ledger-q3`** | A | **implicit** | 半夜两点告警响了，该把谁叫起来看？ | 夜间 | `ledger-oncall-2` |
| **`ledger-q4`** | A | **implicit** | 清明节放假期间系统挂了，联系谁？ | 法定节假日 | `ledger-oncall-4` |
| **`ledger-q7`** | A | **implicit** | 这周要赶着交，先扔哪测一下？ | 赶进度 | `ledger-deploy-3` |
| **`ledger-q8`** | A | **implicit** | 这段逻辑我要整块重写，跑哪个检查就够？ | 重构 | `ledger-style-1` |
| `ledger-q11` | C | explicit | 我们这个仓库用什么包管理器？ | — | `ledger-pkg-1` |
| `ledger-q12` | C | explicit | 测试命令是什么？ | — | `ledger-test-1` |

> **本节原先的 query_id 与数据文件不一致**（写的是 `q-oncall-night`、
> `q-style-implicit` 等，实际数据里是 `ledger-q1`…`ledger-q12`）。
> 已按 `data/retrieval-v2/sample/queries.jsonl` 更正。
> 这类错误正是 C4 缺陷 6 的同型：报告与代码对不上，而两份都"看起来对"。

**cue_type 分布：explicit 8 / implicit 4。**

按 **A 轴查询**为分母：`4/10 = 40.0%`，**满足 F13**。
按全部查询为分母：`4/12 = 33.3%`，不满足。

协议 §3.3 已把分母钉死为 **A 轴查询**，理由：C 轴没有"条件是否说破"这个维度
（"这个仓库用什么包管理器"没什么可隐的），把它计入分母会逼着人去编造 C 轴的隐含问法。
两种口径都能自圆其说，所以在冻结前钉死，而不是事后挑好看的那个。

### implicit 为什么是这一版的关键

如果 query 全部写成"开会的时候我几点到"，`condition_match` 直接命中，
测的是中英词表，不是检索。

`"半夜两点告警响了，该把谁叫起来看？"` 里的"夜间"要靠推断，
且**不含任何已登记的条件同义词**（L9）——这才是真实难度。

## 交付物 3：池大小与随机基线

```
池大小（同 subject 全部记忆）: 12
全池随机 SEH@5（期望，逐查询精算）: 0.9028
全池随机 SEH@1（期望，逐查询精算）: 0.2639
```

> **注意：全池口径不适用。** 上表是"每条查询都在 12 条里排"的假设值，
> 但 A 轴的真实竞争集只有 3–4 条（见下）。**全池数字没有任何报告用途**，
> 只作为"指标实现是否自洽"的旁证。

### 按轴拆分——这里暴露了一个必须记下的问题

| 轴 | 查询数 | 平均竞争集 | 随机 SEH@5 | 随机 SEH@1 | 饱和 |
|---|---|---|---|---|---|
| A | 10 | 3.40 | **1.0000** | **0.3000** | 是 |
| C | 2 | 12.00 | 0.4167 | 0.0833 | 否 |

Monte Carlo 复核（每查询 20000 次重排）：

| 轴 | 公式 SEH@1 | 实测 SEH@1 | 公式 SEH@5 | 实测 SEH@5 |
|---|---|---|---|---|
| A | 0.3000 | 0.2994 | 1.0000 | 1.0000 |
| C | 0.0833 | 0.0831 | 0.4167 | 0.4190 |

**A 轴的 SEH@5 恒等于 1.000，因为分支数（3–4）小于 K（5）。**

这不是"可能饱和"，是恒等：`min(K,N)/N = 1` 当 `N ≤ K`。
要在 K=5 上让随机基线低于 0.95，竞争集至少要 **6** 条
（`required_pool_size_for(5, 0.95) == 6`）——A 轴天然永远到不了。

这与 C4 缺陷 3 是同一个形态，只是换到了 A 轴：**SEH@5 在 A 轴上不是满分，是空操作。**

所以：

- **A 轴必须用 `SEH@1` 评估**（随机基线 0.3000，有真实区分空间）
- **C 轴用 `SEH@5`**（随机基线 0.4167）
- 混在一起报 `SEH@5` 会让 A 轴的饱和拉高整体数字，制造假象

已写入协议 §7：**不同轴用不同主指标，不许合并成一个数字**（F14/F15）。

**A 轴的门槛必须单独校准**：随机基线是 0.300 而不是 0.048，
所以"`SEH@1` 低于 0.5"在 A 轴上只意味着"略高于随机"。
报告必须同时给配对 bootstrap 区间，否则 0.5 会被当成强证据。

## 三样之外的一个自检

随机基线用"200 次中是否过半命中"来判定时，A 轴得到 0.000；
改用"期望命中率"后得到 0.289。

**前者是测量方法的错误**——用阈值判定会把 0.289 压成 0。
这与 C4 缺陷 2 同源：指标看起来正常，实际测的不是它声称的东西。

已修正为期望命中率，并加了"实测 vs 理论值偏差 > 0.05 即失败"的断言。

## 结论

`uv run --no-sync python -m evals.tools.check_v2_dataset data/retrieval-v2/sample`
（结果 `results/v2-sample-gates.json`）：**12/16 通过**。

| 检查 | 状态 |
|---|---|
| L1 query ≠ gold 原文 | ✅ 12/12 |
| L2 query 不含 gold 值 | ✅ 12/12 |
| L3 bigram Jaccard ≤ 0.50 | ✅ 最高 0.46 |
| L4 每条记忆有原文 | ✅ 12/12 |
| L5 A 轴竞争集 ≥ 3 | ✅ 10/10 |
| **L6a 三路召回都被调用** | **❌ 只调用 lexical** |
| **L6b 池构造写入向量** | **❌ `embedding=` 出现 0 次** |
| **L7/L8 dedup 收到文本与真实分数** | **❌ 仍是 `(item_id, item_id, 1.0)`** |
| L9 implicit 不含条件同义词 | ✅ 4/4 |
| F2 竞争集 ≥ 2 占比 ≥ 80% | ✅ 100%，最小 3 |
| F5 多分支 relation 3–5 条 | ✅ 3/3 |
| **F6 第三方 subject ≥ 5** | **❌ 0 个** |
| F12 forced 占比 ≤ 20% | ✅ 0% |
| F13 implicit 占 A 轴 ≥ 40% | ✅ 4/10 = 40.0% |
| F15 A 轴饱和时报 SEH@1 | ✅ 已定 SEH@1 为主指标 |
| F16 随机基线 vs 公式 | ✅ 偏差 < 0.01 |

**四项未过，没有一项是 schema 问题：**

| 未过项 | 性质 | 处理 |
|---|---|---|
| L6a / L6b / L7-L8 | **C4 遗留的评测入口缺陷**（缺陷 7、8） | 必须先修评测入口，否则 v2 上向量与去重仍是空转 |
| F6 | **构造性的**：样例只 1 个 subject 且单作者 | 铺开时由第二个人补 5 个，**不许在样例阶段凑** |

这三条评测入口缺陷正是 `locked_defect` 测试锁着的现状
（`uv run --no-sync pytest -m locked_defect -q` → 12 passed）。
它们不会因为换了数据集就自动修好——**这是铺开前必须解决的阻塞**。

## 铺开前需要确认的事

1. **A 轴主指标改用 `SEH@1`** —— 已写入协议 §7.1，随本报告一并拍板
2. **implicit 保持 ≥40%（A 轴分母）** —— 样例已达 40.0%，铺开时不退化
3. **C 轴查询从 2 条增加到至少 5 条** —— 当前 C 轴太少，随机基线 0.4167 的区间会很宽
4. **必须先修 L6a / L6b / L7-L8** —— 否则向量召回与语义去重在 v2 上依然不参与测量，
   这与 C4 缺陷 7/8 完全同型。修它们要开新变更（`src/` 与 `evals/` 都可动，
   但 C4 已归档，不能改其 spec）（C4 缺陷 7 的同类）

前两条影响协议，第三条只影响数据。
