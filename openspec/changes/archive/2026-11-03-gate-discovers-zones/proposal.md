## Why

**v3 数据造出来后，门禁读不到它——造数据这一步会是白做。**

实测（`tmp_path` 造 v3 签名产物）：

| 情形 | F20 | F24 |
|---|---|---|
| **放 `results/v3/`（spec 规定）** | 失败："没有覆盖本数据集的消融结果" | **`passed=True`**（"未跑"算通过） |
| **放顶层 + 改名 `v2-`** | 通过（`drop=+0.0000`） | 失败（真的执行了） |

**违反分区反而能读到，遵守分区反而读不到。**

两条门禁的文件发现路径写死 `glob("v2-*...")`——**顶层 + `v2-` 前缀**，
两个条件都写死。而 spec 规定 v3 产物放 `results/v3/`。
**两条规格说的是两个互不相通的位置。**

**第二条：`F24` 把"没找到文件"算成了通过。**

```python
result_side_problem = None                      # 没有文件时不设 problem
passed = data_side_problem is None and result_side_problem is None
```

**"没找到文件"与"找到了且没问题"都是 `None`**，于是前者 `passed=True`。
而 `F20` 对同一情形返回 `passed=False`。

**同一个"没找到文件"，一条判失败、一条判通过。**

这是第 4 类状态被压成前 3 类。**第 4 行比"不适用"更危险**：
不适用至少有 `applicable=False` 这个标记，而"找不到文件"伪装成"执行过"。

| 状态 | `applicable` | `passed` |
|---|---|---|
| 执行且通过 | True | True |
| 执行且失败 | True | False |
| 不适用 | False | False |
| **找不到文件** | **True** | **False（F20）/ True（F24）** |

## What Changes

**1. 文件发现扫所有已登记分区，不按文件名前缀**

```python
def result_files(pattern):        # pattern 不含版本前缀
    out = list(RESULTS.glob(pattern))
    for zone in ZONE_NAMES:       # ("v3",)，不含 archive
        out.extend((RESULTS / zone).glob(pattern))
    return sorted(out)
```

装置归属由 `apparatus_signature` 判，不由文件名判。

**2. "找不到文件"显式分成三态**

| 情形 | 应有结果 |
|---|---|
| 目标分区**为空** | `applicable=False`，写明"尚无产物" |
| 有文件但**不匹配本数据集** | `passed=False`，写明是配置问题 |
| 有匹配文件 | 执行判据 |

前两种 MUST NOT 是 `passed=True`。"没数据"与"数据放错地方"处置方向相反。

**3. `F24` 的 `passed` 表达式重写**

引入 `result_side_ran: bool`。旧式子把"没跑"与"跑过且没问题"都当 `None`。

## Impact

- 代码：`evals/tools/check_v2_dataset.py`
- 测试：新增 `test_gate_discovers_zones.py`（7 条）；改 1 条既有断言
- 数据 / 结果文件：**无**
- **`run_all()` 数字不变**：`sample 19/27`、`billing 23/27`

## 验收

| # | 判据 |
|---|---|
| 1 | `results/v3/` 的 v3 产物被 `F20` 发现并执行 |
| 2 | v3 分区为空 -> `applicable=False`，MUST NOT `passed=True` |
| 3 | 顶层 v2 文件仍不适用（现有行为不破） |
| 4 | 有文件但不匹配 -> `passed=False`，细节说明是配置问题 |
| 5 | **`F24` 无任何结果文件时 MUST NOT `passed=True`** |

**验收 5 是最重要的自检**：没有它，"没找到文件"会继续伪装成通过。

## 不做的事

- **不造 v3 数据**：本变更只让门禁"能看见"
- **不给 `F24` 造 v3 判据**：需要 v3 数据定阈值，接在下一步
- **不改分区位置**：`results/v3/` 不变，改的是"谁来读它"
