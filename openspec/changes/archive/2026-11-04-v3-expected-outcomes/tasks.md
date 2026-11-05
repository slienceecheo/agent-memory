# Tasks

## 0. 为什么要有这个变更

**v3 数据造出来后，3 条门禁会验它，而它们红的含义不同。**

| 门禁 | 归因 | 红了说明 | 该去查什么 |
|---|---|---|---|
| `F19b` | `data` | 某条 implicit 的 gold 没被召回 | 召回路径 |
| `F20` | `apparatus` | condition 又回到加权里 | 排序代码 |
| `F24` | `data` | 数据太难或太简单 | 数据本身 |

不写清这个区分，造完数据看到红色会去改错的东西。

## 1. 核实"结构必然"这个分类是否成立

- [x] 1.1 验证 `F19b` 是否结构必然
  - 构造：v3 签名 + 把 `ledger-q3` 的 rank 设为 `None`
  - 实测：`applicable=True passed=False`，"1 条 implicit 从未被召回"
  - **结论：不是结构必然。它依赖数据。**

- [x] 1.2 验证 `F20` 是否结构必然
  - 构造 A：v3 签名 + drop=0 -> `passed=True`，`+0.0000`
  - 构造 B：v3 签名 + drop=0.5 -> `passed=False`，`0.5000 不为 0`
  - **结论：是结构必然，但"必然"来自 ablate 两次跑出相同 ranks，
    不是"签名对了就自动通过"。**

- [x] 1.3 记录被推翻的假设
  - 原假设："前两条是结构必然，第三条由数据决定"
  - 实测：`F19b` 是数据依赖，`F20` 才是结构必然
  - **真实分类是三档，不是两档**

## 2. 新增 `tests/retrieval/test_v3_expected_outcomes.py`

- [x] 2.1 三档归因写成常量
  ```python
  RED_ATTRIBUTION = {"F19b": "data", "F20": "apparatus", "F24": "data"}
  ```

- [x] 2.2 每条归因都有行为级证据

  | 断言 | 证明什么 |
  |---|---|
  | `test_f19b_is_data_dependent_not_structural` | 破坏一条 rank -> 必须红 |
  | `test_f19b_does_not_judge_apparatus` | v2 产物也照跑 |
  | `test_f20_v3_zero_drop_is_structural` | drop=0 -> 通过 |
  | `test_f20_catches_contradictory_drop` | drop=0.5 -> **红** |
  | `test_f20_red_means_apparatus_regression` | detail 指向"condition 又参与了加权" |
  | `test_f24_red_means_data_difficulty` | detail 含"太容易"/"基线" |
  | `test_red_attribution_covers_exactly_the_v3_aware_gates` | 归因表 == AST 派生 |
  | `test_only_f20_is_attributed_to_apparatus` | 只有 F20 归因到装置 |

- [x] 2.3 归因表与发现方式表分开
  - `DISCOVERED_GATES`（已有，`test_result_side_gates.py`）
  - `RED_ATTRIBUTION`（新增，本文件）
  - 集合必须相同（断言之），但判的是不同的事

## 3. 双向证伪（5 个方向全部符合预期）

| # | 构造 | 期望 | 实测 |
|---|---|---|---|
| 1 | 原文本 | 绿 | 绿 |
| 2 | 把 `F19b` 改成恒通过 | 红 | 红（"仍然通过——那说明它的判据不是召回"） |
| 3 | 把 `F20` 改成只看签名 | 红 | 红（"drop=0.5 竟然通过——必然为 0 变成恒真断言"） |
| 4 | 把 `F19b` 归因改成 `apparatus` | 红 | 红（"归因到装置的门禁是 ['F19b','F20']"） |
| 5 | 归因表漏掉 `F24` | 红 | 红（"归因表覆盖 ['F19b','F20']，而能看到 v3 的是三条"） |

**第 3 个方向最重要**：它防的是"结构必然"退化成"恒真断言"。

## 4. 验收

- [x] 4.1 `openspec validate v3-expected-outcomes --strict` 通过
- [x] 4.2 **归档前**跑 `openspec validate --all --strict`
- [x] 4.3 全量测试通过
- [x] 4.4 归档

## 5. 不在本变更范围

- **不造 v3 数据**
- **不改任何门禁的判据**
- **不重跑评测**：`F20` 的"必然"论证基于 `ablate()` 的代码结构
  （两次调用 `_run`，v3 下 condition 不参与 features，所以 ranks 必然相同）

