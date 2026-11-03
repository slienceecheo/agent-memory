# Tasks

## 0. 为什么要有这个变更

**v3 数据造出来后，门禁读不到它。**

实测（`tmp_path` 造 v3 签名产物）：

| 情形 | F20 | F24 |
|---|---|---|
| 放 `results/v3/`（spec 规定） | 失败（找不到） | **`passed=True`** |
| 放顶层 + 改名 `v2-` | 通过 | 失败（真的执行了） |

**违反分区反而能读到，遵守分区反而读不到。**

根因：`glob("v2-*")` 写死顶层 + 前缀。

## 1. 文件发现（TDD）

- [x] 1.1 写失败测试：`results/v3/` 里的 v3 签名产物必须被发现
  - 造 `results/v3/v3-sample-condition-ablation.json`（v3 签名）
  - `F20` 必须**执行**并断言 `drop == 0`
  - 验证：`pytest -k gate_finds_zone_products` 先红

- [x] 1.2 实现 `_result_files(pattern)`：扫顶层 + 已登记分区
  - **不扫 `archive/`**（历史对照物，故意不参与）
  - 验证：1.1 转绿

- [x] 1.3 写测试：`F24` 同样能发现 `results/v3/` 的产物
  - 验证：`pytest -k f24_finds_zone_products`

- [x] 1.4 写测试：已完成分区清单与测试清单一致
  - `check_v2_dataset.ZONE_NAMES` == `test_results_zones.ZONES` 的键（除 `.`）
  - 防两份清单漂移
  - 验证：`pytest -k zone_lists_match`

## 2. "找不到文件"三态

- [x] 2.1 写测试：v3 分区为空时，`F20`/`F24` 都是 `applicable=False`
  - **MUST NOT 是 `passed=True`**
  - 验证：`pytest -k empty_zone_is_not_applicable`

- [x] 2.2 写测试：有文件但不匹配本数据集 -> `passed=False` 且说明是配置问题
  - 造一个只含别的 subject 查询的文件
  - 验证：`pytest -k mismatched_files_are_config_error`

- [x] 2.3 实现：三态分支
  - 空分区 -> `applicable=False`，detail "v3 尚无产物"
  - 不匹配 -> `passed=False`，detail "找到 N 个文件但都不含本数据集查询"
  - 验证：2.1 / 2.2 转绿

## 3. `F24` 的"未跑"不得算通过

- [x] 3.1 写测试：完全没有结果文件时，`F24.passed` MUST 为 False
  - **现状是 `passed=True`**——这是本次最重要的一条
  - 验证：`pytest -k f24_not_run_is_not_passed` 先红

- [x] 3.2 实现：引入 `result_side_ran: bool`
  - `passed = data_side_ok and result_side_ran and no_problem`
  - **不用"detail 里有没有'未跑'"判断**：字符串匹配，一改文案就失效
  - 验证：3.1 转绿

## 4. 既有行为不破

- [x] 4.1 写测试：真实 v2 数据上 `run_all()` 数字不变
  - `sample 19/27`、`billing 23/27`
  - `F20`/`F24` 仍不适用（读到顶层 v2 文件，签名是 v2）
  - 验证：`pytest -k real_data_numbers_unchanged`

- [x] 4.2 验证：顶层 v2 文件仍被正确处理（`apparatus_signature` 判 v2）

## 5. 验收

- [x] 5.1 `openspec validate gate-discovers-zones --strict` 通过
- [x] 5.2 **归档前**跑 `openspec validate --all --strict`
- [x] 5.3 全量测试通过，记录 passed/skipped
- [x] 5.4 更新 HANDOFF：说明门禁现在能发现分区产物
- [x] 5.5 归档

## 6. 不在本变更范围

- `F24` 的 v3 判据（需要 v3 数据定阈值）——接在 v3 数据变更之后
- **不造 v3 数据**：本变更只让门禁"能看见"

