# Tasks

## 0. 为什么要有这个变更

**结论 5 说明了现象，但没有说明原因。** 两个机制都能产生 `0.8333 → 0.5000`：

| 机制 | 处置 |
|---|---|
| 融合规则（RRF 稀释） | 改融合 |
| vector 召回质量（cosine 排序） | 改召回 |

**区分它们需要 cosine 分，而现有产物没有。**

## 1. 核实 `462` 这个数

- [x] 1.1 `path_returns.vector = 462` 是**累加值**

  | 产物 | 顶层 | 单条 case | `pool_size` |
  |---|---|---|---|
  | `a3-lexical-vector-adjacency.json` | 462 | **14** | 14 |
  | `v2-billing-lexical-vector-adjacency.json` | 108 | **9** | 9 |

- [x] 1.2 **单条 case 的 `vector` 恒等于 `pool_size`**
  - 即 vector 路返回**整个池**，排序 = cosine 全序
  - 这解释了 vector-only 召回 10/10、12/12（返回全部）
  - 也解释了它的 `SEH@1` 只有 0.4000 / 0.1667（cosine 排序不准）

- [x] 1.3 纠正两处事实
  - `sample` 池是 **14**，不是 12
  - `v2-sample-lexical-vector-adjacency.json` **不存在**

## 2. 报告新增两节

- [x] 2.1 §6.6 机制未区分（两个机制并列 + 为什么不能区分）
- [x] 2.2 §6.7 关于「462 条」这个数（累加 / 返回整个池 / cosine 全序）
- [x] 2.3 原 §6.6 复算顺延为 §6.8

## 3. 新增断言

- [x] 3.1 `test_report_states_mechanism_is_undifferentiated`
- [x] 3.2 `test_report_does_not_claim_462_is_per_case`
- [x] 3.3 `test_product_shows_vector_returns_whole_pool`（**只读产物**）
- [x] 3.4 `test_report_documents_vector_returns_whole_pool`（**只读文档**）

- [x] 3.5 **拆开的理由**（本轮踩的坑）
  - 第一版只有一条，名叫 `test_report_documents_...`，但**只读产物**
  - 删掉文档那句话它不红——**名字覆盖了，实现没覆盖**
  - 证伪时它红过一次，但那是"临时目录缺产物"，与文档无关
  - 差点当成证伪成功

## 4. 双向证伪（8 个方向全部符合预期）

| # | 构造 | 期望 | 实测 |
|---|---|---|---|
| A | 删掉「机制未区分」那一节 | 红 | 红 |
| B | 删掉「融合规则」 | 红 | 红 |
| C | 删掉「累加」 | 红 | 红 |
| D | 删掉「返回了整个池」 | 文档红 | 文档红 |
| E | 原文本 | 全绿 | 全绿 |
| F | 改产物里一个 `vector` 值 | 产物红 | 产物红 |
| G | **改文档时产物断言** | **仍绿** | **绿** |
| H | **改产物时文档断言** | **仍绿** | **绿** |

**G 与 H 是拆开写的可执行证据**：合并成一条时，两者会互相掩盖。

## 5. 验收

- [x] 5.1 `openspec validate conclusion5-mechanism-limit --strict` 通过
- [x] 5.2 **归档前**跑 `openspec validate --all --strict`
- [x] 5.3 全量测试通过
- [x] 5.4 归档

## 6. 不在本变更范围

- **不测 cosine 分布**：产物无记录，测出的数字无法复算
- **不改产物格式**：会破坏 v2 冻结或 48 个约束
- **不改融合算法**
- **不造 v3 数据**

## 7. 关于"加 cosine 特征"的正确顺序

若将来要做，顺序必须是：

1. 先决定"cosine 要不要成为正式特征"
2. 若是，则属 **v3 装置变更**
3. 那时让 `results/v3/` 的产物记录 cosine（不动 v2 的 48 份）
4. 用 v3 产物复算分布

**先测分布再决定加不加是错的**：测出的数字只能当探索性证据。

