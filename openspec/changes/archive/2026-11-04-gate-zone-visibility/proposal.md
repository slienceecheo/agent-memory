## Why

**上一轮问"造完 v3 数据后谁来验"，读代码得出的答案是错的。**

实测 27 条门禁里 **7 条读 `results/`**，其中只有 **3 条**能看到 `results/v3/`：

| 门禁 | 发现方式 | 能看到 `results/v3/` |
|---|---|---|
| `L6a` | `_load_run(THREE_PATH_RUN)` 写死 | ❌ |
| `L6b` | 同上 | ❌ |
| `L6c` | 直接拼 `ROOT/"results"/"a3-..."` | ❌ |
| `L8` | `_load_run(DEDUP_RUN)` 写死 | ❌ |
| `F19b` | `_ablation_for_subjects` -> `result_files` | ✅ |
| `F20` | 同上 | ✅ |
| `F24` | `result_files` | ✅ |

前 4 条看不到 v3 **是合理的**（判据不依赖排序装置），但这件事没有登记，
于是"造完数据谁来验"的答案被读成 6 条、7 条，而真实答案是 3 条。

## 三个实测出来的缺陷

### 缺陷 1：v3 产物被 v2 产物遮蔽（已修）

```
result_files("*-condition-ablation.json") 同时返回：
  results/v2-sample-condition-ablation.json
  results/v3/v3-sample-condition-ablation.json

旧实现 for path in candidates：取第一个匹配的 -> 拿到 v2
  -> 判"由 v2 装置产物，当前为 v3" -> F20 不适用
```

**v3 数据完整、文件名正确，F20 仍然不执行。**

修法：优先返回签名等于 `CURRENT_APPARATUS` 的产物。实测修后
`F20` 执行并断言 `drop=+0.0000`。

**这不是假想的边界**：`sorted()` 让 `v2-` 排在 `v3` 前面，所以只要有 v2 产物，
v3 产物就永远轮不到。而 `results/` 顶层**永远**有 v2 产物。

### 缺陷 2：登记表漏了 `L6a`（已修）

`tests/retrieval/test_result_side_gates.py` 登记 6 条，实际 7 条。
而第 99 行 `assert len(...) == 6` **会阻止修正**——改成 7 就红。

`L6a` 与 `L6b` 读同一个文件，看上去像"已经统计过了"，所以漏了。

### 缺陷 3：登记表写错文件，而且机制对 v3 不触发（已修）

`test_registry_matches_implementation` 证伪时发现登记表本身有两处与源码不符：

| 门禁 | 旧登记 | 代码实际读 |
|---|---|---|
| `L6b` | `a3-with-dedup.json` | `a3-lexical-vector-adjacency.json`（`THREE_PATH_RUN`） |
| `F24` | `v2-*-lexical-vector-adjacency.json` | `*-lexical-vector-adjacency.json` |

**`F24` 那条后果最重**：本文件的设计是"有人重跑那些文件时这条登记自动失效"。
但旧 pattern 带 `v2-` 前缀，而 `result_files()` 已经改成扫 `ZONE_NAMES`——
于是 **v3 产物放进去，这条自动失效机制不触发**：

```
实测（results/v3/v3-sample-lexical-vector-adjacency.json 存在时）：
  旧方式 glob("v2-*-lexical-vector-adjacency.json") -> 2 个，看不到 v3
  新方式 result_files("*-lexical-vector-adjacency.json") -> 4 个，看到 v3
```

登记表看着在守，实际守的是旧名字。

## What Changes

**1. `_ablation_for_subjects` 优先选当前装置的产物**

**2. `test_result_side_gates.py` 重写为"登记 + 从源码派生比对"**

- 补 `L6a`（6 -> 7）
- 分 `FIXED_PATH_GATES`（4 条）与 `DISCOVERED_GATES`（3 条），因为它们的
  **发现方式**不同，而发现方式决定能否看到 v3
- 新增 `test_registry_matches_implementation`：AST 派生每条门禁实际读什么，
  与登记逐条比对，**含空集**（登记不能只增不减）
- 计数断言改为分别断言 7 / 4 / 3

**3. 新建 `test_gate_zone_visibility.py`**

| 断言 | 抓什么 |
|---|---|
| `test_v3_product_is_not_shadowed_by_v2` | 放 v3 产物后 `F20` 的结论**必须改变** |
| `test_ablation_picks_current_apparatus_first` | 选中的签名 == `CURRENT_APPARATUS` |
| `test_fixed_path_gates_are_blind_to_v3` | 放 v3 产物后那 4 条**结果不变** |
| `test_v3_aware_gates_are_exactly_three` | 走 `result_files()` 的**恰好 3 条** |

## Impact

- 代码：`evals/tools/check_v2_dataset.py`（`_ablation_for_subjects` 的选择顺序）
- 测试：`test_result_side_gates.py`（重写）、`test_gate_zone_visibility.py`（新增）
- 数据 / 结果文件：**无**

## 验收

| # | 判据 | 可被违反的形式 |
|---|---|---|
| 1 | 放 v3 消融产物，`F20` 的 `(applicable, passed)` | 必须从 `(False, False)` 变为 `(True, True)` |
| 2 | `_ablation_for_subjects` 的返回值签名 | 必须 == `CURRENT_APPARATUS`，不是 `v2` |
| 3 | 放 v3 产物后 `L6a`/`L6b`/`L6c`/`L8` 的结论 | **必须完全不变** |
| 4 | 删掉 `L6a` 登记 | `test_registry_matches_implementation` **必须红** |
| 5 | `L6b` 登记改回 `a3-with-dedup.json` | 同上**必须红** |
| 6 | `F24` 登记加回 `v2-` 前缀 | 同上**必须红** |
| 7 | 把 `L1`（不读文件）塞进登记 | 同上**必须红**（含空集） |
| 8 | `L6a` 从写死组挪到 discovered 组 | 同上**必须红**（发现方式变了） |
| 9 | 限制在 `results/v3/` 的自动失效机制 | 旧 `v2-*` 看不到 v3，新 `*` 看得到 |

**验收 1 与 3 是同一次实验的两面**：前者证明能看见，后者证明另 4 条看不见。
