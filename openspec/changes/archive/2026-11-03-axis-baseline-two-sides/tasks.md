# Tasks

## 0. 为什么要有这个变更

上一轮的 `axis_baseline_derived` 与 `F24` 的 v3 分支有三处缺口：

| # | 缺口 | 后果 |
|---|---|---|
| 1 | 空组返回 `0.0` | "没有数据"伪装成"最容易达标的基线" |
| 2 | v3 只设下限 | 放行"数据太简单"（池小 -> 容易满分） |
| 3 | v3 数据侧恒真未写明 | 读者以为两段都在验 |

## 1. 空组返回 `None`（TDD）

- [x] 1.1 写失败测试：`billing` 的 `relation_cross` 必须是 `None`
  - 实测 `billing` 三个 relation 全多分支，12 条派生全在 within
  - 旧实现返回 `0.0`
  - 验证：`pytest -k billing_has_no_cross_axis`

- [x] 1.2 实现：`sum(...)/len(...) if values else None`
  - 返回类型改 `dict[str, float | None]`
  - 验证：1.1 转绿

- [x] 1.3 写测试（反向）：`sample` 的 `relation_cross` 必须是 `0.0833`
  - 确认 `None` 不是普遍行为
  - 验证：`pytest -k cross_baseline_is_usable_when_present`

- [x] 1.4 `F24` 的调用点加 `None` 防护
  - `derived.get("relation_within")` 为 `None` -> `applicable=False`
  - 验证：导入与执行不抛 `TypeError`

## 2. v3 加回上限

- [x] 2.1 写失败测试：v3 下满分（`ratio=1.0`）必须**红**
  - 旧实现 `ratio > baseline` 会让 1.0 通过
  - 验证：`pytest -k f24_v3_has_no_upper_bound_gap`

- [x] 2.2 实现：`baseline < ratio < ceiling`
  - 验证：2.1 转绿

- [x] 2.3 写测试：`ratio=0.5`（`baseline < 0.5 < ceiling`）必须**绿**
  - 确认上限不会把正常值判红
  - **不能用 ratio=1.0**：它已被上限覆盖
  - 验证：`pytest -k f24_v3_judges_against_baseline`

## 3. 登记 v3 数据侧恒真

- [x] 3.1 写测试：断言"理论最大基线 < 0.9999"
  - 派生 within 池大小 `>= 2` -> 基线最大 `0.5`
  - 实测 `sample` / `billing` 都是 `1/3`
  - 若将来池退化成 1，这条会红
  - 验证：`pytest -k f24_v3_data_side_is_vacuous`

- [x] 3.2 在代码注释与 spec 里写明"v3 数据侧恒真"
  - 保留该判据：它防"池大小退化成 1"
  - 明确"真正有判别力的是结果侧"

## 4. 两处既有测试的语义更新

- [x] 4.1 `test_gate_discovers_zones::test_f24_finds_zone_products`
  - 上一轮断言"满分应通过"（那时只有下限）
  - 现在满分被上限判红 -> 改为断言"能发现并执行"+ 满分被上限拦
  - **这条只验"发现"，判据结果由 `test_f24_derived_axis.py` 覆盖**

- [x] 4.2 `test_f24_v3_judges_against_baseline`
  - 上一轮用 `ratio=1.0` 验下限
  - 现在 1.0 被上限拦 -> 改为 `ratio=0.5`

## 5. 验收

- [x] 5.1 `openspec validate axis-baseline-two-sides --strict` 通过
- [x] 5.2 **归档前**跑 `openspec validate --all --strict`
- [x] 5.3 全量测试通过
  - **实测**：1626 passed, 3 skipped
- [x] 5.4 `run_all()` 数字不变（`sample 19/27`、`billing 23/27`）
- [x] 5.5 归档

## 6. 不在本变更范围

- **不造 v3 数据**
- **不改 `axis_baseline()`**：v2 口径保留
- **不改 `F24` 的 v2 分支**：它的"不满分"语义仍然正确

