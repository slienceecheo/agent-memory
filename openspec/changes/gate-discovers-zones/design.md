## 决策 1：按分区扫，不按文件名前缀

**做法**：

```python
def result_files(pattern: str) -> list[Path]:
    out = list(RESULTS.glob(pattern))
    for zone in REGISTERED_ZONES:        # {"", "v3", ...}
        if zone:
            out.extend((RESULTS / zone).glob(pattern))
    return sorted(out)
```

**为什么不改成 `rglob`**：`rglob` 会扫到 `results/archive/`（历史对照物），
那是**故意不参与**的分区。按清单扫，范围是显式的。

**为什么保留 `pattern` 而不是全扫**：`F20` 只关心 `*condition-ablation.json`，
`F24` 只关心 `*lexical-vector-adjacency.json`。全扫会让它们读到彼此的文件。

**文件名前缀不再是发现条件**：`v2-` 是 v2 时代的命名约定。
v3 产物如果叫 `v3-sample-...`，按 `v2-*` glob 永远匹配不到——
**这就是本变更要修的**。

装置归属改由 `apparatus_signature` 判断（已在上一个变更接好）。

## 决策 2："找不到文件"拆成三态，而不是压成一态

**现状**：

| 门禁 | 无文件时 | `passed` |
|---|---|---|
| `F20` | `"没有覆盖本数据集的消融结果"` | False |
| `F24` | `"[结果侧未跑] 未跑（无结果文件）"` | **True** |

**两者方向相反**，而 `passed=True` 那条让"门禁没跑"伪装成"执行过"。

**改法**：

| 情形 | `applicable` | `passed` | detail |
|---|---|---|---|
| 目标分区为空 | False | False | "v3 尚无产物" |
| 有文件但不匹配本数据集 | True | False | "找到 N 个文件，但都不含本数据集的查询" |
| 有匹配文件 | 执行 | 执行 | —— |

**"分区为空"判 `applicable=False` 而不是 `passed=False`**：
"这代还没数据"不是失败，是"不适用"。而"有文件但配错了"才是失败。

**这个区分让两个不同的原因指向不同的处置**：
- 无数据 -> 去造数据
- 配错了 -> 去查路径/数据集

现在两者都被压成一句话，人只能猜。

## 决策 3：`F24` 的 `passed` 表达式必须重写

**现状**：

```python
result_side_note = "未跑（无结果文件）"
result_side_problem = None
passed = data_side_problem is None and result_side_problem is None
```

"没找到文件"与"找到了且没问题"都是 `None`，所以前者也 `passed=True`。

**改法**：引入显式的 `result_side_ran: bool`。

```python
passed = (
    data_side_problem is None
    and result_side_ran          # <- 新增：结果侧真的跑了
    and result_side_problem is None
)
```

**为什么不用"detail 里有没有'未跑'"判断**：那是字符串匹配，
`detail` 一改写就失效。用布尔量表达"跑了没有"，与文案解耦。

## 决策 4：`REGISTERED_ZONES` 复用已有的分区清单

`test_results_zones.py` 已有 `ZONES`（`.`, `v3`, `archive`, `features`）。

**但不直接 import 测试模块**：生产代码不该依赖测试。
在 `check_v2_dataset.py` 里定一份自己的清单，并**加一条测试断言两者一致**。

**为什么**：两份清单会漂移，而"门禁扫的分区"与"测试认的分区"必须是同一份。
测试断言一致，漂移会立刻红。

## Risks / Trade-offs

| 风险 | 缓解 |
|---|---|
| 扫到 `archive/` 导致读到不该读的 | 清单里不含 `archive`，且测试断言 |
| 两份分区清单漂移 | 加测试断言一致 |
| `F24` 的 `passed` 语义变化影响既有测试 | 真实 v2 数据上它仍不适用（读取顶层 v2 文件），数字不变 |
| v3 分区里放了不匹配的文件 | 归入"有文件但不匹配" -> `passed=False`，不是静默通过 |

## 不做的事

- **不造 v3 数据**：本变更只让门禁能看见
- **不给 `F24` 造 v3 判据**：需要 v3 数据定阈值，接在下一步
- **不改分区位置**：`results/v3/` 不变
