# Tasks

## 0. 为什么要有这个变更

**`n_competitors` 与 `competing_set` 是两个量，而只有 A 轴上 `n+1 == cs`。**

| 查询 | 标注轴 | `n` | `cs` |
|---|---|---|---|
| `ledger-q11/q12` | C | 0 | **12** |
| `billing-c1/c2/c3` | C | 2 | **9** |

按 `n+1` 推池大小会让 cross 基线变成 `1/1 = 1.0`，**与真值 `1/12 = 0.0833` 差 12 倍**。

## 1. `axis_baseline_derived()`（TDD）

- [x] 1.1 写失败测试：`axis_baseline_derived(sample)`
  - 期望 `{"relation_within": 0.3000, "relation_cross": 0.0833}`
  - 验证：`pytest -k derived_baseline_sample` 先红

- [x] 1.2 实现：按 `derive_axis` 分组，`N = len(competing_set(...))`
  - **`N` 从竞争集取，不推 `n_competitors + 1`**
  - 验证：1.1 转绿

- [x] 1.3 写测试（**核心**）：cross 基线必须是 `1/12`，不是 `1/1`
  - 若实现用了 `n+1`，会得到 `1.0` -> 这条红
  - 验证：`pytest -k cross_baseline_is_not_one`

- [x] 1.4 写测试：`billing` 的派生 within 基线是 **0.2778**
  - 构成：9 条 `N=3`（`1/3`）+ 3 条 `N=9`（`1/9`）
  - **不是 0.3333**（那是标注口径）
  - 验证：`pytest -k billing_derived_baseline`

- [x] 1.5 写测试：`n_competitors + 1 == len(competing_set)` 的例外必须被登记
  - 实测 5 条例外，全部是 C 轴
  - 这条把"两个量不同"写成可执行的事实
  - 验证：`pytest -k pool_size_identity_exceptions`

## 2. `F24` 改用派生轴

- [x] 2.1 写测试：v3 下 `F24` 的数据侧用派生 within 基线
  - 造 v3 签名产物，断言 detail 里的基线值来自派生口径
  - 验证：`pytest -k f24_uses_derived_baseline`

- [x] 2.2 实现：v3 分支改用 `axis_baseline_derived()["relation_within"]`
  - v2 分支保持 `axis_baseline(dataset, Axis.A)`
  - 验证：2.1 转绿

- [x] 2.3 写测试：v3 的结果侧判据是 `ratio > baseline`
  - **不是 `ratio < 0.9999`**
  - 构造 `ratio < baseline` 的假产物 -> 必须红
  - 验证：`pytest -k f24_v3_judges_against_baseline`

- [x] 2.4 实现：v3 分支的判据改成与基线比较
  - 验证：2.3 转绿

## 3. 报告"标注与派生不一致"

- [x] 3.1 写测试：能算出每个 subject 的不一致数
  - `sample` 0/12、`billing` **3/12**
  - 验证：`pytest -k axis_label_mismatch_counts`

- [x] 3.2 实现：加一个可复算的辅助函数（供报告与测试共用）

- [x] 3.3 更新 HANDOFF：写 `sample` 0/12、`billing` 3/12

## 4. 验收

- [x] 4.1 `openspec validate bounded-axis-baseline --strict` 通过
- [x] 4.2 **归档前**跑 `openspec validate --all --strict`
- [x] 4.3 全量测试通过
- [x] 4.4 `run_all()` 数字不变（`sample 19/27`、`billing 23/27`）
  - `F24` 在真实 v2 数据上仍不适用（产物签名 v2）
- [x] 4.5 归档

## 5. 不在本变更范围

- **不造 v3 数据**
- **不定 margin**：`ratio > baseline` 不需要 margin
- **不改 `axis_baseline()`**：v2 口径保留供对比
- **不改 `competing_set()`**：它是"唯一的竞争集定义"，本变更只是不把它
  当成 `n_competitors` 用

