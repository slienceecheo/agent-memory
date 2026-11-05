# Tasks

## 0. 为什么要有这个变更

**真正的问题不是"加不加 cosine"，而是"lexical 的 0.83 / 0.89 里有多少是排序能力"。**

若高分主要来自"query 与 gold 共享词面"，那它不是排序能力，是**数据太容易**——
而那正是 `F24` 一直在找的"数据太简单"。

## 1. 三组必须分开

- [x] 1.1 定义 A/B/C

  | 组 | 含义 | 能否用重叠解释 |
  |---|---|---|
  | A | 召回了 gold **且** top-1 | ✅ |
  | B | 召回了 gold 但未 top-1 | ✅（对照） |
  | C | **没召回 gold** | ❌ |

- [x] 1.2 实测三组

  | subject | A | B | C（未召回） |
  |---|---|---|---|
  | `sample` | 5 | 1（q2=0.040） | **4，bigram 全 0** |
  | `billing` | 8 | 1（a6=0.156） | 3，均值 0.0104 |

- [x] 1.3 **修正一个过强的假设**
  - 我第一版写"C 组 bigram 全为 0"
  - 实测 `billing-a2` 未召回但 bigram = **0.031**（共享"发票"）
  - 准确说法：**未召回 = 重叠不足以进入召回**，不是"没有重叠"

## 2. 置换检验（n 小，穷举可行）

- [x] 2.1 `sample`：C(6,5)=6 种组合，均值差 +0.1837，**p = 0.0079（显著）**

- [x] 2.2 `billing`：C(12,8)=495 种组合，均值差 +0.0612，**p = 0.1091（不显著）**

- [x] 2.3 **结论分裂，不能统一**

## 3. 两处关键发现

- [x] 3.1 `sample` 的 5 条 top-1 **全部 bigram ≥ 0.05**

  | case | bigram |
  |---|---|
  | `ledger-q1` | 0.462 |
  | `ledger-q10` | 0.182 |
  | `ledger-q5` | 0.172 |
  | `ledger-q6` | 0.100 |
  | `ledger-q9` | 0.053 |

- [x] 3.2 `billing` 的 8 条 top-1 里 **3 条 bigram < 0.05**

  | case | bigram | 共享的是什么 |
  |---|---|---|
  | `billing-c1` | 0.0357 | "发票"的语义 |
  | `billing-c2` | 0.0345 | "申报" |
  | `billing-a3` | 0.0488 | **德国↔欧洲** |

  **这是语义相关，不是词面重叠。**

- [x] 3.3 所以"lexical 高分 = 数据太容易"**不成立**
  - `sample` 上成立，`billing` 上不成立
  - 强行统一会去给 billing 加难度，而实际那 3 条是真实能力

## 4. 新增测试（10 条）

| 断言 | 判据 |
|---|---|
| `test_three_groups_are_disjoint_and_cover_all` | A/B/C 互斥且覆盖全部 |
| `test_group_membership_matches_report` | 三组成员 == 报告 §6.9 |
| `test_not_recalled_group_overlap_is_negligible` | C 组 bigram < 0.05 |
| `test_sample_top1_all_have_overlap` | sample A 组全部 ≥ 0.05 |
| `test_billing_has_low_overlap_top1` | billing 低重叠 == 3 条 |
| `test_permutation_results_split_by_subject` | sample p<0.05 且 billing p>0.05 |
| `test_a_group_means_match_report` | A 均值 == 报告 |
| `test_report_states_the_split_conclusion` | §6.9 有"结论分裂"与两个 p |
| `test_report_does_not_claim_data_is_too_easy` | §6.9 否定那个推广，点名 3 条 |
| `test_report_registers_bigram_blind_spot` | §6.9 有"语义"与"德国/欧洲" |

## 5. 双向证伪（13 个方向全部符合预期）

| # | 构造 | 期望 | 实测 |
|---|---|---|---|
| A | billing A 组全改 0.2（无低重叠） | 红 | 红 |
| B | sample p 改 0.5 | 红 | 红（"期望 < 0.05"） |
| B2 | **billing p 改 0.01** | 红 | 红（"期望 > 0.05"） |
| A2 | 一个 case 同时在 A 与 B | 红 | 红（"A 与 B 有交集"） |
| C | 删掉报告"结论分裂" | 红 | 红 |
| D | 删掉报告里 `billing-c1` | 红 | 红 |
| E | 原文本 | 全绿 | 全绿 |

**B 与 B2 方向相反**：一个要求 p < 0.05，一个要求 p > 0.05。
这本身就是"结论分裂"的可执行形式。

## 6. 验收

- [x] 6.1 `openspec validate lexical-provenance --strict` 通过
- [x] 6.2 **归档前**跑 `openspec validate --all --strict`
- [x] 6.3 全量测试通过
- [x] 6.4 归档

## 7. 不在本变更范围

- **不测 cosine**：无法从产物复算（上一轮已确认）
- **不定 v3 产物格式**：格式取决于"cosine 是否参与排序"这个未决决策
- **不加特征、不改融合**
- **不造 v3 数据**
- **不新增 results 文件**

