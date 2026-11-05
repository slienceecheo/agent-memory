# Tasks

## 0. 为什么要有这个变更

cosine 的四条泄漏判据全过，但它依赖 embedding 稳定性。
`AGENTS.md` 登记了"embedding 非确定性"，必须先量化它对名次的影响。

## 1. 非确定性只在缓存未命中时出现

- [x] 1.1 实测缓存命中的确定性

  ```
  同一文本两次（缓存命中）: max|diff| = 0.00e+00
  cos = 1.0000000000
  ```

  **`run_retrieval` 走缓存，所以重跑同一份产物是逐位可复现的。**

- [x] 1.2 缓存未命中时 `cos = 0.9971`（约 4.36°）

## 2. 向量噪声换算到"分"的尺度

- [x] 2.1 **不能直接把 0.9971 当作分的噪声**
  - 用户手推 `sin(角度差) × θ ≈ 0.0056`
  - 我实测旋转真实向量（30 个样本）

  | 量 | 值 |
  |---|---|
  | 均值 | **0.0019** |
  | P95 | **0.0051** |
  | **最大** | **0.0061** |

- [x] 2.2 夹角越大越敏感

  | 夹角 | n | 均值 | 最大 |
  |---|---|---|---|
  | 40–70° | 26 | 0.0020 | **0.0061** |
  | ≥ 70° | 4 | 0.0016 | 0.0021 |

## 3. 阈值：0.01，不是 0.006

- [x] 3.1 **用户建议 0.006，但它小于实测最大值 0.0061**
  - 那会让判据卡在自己的噪声边界上

  | 阈值 | 与噪声最大值的关系 | 判定 |
  |---|---|---|
  | 0.006 | **小于** 0.0061 | ❌ |
  | **0.01** | **1.6 倍** | ✅ |

## 4. `cosine_gap` 分布

- [x] 4.1 实测

  | subject | 正 gap 最小 | case | `gap < 0.01` | 负 gap（排错） |
  |---|---|---|---|---|
  | `sample` | **0.0136** | `ledger-q8` | **0** | **1**（`ledger-q2`） |
  | `billing` | **0.0447** | `billing-c2` | **0** | **2**（`a2`、`c3`） |

- [x] 4.2 **负 gap 必须与"不稳定"分开计数**
  - 负 gap 是"已经排错"，不是"可能翻转"
  - 若混算会得出"`billing` 17% 不稳定"这种误导数字

## 5. 敏感度归因

- [x] 5.1 **不是池大小，是 tie 紧密度**

  | subject | 池大小 | 正 gap 最小 | 与噪声之比 |
  |---|---|---|---|
  | `billing` | **9**（更小） | 0.0447 | **7.3×** |
  | `sample` | **14**（更大） | 0.0136 | **2.2×** |

  **池更小的 `billing` 反而更稳定。**

## 6. 新增 `tests/retrieval/test_cosine_noise_boundary.py`（11 条）

| 断言 | 判据 |
|---|---|
| `test_cache_hit_is_bitwise_identical` | `max|diff| == 0` |
| `test_rotation_delta_within_bound` | 最大值 <= 0.01 且 > 0.001 |
| `test_threshold_exceeds_measured_noise` | 阈值 > 噪声最大值，且 >= 1.5 倍 |
| `test_no_case_falls_in_noise_band` | `unstable == 0` |
| `test_min_positive_gap_matches_report` | 最小 gap 与 case 都一致 |
| `test_wrong_cases_are_counted_separately` | 负 gap 条数与名单 |
| `test_sensitivity_is_tie_not_pool_size` | 池更小的 gap 更大 |
| `test_report_states_both_cache_states` | 缓存命中/未命中都写 |
| `test_report_states_threshold_rationale` | 阈值对比表两行 |
| `test_report_separates_wrong_from_unstable` | 三个排错 case 都点名 |
| `test_report_registers_future_fields` | 字段表两行 + tie 先例 |

## 7. 双向证伪（18 个方向全部符合预期）

| # | 构造 | 期望 | 实测 |
|---|---|---|---|
| A | 阈值改 0.006（小于噪声） | 红 | 红 |
| B | 噪声上界改 0.02 | 红 | 红 |
| C | `sample` unstable=1 | 红 | 红 |
| D | 把负 gap 混进 unstable | 红 | 红 |
| E | 池大小关系反转 | 红 | 红 |
| F | gap 关系反转 | 红 | 红 |
| G | 最小 gap 与报告不符 | 红 | 红 |
| I | 删掉 `0.0061` 那格 | 红 | 红 |
| J | 删掉 `cosine_gap` 整行 | 红 | 红 |
| H | 原文本（4 条） | 绿 | 绿 |

**A 与 B 是本变更的核心**：阈值必须大于实测噪声，两个方向都能抓。

## 8. 修章节号断层

- [x] 8.1 插入新节后 `6.12.3` / `6.12.5` 缺失
- [x] 8.2 重编为连续的 6.12.1–6.12.5
- [x] 8.3 **同时修了两个测试的 `_sub()` 边界**
  - 插入 §6.12.6 后，`split("#### 6.12.5")` 找不到边界
  - 把后面内容全包进来 -> "证明"从别处混入 -> 断言误红（其实是对的边界问题）
  - 已改成 `split("#### 6.12.6")`

## 9. 验收

- [x] 9.1 `openspec validate cosine-noise-boundary --strict` 通过
- [x] 9.2 **归档前**跑 `openspec validate --all --strict`
- [x] 9.3 全量测试通过
- [x] 9.4 归档

## 10. 不在本变更范围

- **不改产物格式**（`cosine_gap` / `cosine_unstable` 只登记，不实施）
- **不改权重**
- **不加 cosine 特征**
- **不实施"稳定 case 子集"验收**

