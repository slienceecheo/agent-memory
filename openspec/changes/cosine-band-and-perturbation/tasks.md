# Tasks

## 0. 为什么要有这个变更

**我上一轮登记的两条东西都是错的。**

| # | 错 | 后果 |
|---|---|---|
| 1 | 验收判据"稳定 `SEH@1` == 全部 `SEH@1`" | 两种读法都不成立 |
| 2 | `cosine_unstable` 布尔 | 把"可能翻转"与"已排错"压成一个 |

## 1. 复现验收判据的两种失效

- [x] 1.1 读法 1：`unstable = gap < 0.01`（含负 gap）

  | subject | full | stable 子集 | 相等? |
  |---|---|---|---|
  | `sample` | 9/10 = 0.9000 | 9/9 = **1.0000** | **False** |
  | `billing` | 10/12 = 0.8333 | 10/10 = **1.0000** | **False** |

  **永远红**。原因是排除负 gap（已排错）后，剩下全是命中项。

- [x] 1.2 读法 2：`unstable = 0 < gap < 0.01`（只算噪声带）
  - 两个 subject 的 `unstable = 0` -> 集合 == 全集 -> **恒真**

- [x] 1.3 **逻辑错误**：读法 1 等于"先把错的删掉再报准确率"

## 2. 正确的验收：扰动

- [x] 2.1 判据：稳定 case 在 `±0.0061` 的扰动下 top-1 不翻转

- [x] 2.2 实测

  | subject | 稳定 case | 扰动次数 | 翻转 | 噪声/最小 gap |
  |---|---|---|---|---|
  | `sample` | 9 | **2700** | **0** | **0.45** |
  | `billing` | 10 | **3000** | **0** | **0.14** |

  **合计 5700 次扰动，0 次翻转。**

- [x] 2.3 **扰动的是"分"不是"向量"**
  - 保守近似：真实扰动幅度取决于夹角（最大 0.0061），按分统一扰动覆盖最坏情况
  - 保守方向安全：0 翻转的结论更强

- [x] 2.4 **`sample` 的噪声是最小 gap 的 45%**
  - 离翻转只剩 55% 余量，比 `billing`（14%）紧得多
  - 这个比值必须写进报告

## 3. 字段从布尔改三态

- [x] 3.1 旧：`cosine_unstable = gap < 0.01`

- [x] 3.2 新：`cosine_band` 三态

  | 区间 | band | 含义 | 处置 |
  |---|---|---|---|
  | `gap >= 0.01` | `stable` | 噪声下不翻转 | 可用于结论 |
  | `0 <= gap < 0.01` | `noise` | 可能翻转 | 记录并排除 |
  | `gap < 0` | **`negative`** | **已排错** | **不能排除** |

- [x] 3.3 负 gap 实测

  | subject | 条数 | case |
  |---|---|---|
  | `sample` | **1** | `ledger-q2`（−0.0542） |
  | `billing` | **2** | `billing-a2`（−0.0402）、`billing-c3`（−0.0429） |

- [x] 3.4 **这是第四次遇到"布尔压掉两种坏"**
  - 前面三次：装置签名 v2/v3、门禁 applicable/passed、统计量 A/B/C 类

## 4. 命名约束

- [x] 4.1 `(0,0,1)` **不得叫 `uniform`**
  - `uniform` 暗示"各项相等"，而它是"只有一项"
  - 且与 `disabled_weights()` 的 `(1,0,0)` 语义冲突

- [x] 4.2 建议命名

  | 权重 | 名字 |
  |---|---|
  | `(0,0,1)` | **`cosine_only`** / `single_signal` |
  | `(0.2,0.2,0.6)` | **`mixed`** |

## 5. 新增 `tests/retrieval/test_cosine_band.py`（11 条）

| 断言 | 判据 |
|---|---|
| `test_band_is_three_states` | 三态都用到（退化两态必须红） |
| `test_band_counts_match_report` | 9/0/1、10/0/2 |
| `test_negative_cases_are_named` | 三个 case 名单 |
| `test_min_stable_gap_matches_report` | 0.0136 / 0.0447 |
| `test_subset_equality_criterion_is_broken` | **记录两种失效方式** |
| `test_stable_cases_do_not_flip_under_noise` | 5700 次 0 翻转 |
| `test_noise_ratio_is_registered` | 0.45 / 0.14 |
| `test_report_states_two_failed_readings` | 失效表两行 |
| `test_report_states_perturbation_acceptance` | 实测表 + 合计句 |
| `test_report_states_three_state_band` | 字段行含三取值 |
| `test_report_forbids_uniform_naming` | `(0,0,1)` -> `cosine_only` 行 |

## 6. 双向证伪（14 个方向全部符合预期）

| # | 构造 | 期望 | 实测 |
|---|---|---|---|
| A | 去掉 `negative`（退化两态） | 红 | 红 |
| B | `stable` gap 改成 0.001 | 红 | 红（1167/2700 翻转） |
| C | `sample` 少一条 negative | 红 | 红 |
| D | 负 gap 名单改错 | 红 | 红 |
| E | 最小 stable gap 改 0.05 | 红 | 红 |
| G | 删掉「永远红」 | 红 | 红 |
| H | 删掉「5700」 | 红 | 红 |
| I | 删掉 `cosine_band` | 红 | 红 |
| J | 删掉 `cosine_only` | 红 | 红 |
| F | 原文本（4 条） | 绿 | 绿 |

**证伪时又抓到三处弱判据**（都是"字符串在段落里出现多次"）：
G、H、I、J 最初都没红。已全部改成定位到表格行。

**J 还额外抓到一处 `or` 造成的弱判据**：
`("cosine_only" in r or "single_signal" in r)` —— 删掉前半个，后半个仍满足。

## 7. 验收

- [x] 7.1 `openspec validate cosine-band-and-perturbation --strict` 通过
- [ ] 7.2 **归档前**跑 `openspec validate --all --strict`
- [ ] 7.3 全量测试通过
- [ ] 7.4 归档

## 8. 不在本变更范围

- **不改产物格式**（`cosine_band` 只登记）
- **不改权重**
- **不加 cosine 特征**
