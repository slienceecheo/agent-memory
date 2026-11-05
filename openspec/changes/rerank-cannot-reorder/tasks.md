# Tasks

## 0. 为什么要有这个变更

**"候选集太大"不是主因。主因是重排层无法改变融合顺序。**

我曾倾向"裁剪候选集"，实测否决。用户提出"重排无法改变顺序"，实测成立。

## 1. 决定性证据：gold 在前 3 名却排不到第 1

- [x] 1.1 位置分布

  | subject | gold 在融合顺序中的位置 | 中位数 | rank ≤ 3 | top-1 |
  |---|---|---|---|---|
  | `sample` | `[1,1,2,2,2,3,3,4,4,8]` | 3 | **7/10** | 2/10 |
  | `billing` | `[1,1,2,2,2,2,2,3,3,3,3,6]` | 2 | **11/12** | 2/12 |

  **billing 有 11/12 在前 3，却只有 2/12 排第一。**

- [x] 1.2 机制：`base = rrf_norm(fusion_score)` 严格单调
  - 按 base 排序 == 融合顺序
  - 实测 `base-only` top-1 **等于**融合 rank-1 率（2/10、2/12）

- [x] 1.3 **billing 上重排让结果变差**
  - 融合 rank-1 = 2/12，threeway top-1 = **1/12**
  - 重排不只"没有信号"，它**主动破坏了本来对的那一条**
  - 机制：authority 分层把 fusion rank-1 的 gold 推到更高 authority 的干扰项后面

- [x] 1.4 另外两个特征
  - `authority`：与 gold 无关（唯一最高 0/22），只做分层
  - `status`：恒为常数

## 2. 裁剪候选集：实测否决

- [x] 2.1 增益随 N 单调递增

  | N | `sample` 增益 | `billing` 增益 |
  |---|---|---|
  | 1 | **−0.8000** | **−0.8333** |
  | 3 | −0.0333 | −0.2500 |
  | 5 | +0.1000 | −0.1167 |
  | 全量 | **+0.2167** | **−0.0278** |

- [x] 2.2 原因：`增益 = SEH@1 − 基线`，裁剪让基线从 `1/9` 跳到 `1/1`（涨 9 倍），
  而 `SEH@1` 最多涨到 1——**基线涨得比命中率快**

- [x] 2.3 而且裁剪会把 gold 排除在外（N=1 时只剩融合第 1 名）

## 3. cosine：唯一有证据的候选

- [x] 3.1 证据

  | 量 | `sample` | `billing` |
  |---|---|---|
  | cosine top-1（全融合候选集） | **0.9000** | **0.8333** |
  | threeway `SEH@1` | 0.3000 | 0.0833 |
  | "只有 cosine 最高" | 4/10 | 2/12 |

- [x] 3.2 **撤销上一轮的"cosine 只能追平"**
  - 那个结论比较了两个不同候选集：lexical 的 6/9 条 vs 全融合的 10/12 条

- [x] 3.3 泄漏检查（三条判据）

  | subject | gold 均值 | dist 均值 | 差 | 唯一最高 | 重叠 |
  |---|---|---|---|---|---|
  | `sample` | 0.5836 | 0.4163 | **+0.1673** | **9/10** | ✅ 0.4692 < 0.5770 |
  | `billing` | 0.6585 | 0.5429 | **+0.1156** | **10/12** | ✅ 0.4517 < 0.6431 |

  **三条都过**，所以是"真信号"不是"泄漏"。

## 4. 新增 `tests/retrieval/test_rerank_cannot_reorder.py`（10 条）

| 断言 | 判据 |
|---|---|
| `test_gold_fusion_position_distribution` | 分布 == 报告 |
| `test_position_distribution_shows_headroom` | rank≤3 > top-1 × 2 |
| `test_base_only_equals_fusion_top1` | 两者相等 |
| `test_rerank_never_improves_top1` | billing 上变差 |
| `test_cropping_gain_is_monotonic` | 增益随 N 递增 |
| `test_cosine_leak_guard` | 三条判据 |
| `test_cosine_beats_current_threeway` | 差 > 0.5 |
| `test_report_states_rerank_cannot_reorder` | §6.11 有机制与比例 |
| `test_report_states_cropping_is_rejected` | §6.11 有"否决" |
| `test_report_states_cosine_evidence` | §6.12 表格行含差值 |

## 5. 报告新增 §6.11 / §6.12

- [x] 5.1 §6.11.1 位置分布（7/10、11/12）
- [x] 5.2 §6.11.2 base == 融合顺序（2/10、2/12 相等）
- [x] 5.3 §6.11.2b **billing 上重排变差**（2/12 → 1/12）
- [x] 5.4 §6.11.3 裁剪被否决（单调表）
- [x] 5.5 §6.12.1 cosine 证据
- [x] 5.6 §6.12.2 泄漏检查三条判据
- [x] 5.7 §6.12.3 若要加 cosine 需四步（推荐替换 status）
- [x] 5.8 原 §6.10 复算顺延为 §6.13

## 6. 双向证伪（19 个方向全部符合预期）

| # | 构造 | 期望 | 实测 |
|---|---|---|---|
| A | `q10` 位置 8→9 | 红 | 红 |
| B | `billing` base_top1=3 | 红 | 红 |
| C | rank≤3 只有 1/10 | 红 | 红 |
| D | 裁剪增益非单调 | 红 | 红 |
| E | cosine 差 0.6（泄漏） | 红 | 红 |
| F | 唯一最高 12/12 | 红 | 红 |
| G | `min_gold > max_dist` | 红 | 红 |
| I | 删掉 `7/10` | 红 | 红 |
| J | 删掉 cosine 差值 | 红 | 红 |
| H | 原文本（3 条） | 绿 | 绿 |

**证伪期间发现 `+0.1673` 在 §6.12 出现两次**，全局 `in` 会被顶替，
已改成断言表格行。

## 7. 验收

- [x] 7.1 `openspec validate rerank-cannot-reorder --strict` 通过
- [ ] 7.2 **归档前**跑 `openspec validate --all --strict`
- [ ] 7.3 全量测试通过
- [ ] 7.4 归档

## 8. 不在本变更范围

- **不加 cosine 特征**：需要产物格式变更（四步，见 design.md 决策 5）
- **不改融合规则**
- **不造 v3 数据**
- **不删 `status` 字段**：它是观测事实，只是不该参与加权
