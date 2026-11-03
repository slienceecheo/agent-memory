## Why

**v3 数据造出来后，门禁读不到它——造数据这一步会是白做。**

实测（`tmp_path` 造 v3 签名产物，两种放法）：

| 情形 | F20 | F24 |
|---|---|---|
| **放 `results/v3/`（spec 规定）** | 失败："没有覆盖本数据集的消融结果" | **`passed=True`**（"未跑"算通过） |
| **放顶层 + 改名 `v2-`** | 通过（`drop=+0.0000`，v3 分支正确执行） | 失败（真的执行了） |

**违反分区反而能读到，遵守分区反而读不到。**

原因是两条门禁的文件发现路径写死：

```python
# F20 (check_v2_dataset.py:974)
candidates = sorted(ROOT.joinpath("results").glob("v2-*-condition-ablation.json"))

# F24 (check_v2_dataset.py:1182)
for path in sorted((ROOT / "results").glob("v2-*-lexical-vector-adjacency.json")):
```

**顶层 + `v2-` 前缀**，两个条件都写死。而 spec 规定 v3 产物放 `results/v3/`
（`evaluation-harness` 的「结果产物的分区」）。

**两条规格说的是两个互不相通的位置**：产物按 `results/v3/` 放，门禁按顶层 `v2-*.json` 找。

**第二条：`F24` 把"没找到文件"算成了通过。**

```python
result_side_note = "未跑（无结果文件）"
result_side_problem = None            # <- 没有文件时不设 problem
passed = data_side_problem is None and result_side_problem is None
```

于是 `passed=True`。而 `F20` 对同一情形返回 `passed=False`。

**同一个"没找到文件"，一条判失败、一条判通过。**

**这是第 4 类状态被压成前 3 类**：

| 状态 | `applicable` | `passed` | 含义 |
|---|---|---|---|
| 执行且通过 | True | True | 门禁跑了，判据成立 |
| 执行且失败 | True | False | 门禁跑了，判据不成立 |
| 不适用 | False | False | 跨装置 |
| **找不到文件** | **True** | **False（F20）/ True（F24）** | **门禁没跑** |

**第 4 行比"不适用"更危险**：不适用至少有 `applicable=False` 这个标记，
而"找不到文件"伪装成"执行过"。

## What Changes

**1. 文件发现改为扫所有分区，不按文件名前缀**

```python
def _result_files(pattern: str) -> list[Path]:
    """扫 results/ 顶层与所有已登记分区。"""
    candidates = list(RESULTS.glob(pattern))
    for zone in ("v3",):                      # 未来加 features 等
        candidates.extend((RESULTS / zone).glob(pattern))
    return sorted(candidates)
```

**判装置靠 `apparatus_signature`，不靠文件名前缀。**
文件名前缀是 v2 时代的约定，不该成为"能不能被发现"的条件。

**2. "找不到文件"必须显式区分三件事**

| 情形 | 应有结果 |
|---|---|
| `results/v3/` **为空**（v3 尚无产物） | `applicable=False`，说明"v3 尚无产物" |
| 有文件但**不匹配本数据集** | `passed=False`（配置错） |
| 有匹配文件 | 执行判据 |

**关键**：前两种 MUST NOT 是 `passed=True`。
"没数据"与"数据放错地方"是两件事，现在被压成了同一句。

**3. `F24` 的"未跑"不能再算通过**

`passed = data_side_problem is None and result_side_problem is None`
这个式子里，"没找到文件"与"找到了且没问题"都是 `None`。
必须显式区分。

## Impact

- 代码：`evals/tools/check_v2_dataset.py`（`_result_files` 辅助、`F20`/`F24` 的文件发现与无文件分支）
- 测试：新增 `test_gate_discovers_zone_products.py`
- 数据 / 结果文件：**无**
- **`run_all()` 数字**：`F24` 在真实 v2 数据上**不变**（仍不适用，因为读到了顶层 v2 文件）

## 验收

| # | 判据 | 可被违反的形式 |
|---|---|---|
| 1 | `results/v3/*.json` 里放 v3 签名的产物 | `F20` **找到并执行**（`drop==0`） |
| 2 | v3 分区为空 | `F20`/`F24` 都是 `applicable=False`，**MUST NOT 是 `passed=True`** |
| 3 | 顶层 v2 文件 | 仍不适用（现有行为不破） |
| 4 | 有文件但不匹配本数据集 | `passed=False` 且 detail 说明是配置问题，不是"没有产物" |
| 5 | `F24` 在无任何结果文件时 | **`passed=False` 或 `applicable=False`**，MUST NOT `passed=True` |

**验收 5 是本次最重要的自检**：没有它，"没找到文件"会继续伪装成通过。

## 不做的事

- **不造 v3 数据**：本变更只让门禁"能看见"，不产出数据
- **不给 `F24` 造 v3 判据**：需要 v3 数据才能定阈值，接在下一步
- **不改分区规格**：`results/v3/` 的位置不变，改的是"谁来读它"
