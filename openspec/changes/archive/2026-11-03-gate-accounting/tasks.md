# Tasks

## 0. 为什么要有这个变更

**"不适用"被算进"失败"，而结果文件丢了 `applicable` 字段。**

| 量 | 值 |
|---|---|
| `billing` 的 `run_all` 条数 | 27 |
| `passed=True` | 23 |
| `applicable=False` | 2（`F20`、`F24`） |
| 旧 `main` 报的 `failed` | **4**（含那 2 条不适用的） |
| 屏幕上 | `通过 23/27` |

**而 `--json` 不写 `applicable`**——结果文件无法复算这个区别。

**另有一条会崩的代码**：`F24` 在"派生 within 为空"时
`return Check(..., passed=True, applicable=False)`，而 `Check.__post_init__` 拒绝该组合。
实测（`sample` 全 relation 改唯一）：

```
派生 within: 0
ValueError: F24: applicable=False 时 passed 必须为 False
```

## 1. `--json` 写入 `applicable`（TDD）

- [x] 1.1 写失败测试：`--json` 的每条 check 必须含 `applicable` 字段
  - 验证：`pytest -k json_has_applicable` 先红

- [x] 1.2 实现：payload 里加 `"applicable": r.applicable`
  - 验证：1.1 转绿

- [x] 1.3 写测试：从 JSON 复算的三态与 `run_all()` 一致
  - 取真实 v2 数据，跑 `--json`，读回，与内存结果比对
  - 验证：`pytest -k json_roundtrip_matches`

## 2. `main()` 报三元组

- [x] 2.1 写失败测试：输出必须含三个分开的数
  - 断言 `"不适用"` 与 `"未通过"` 是分开的
  - 验证：`pytest -k main_reports_three_counts`

- [x] 2.2 实现：`passed / na / failed` 三个列表
  - `na = [r for r in results if not r.applicable]`
  - `failed = [r for r in results if r.applicable and not r.passed]`
  - 验证：2.1 转绿

- [x] 2.3 写测试：`na` 与 `failed` **不相交**
  - 这是核心：一条结果不能同时算两处
  - 验证：`pytest -k na_and_failed_are_disjoint`

## 3. `F24` 空派生 within

- [x] 3.1 写失败测试：全单值数据集上 `F24` **返回 Check 而非抛异常**
  - 构造：`dataclasses.replace` 把每条 memory 的 relation 改成唯一值
  - 验证：`pytest -k f24_handles_no_derived_within` 先红（现在是 `ValueError`）

- [x] 3.2 实现：`passed=False, applicable=True`，detail 写"无派生 within 查询"
  - **不是 `applicable=False`**：装置是对的，是数据形状的问题
  - 验证：3.1 转绿

- [x] 3.3 写测试：该分支的 `applicable` 必须是 True
  - 与"跨装置"的 `applicable=False` 区分开
  - 验证：`pytest -k no_subject_is_not_cross_apparatus`

## 4. 数字与文档

- [x] 4.1 实测 `main()` 的新输出，记录三个数
  - 期望：`ledger 通过 19 / 不适用 2 / 未通过 6`
  - `billing 通过 23 / 不适用 2 / 未通过 2`
- [x] 4.2 更新 HANDOFF：`19/27` -> 写成三态
- [x] 4.3 更新 `test_handoff_current` 与 `test_v2_sample_layers` 的断言

## 5. 验收

- [x] 5.1 `openspec validate gate-accounting --strict` 通过
- [x] 5.2 **归档前**跑 `openspec validate --all --strict`
- [x] 5.3 全量测试通过
- [x] 5.4 归档

## 6. 不在本变更范围

- **不把 `applicable` 改枚举**：B + 数据约束已覆盖当前已知形状
- **不造 v3 数据**：但 v3 数据约束里要加"每 subject 至少 1 条派生 within"
- **不改 `passed` 数的算法**：19 / 23 不变


