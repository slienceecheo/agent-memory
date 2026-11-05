# Tasks

## 0. 为什么要有这个变更

`F24` 只说"高于/不高于基线"，不说**高多少**。造完 v3 数据后，
读者最想知道的是"排序有没有增益"，而不只是"过没过线"。

而"定目标区间"会诱导造数据时调难度。所以改成**如实报差值**。

## 1. `F24` 的 detail 增加差额

- [x] 1.1 v3 分支加 `差 {gain:+.4f}`
  - 旧：`实测 12/12=1.0000（v3-billing-...json）`
  - 新：`实测 12/12=1.0000 vs 派生 within 基线 0.2778（差 +0.7222；v3-billing-...json）`

- [x] 1.2 v2 分支保持原样
  - v2 判据是"不满分"，没有结果侧 baseline 可对照

- [x] 1.3 用 `+.4f` 而不是 `.4f`
  - 负号必须保留：`-0.1944` 与 `+0.1944` 是相反的结论

## 2. 新增 `tests/retrieval/test_f24_reports_gain.py`

- [x] 2.1 `test_f24_reports_gain_in_detail`（通过时）
- [x] 2.2 `test_f24_reports_gain_when_failing_upper_bound`（红，太容易，`+0.7222`）
- [x] 2.3 `test_f24_reports_gain_when_below_baseline`（红，低于基线，`-0.1944`）
- [x] 2.4 `test_f24_has_no_target_range`（不得引入区间）

## 3. 双向证伪（10 个方向全部符合预期）

| 组 | 构造 | 期望 | 实测 |
|---|---|---|---|
| 基线 | 原实现 | 4 条绿 | 绿 |
| A1 | 去掉差值，ratio=0.5 | 红（缺 `+0.2222`） | 红 |
| A2 | 去掉差值，ratio=1.0 | 红（缺 `+0.7222`） | 红 |
| A3 | 去掉差值，ratio=0.0833 | 红（缺 `-0.1944`） | 红 |
| B1 | 注入 `TARGET_LOW = 0.5` | 断言会红 | 是 |
| B2 | 注入 `target_high = 0.9` | 断言会红 | 是 |
| B3 | 原 body 不含区间标记 | 通过 | 通过 |

**A 组证明"差值真的被检查"，B 组证明"区间真的被禁止"。**

## 4. 验收

- [x] 4.1 `openspec validate f24-report-gain --strict` 通过
- [ ] 4.2 **归档前**跑 `openspec validate --all --strict`
- [ ] 4.3 全量测试通过
- [ ] 4.4 归档

## 5. 不在本变更范围

- **不造 v3 数据**
- **不改 `F24` 的判据**（仍是 `baseline < ratio < 0.9999`）
- **不动 v2 分支的 detail**
- **不定任何目标区间**
