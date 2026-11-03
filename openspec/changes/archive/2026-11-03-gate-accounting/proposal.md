## Why

**"不适用"在门禁账里被算进了"失败"，而结果文件也丢掉了 `applicable` 字段。**

两处实测：

```python
# main()
failed = [r for r in results if not r.passed]      # <- 不适用也是 not passed
print(f"通过 {len(results) - len(failed)}/{len(results)}")

# --json
{"checks": [{"code": ..., "title": ..., "passed": ..., "detail": ...}]}   # 无 applicable
```

**后果**：

| 量 | 值 |
|---|---|
| `billing` 的 `run_all` 条数 | 27 |
| `passed=True` | **23** |
| `applicable=False` | **2**（`F20`、`F24`） |
| `main` 报的 `failed` | **4**（`F6`、`F20`、`F21b`、`F24`） |
| 屏幕上 | `通过 23/27` |

**"23/27" 里，2 条是"不适用"、2 条是"真失败"，被压成同一个单元格。**

而 `--json` 不写 `applicable`，所以**一份门禁结果文件无法区分这两种 false**。
HANDOFF 里记的 `21/27`、`24/27`，从结果文件复算时会把两者算成一样。

**第三条：`F24` 在"派生 within 为空"时会抛未捕获的 `ValueError`。**

```python
if baseline_value is None:
    return Check("F24", ..., True, "...", applicable=False)   # passed=True + applicable=False
```

`Check.__post_init__` 拒绝这个组合。实测（把 `sample` 的所有 relation 改成唯一值）：

```
派生 within 条数: 0
派生基线: {'relation_within': None, 'relation_cross': 0.8472222222222222}
抛出 ValueError: F24: applicable=False 时 passed 必须为 False
```

**而"一个 subject 全单值 relation"是 v3 的合法数据形状**：
约束是 `relation 数 ∈ [2,3]` 且"至少 1 个单值 relation"，
而"2 个单值 relation"完全满足——那时派生 within 为空，`F24` 崩溃。

**`run_all()` 会因此整体崩掉，而不是报一条门禁失败。**

## What Changes

**1. `--json` 写入 `applicable`**

```python
{"code": ..., "title": ..., "passed": ..., "applicable": ..., "detail": ...}
```

没有它，结果文件无法区分"不适用"与"失败"。

**2. `main()` 报三元组**

```
通过 19 / 不适用 2 / 未通过 6  （共 27）
```

**而不是** `通过 19/27`——后者把两种 false 压成一格。

**3. `F24` 的空派生 within 分支改为"失败 + 适用"**

`passed=False, applicable=True`，detail 写明"该 subject 无派生 within 查询"。

**为什么不是 `applicable=False`**：
"不适用"的语义是"跨装置，判据不成立"；
而这里**装置是对的**，只是数据形状让判据没有主语。
用 `applicable=False` 会让两种完全不同的原因混进同一个值。

**4. v3 的数据约束加一条**

> 每个 subject MUST 至少有 1 条派生 within 查询
> （即 `relation 数 >= 2` 且至少 1 个 relation 有 >= 2 条记忆）

**否则 `F24` 会在合法数据上永远红，而那个红无法通过改数据以外的方式消除。**

这条与"至少 1 个单值 relation"可以并存：3 个 relation 时是"1 单值 + 2 多分支"。

## Impact

- 代码：`evals/tools/check_v2_dataset.py`（`--json`、`main()`、`F24` 空轴分支）
- 测试：新增 `test_gate_accounting.py`
- 数据：**无**
- **屏幕输出变化**：`通过 19/27` -> `通过 19 / 不适用 2 / 未通过 6`
- **`run_all()` 的 `passed` 数字不变**（19 / 23），变的只是"如何报它"

## 验收

| # | 判据 | 可被违反的形式 |
|---|---|---|
| 1 | `--json` 每条 check 含 `applicable` | 缺字段则结果文件无法复算三态 |
| 2 | `main()` 输出三个分开的数字 | 只报 `X/27` 则两种 false 混在一起 |
| 3 | **不适用不得计入"未通过"** | 断言 `na` 与 `failed` 不相交 |
| 4 | `F24` 在全单值数据集上**返回 Check 而非抛异常** | 当前会抛 `ValueError` |
| 5 | 该分支的 `passed=False, applicable=True` | 不能是 `applicable=False`（语义不同） |
| 6 | v3 数据约束写明"至少 1 条派生 within" | 否则 F24 在合法数据上永久红 |

**验收 3 是本变更的核心**：它让"不适用"不再伪装成"失败"。
