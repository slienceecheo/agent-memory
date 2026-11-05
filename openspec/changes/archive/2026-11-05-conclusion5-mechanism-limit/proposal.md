## Why

**结论 5 说明了现象，但没有说明原因。** 两个完全不同的机制都能产生
`0.8333 → 0.5000` 这个下降：

| 机制 | 含义 | 处置 |
|---|---|---|
| **融合规则**（RRF 稀释） | 三路分数混合方式不当 | 改融合 |
| **vector 召回质量** | cosine 排序与 gold 不一致 | 改召回或不用 vector 排序 |

**区分它们需要单独测 cosine 排序质量，而现有 15 份冻结产物都没有记录 cosine 分。**

若不把这句限定写进报告，下一个人会以为结论 5 已经解释了原因，
从而直接去改融合——而真正的原因可能是 cosine 排序。

## 同时纠正一个会被误读的数

`path_returns.vector = 462` 是**三份产物上所有 case 的累加**，不是单条 case 的返回数。

实测（可复算）：

| 产物 | 顶层 `path_returns.vector` | 单条 case | `pool_size` |
|---|---|---|---|
| `a3-lexical-vector-adjacency.json` | 462 | 14 | 14 |
| `v2-billing-lexical-vector-adjacency.json` | 108 | 9 | 9 |

**单条 case 的 `path_returns.vector` 恒等于 `pool_size`**——
vector 路返回了**整个池**，它的排序就是 cosine 全序。

**这解释了两件事**：

| 现象 | 解释 |
|---|---|
| vector-only 召回 10/10、12/12 | 它返回全部候选 |
| vector-only 的 `SEH@1` 只有 0.4000 / 0.1667 | cosine 排序只在少数 case 上与 gold 一致 |

**这个数被误读的代价**：会以为"vector 返回了海量噪声"，
从而去"压缩 vector 召回"。而实际它返回的就是全部候选，没有可压缩的东西。

**另外纠正**：`v2-sample-lexical-vector-adjacency.json` **不存在**
（`sample` 只有冻结的 `a3-*.json`，池 14）。§6.1 的 `sample` 数字来自现场重跑。

## What Changes

**1. `v2-what-it-measures.md` §6 新增两节**

- §6.6 机制未区分（两个原因都能产生同样的数字）
- §6.7 关于「462 条」这个数（累加值 / vector 返回整个池）

原 §6.6 复算顺延为 §6.8。

**2. `test_fusion_dilution.py` 新增 3 条断言**

| 断言 | 判据 |
|---|---|
| `test_report_states_mechanism_is_undifferentiated` | §6 有"机制未区分"且并列两个机制 |
| `test_report_does_not_claim_462_is_per_case` | §6 有"累加"与"返回了整个池" |
| `test_product_shows_vector_returns_whole_pool` | **读产物**：`vector == pool_size`，池为 {9, 14} |
| `test_report_documents_vector_returns_whole_pool` | **读文档**：§6.7 有那两句 |

**3. 拆开"读产物"与"读文档"两条断言**

这是我这一轮踩到的坑（详见 design.md 决策 3）：
一条断言名叫 `test_report_documents_...`，但**只读产物、不读文档**。
删掉文档里那句话，它不会红——**名字声称覆盖的内容无人守**。

## Impact

- 代码：**无**
- 测试：`test_fusion_dilution.py`（新增 4 条，其中 2 条是拆分）
- 文档：`v2-what-it-measures.md` §6 新增两节
- 结果文件：**无新增**（顶层仍 48 个）

## 验收

| # | 判据 | 可被违反的形式 |
|---|---|---|
| 1 | §6 含"机制未区分"且并列两机制 | 删掉任一必须红 |
| 2 | §6 含"累加"与"返回了整个池" | 删掉必须红 |
| 3 | 产物里 `vector == pool_size` | 改一个值必须红 |
| 4 | §6.7 含"返回了整个池"与"cosine 全序" | 删掉必须红 |
| 5 | 改文档只影响文档断言 | 产物断言**必须仍绿** |
| 6 | 改产物只影响产物断言 | 文档断言**必须仍绿** |

**验收 5 与 6 是本变更的核心**：它们是"拆开写"这件事的可执行证据。
合并成一条时，两者会互相掩盖。
