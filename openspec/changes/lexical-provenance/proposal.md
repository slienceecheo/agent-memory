## Why

**真正的问题不是"加不加 cosine"，而是"lexical 的 0.83 / 0.89 里有多少是排序能力"。**

若那个高分主要来自"query 与 gold 共享词面"，那它不是排序能力，而是**数据太容易**。
而那正是 `F24` 一直在找的"数据太简单"。

## 实测（三组分开，不能混算）

**必须分清三类**，因为"未召回"与"没排对"是两个不同的问题：

| 组 | 含义 |
|---|---|
| A | lexical 召回了 gold **且** top-1 |
| B | lexical 召回了 gold 但未 top-1 |
| C | **lexical 没召回 gold**（与重叠无关） |

### `sample`

| 组 | n | bigram 均值 | 逐条 |
|---|---|---|---|
| A 召回了且 top-1 | 5 | **0.1937** | q1=0.462, q5=0.172, q6=0.100, q9=0.053, q10=0.182 |
| B 召回但未 top-1 | 1 | 0.0400 | q2=0.040 |
| C **未召回** | 4 | **0.0000** | q3/q4/q7/q8 = 0（全是 implicit） |

**A 组里 bigram < 0.05 的：0/5。**

### `billing`

| 组 | n | bigram 均值 | 逐条 |
|---|---|---|---|
| A 召回了且 top-1 | 8 | **0.1353** | a1=0.240, a3=0.049, a4=0.240, a5=0.233, a7=0.125, a8=0.125, c1=0.036, c2=0.034 |
| B 召回但未 top-1 | 1 | 0.1562 | a6=0.156 |
| C **未召回** | 3 | 0.0104 | a2=0.031, a9=0.000, c3=0.000 |

**A 组里 bigram < 0.05 的：3/8**（a3、c1、c2）。

## 两个 subject 的形态不同

| 量 | sample | billing |
|---|---|---|
| A 组均值 | **0.1937** | **0.1353** |
| A 组低重叠（< 0.05） | **0/5** | **3/8** |
| 置换检验（A vs B/C） | **p = 0.0079 显著** | **p = 0.1091 不显著** |

**结论分化**：

- `sample`：**词面重叠能解释 top-1**（A 组全部 ≥ 0.05，检验显著）
- `billing`：**词面重叠解释不了一半**（3/8 的 top-1 来自低重叠的 c1/c2/a3）

**所以不能写成"lexical 的高分就是数据太容易"**——那在 `billing` 上不成立。

## `billing` 那 3 条低重叠的命中考了什么

| case | bigram | 机制 |
|---|---|---|
| `billing-c1` | 0.0357 | **C 轴**。query 是"发票币种是怎么规定的？"，gold 是"国内客户的发票一律开人民币"——共享的是"发票"这个词的语义，不是字面片段 |
| `billing-c2` | 0.0345 | **C 轴**。query"税务申报是按什么分的？"，gold"华北的客户在北京税局申报"——共享"申报" |
| `billing-a3` | 0.0488 | query"德国那边的账怎么开"，gold"欧洲客户走欧元发票"——**跨语种/近义**（德国↔欧洲） |

**这不是"词面重叠"，是"语义相关"**。而 bigram 抓不到它。

**这反而是好消息**：说明 lexical 路径不完全是字面匹配。
但它也说明 **bigram 作为"数据是否太容易"的指标不够**——它会漏掉语义相关。

## What Changes

**1. 新增 `tests/retrieval/test_lexical_provenance.py`**

| 断言 | 判据 |
|---|---|
| `test_three_groups_are_disjoint` | A/B/C 三类必须互斥且覆盖全部 |
| `test_sample_top1_all_have_background_overlap` | sample 的 A 组全部 bigram ≥ 0.05 |
| `test_billing_has_low_overlap_top1` | billing 的 A 组有 3 条 < 0.05 |
| `test_permutation_test_results` | sample p < 0.05、billing p > 0.05 |
| `test_not_recalled_group_is_the_denominator_issue` | C 组的 bigram 全为 0（隐式查询） |

**2. 报告新增 §6.9（lexical 高分的来源）**

**3. 明确不写"lexical 高分 = 数据太容易"**

那在 `billing` 上不成立。

## Impact

- 代码：**无**
- 测试：新增 `test_lexical_provenance.py`
- 文档：`v2-what-it-measures.md` §6.9
- 结果文件：**无新增**

## 验收

| # | 判据 | 可被违反的形式 |
|---|---|---|
| 1 | A/B/C 三类互斥且覆盖全部 | 重复计数必须红 |
| 2 | sample A 组最小 bigram | 必须 ≥ 0.05 |
| 3 | billing A 组低重叠条数 | 必须 == 3 |
| 4 | sample 置换 p | 必须 < 0.05 |
| 5 | billing 置换 p | 必须 > 0.05 |
| 6 | C 组 bigram | 必须全为 0 |

**验收 4 与 5 方向相反**，这本身就是结论：
两个 subject 的形态不同，不能合并成一个说法。
