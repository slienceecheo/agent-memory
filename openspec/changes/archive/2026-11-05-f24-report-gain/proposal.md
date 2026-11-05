## Why

**`F24` 在 v3 下的判据是"高于派生基线"，但 detail 只说"高于/不高于"，不说高多少。**

造完 v3 数据后，读者最想知道的是**排序有没有增益**，而不只是"过没过线"。

## 为什么不定目标区间

有两个看似合理的做法，都会掉进同一个坑：

| 做法 | 后果 |
|---|---|
| 定 `0.5 < ratio < 0.9` | 造数据时为了让 ratio 落进区间而调难度 —— **为达标回头改数据** |
| 先造出来再看 | ratio 落进哪里都接受 —— **上限 `0.9999` 在数据上失去约束力** |

**正确的做法：如实报告 `ratio - baseline`，让增益本身成为结论。**

| `ratio - baseline` | 结论 |
|---|---|
| ≈ 0 | 这份数据上排序没有增益 |
| 明显 > 0 | 有增益，数值就是增益大小 |
| < 0 | 排序比随机还差 |

## 为什么这个区分必须写进 detail

实测 v3 装置跑 v2 数据的两个 subject：

| subject | 派生 within baseline | v3 实测 ratio | 差 |
|---|---|---|---|
| `sample` | 0.3000 | 0.3000 | **+0.0000** |
| `billing` | 0.2778 | 0.0833 | **−0.1944** |

`sample` 的差正好为 0。**这本身是一条结论**：v3 去掉 condition 加权后，
排序在这份数据上没有增益。

**若 detail 只报 `ratio=0.3000`**，读者会以为"比基线好"——
因为基线也是 0.3000，而两个数字写成两句话时看不出它们相等。

## What Changes

**1. `F24` 的 v3 分支 detail 增加差额**

```
旧：实测 12/12=1.0000（v3-billing-...json）
新：实测 12/12=1.0000 vs 派生 within 基线 0.2778（差 +0.7222；v3-billing-...json）
```

**2. v2 分支**继续只报 `ratio`（v2 的判据是"不满分"，没有 baseline 可对照）

**3. 新增 `tests/retrieval/test_f24_reports_gain.py`（4 条断言）**

| 断言 | 判据 |
|---|---|
| `test_f24_reports_gain_in_detail` | 通过时 detail 含 `ratio` / `baseline` / 差值 |
| `test_f24_reports_gain_when_failing_upper_bound` | **红了也报差值**（"太容易"时差值是 +0.7222） |
| `test_f24_reports_gain_when_below_baseline` | 负差值必须保留负号 |
| `test_f24_has_no_target_range` | **不得引入目标区间** |

## Impact

- 代码：`evals/tools/check_v2_dataset.py`（`F24` 的 detail 一行）
- 测试：新增 `test_f24_reports_gain.py`
- 数据 / 结果文件：**无**

## 验收

| # | 判据 | 可被违反的形式 |
|---|---|---|
| 1 | ratio=0.5, baseline=0.2778 | detail 含 `+0.2222` |
| 2 | ratio=1.0（红，太容易） | detail 含 `+0.7222` |
| 3 | ratio=0.0833（红，低于基线） | detail 含 `-0.1944`，负号保留 |
| 4 | 把差值从 detail 里去掉 | 三条报差值的断言**必须红** |
| 5 | 在 `F24` 里加 `TARGET_LOW` | `test_f24_has_no_target_range` **必须红** |

**验收 4 与 5 是一对**：前者防"差值被删"，后者防"用区间代替差值"。
只写 4，人会以为"报差值就行"，然后加个区间"让它更严格"。
