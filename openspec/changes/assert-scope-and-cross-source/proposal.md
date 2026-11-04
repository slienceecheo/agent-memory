## Why

**上一轮把 A 类断言改成读 `compute()`，但其中两条不限定范围，于是会互相顶替。**

HANDOFF 里 `| **合计** | **N** |` 出现三次：

| 行号 | 内容 | 属于哪一节 |
|---|---|---|
| 297 | `| **合计** | **214** |` | §0.6 MUST/SHALL 行表 |
| 387 | `| **合计** | **287** |` | Scenario 表 |
| 2622 | `| **合计** | **55** |` | 要求数 |

而两条断言都**扫全文**：

```python
# test_scenario_count_is_real
assert f"| **合计** | **{total}** |" in text        # total = 287

# test_must_coverage_numbers_are_real
assert f"| **合计** | **{total}** |" in text        # total = 214
```

**它们现在通过，只因为 287 ≠ 214。**

**实测确认这个缺陷**（构造：Scenario 真值 220 / 文档写 219，MUST 真值 220 / 文档写 220）：

```
test_scenario_count_is_real -> **通过**
```

**Scenario 表写错了，但断言因为 MUST 表的 220 而通过。**

这正是本项目反复防的形态：**同一个字符串在两个位置有不同含义**。
上一轮已经为 `1.2%` 处理过一次（`test_section_0_6_distinguishes_the_two_1_2_percent`），
同样的问题在"合计"上存在，只是数字不同所以没暴露。

**第二条：`has_fn` 与 `MANUAL_SYMBOL_EXISTS_ROWS` 是两个来源。**

| 量 | 来源 | 值 |
|---|---|---|
| `four_way.has_fn.n` | **扫描 spec 算出** | 1 |
| `MANUAL_SYMBOL_EXISTS_ROWS` | **手写常量** | 1 |

它们本来是同一个量（"有函数名的行" = "exists 能覆盖的行"），但**没有断言保证它们相等**。
若 spec 新增"实现 foo"，`has_fn` 变 2 而常量仍 1，两处数字不一致而无人发现。

**第三条：`test_recount_script_matches_reality` 打印污染。**

```python
assert mod.main() == 0
```

`main()` 会把整份报告打印到 stdout，在 pytest 里污染输出（`-q` 下看不出来——
**而那正是问题**）。而且它只证明"函数没抛异常"，不证明"算出了东西"。

## What Changes

**1. 两条合计断言加 scope**

| 断言 | 新 scope |
|---|---|
| `test_scenario_count_is_real` | `text.split("真正该看的数字：")[1].split("\n### ")[0]` |
| `test_must_coverage_numbers_are_real` | `text.split("### 0.6 自动检查的边界")[1].split("### 0.7")[0]` |

**2. 新增交叉断言：`has_fn` 必须等于 `MANUAL_SYMBOL_EXISTS_ROWS`**

**3. `test_recount_script_matches_reality` 改为读 `compute()`**

判据从 `main() == 0` 改成"`compute()` 返回非空 + 四类之和 == 总数"。

## Impact

- 代码：**无**
- 测试：`test_handoff_v3_method.py`（2 处 scope、1 条新断言、1 条重写）
- 数据 / 结果文件：**无**

## 验收

| # | 判据 | 可被违反的形式 |
|---|---|---|
| 1 | 构造"Scenario 真值 220 / 文档 219 / MUST 真值 220 / 文档 220" | `test_scenario_count_is_real` **必须红** |
| 2 | 同上构造，加 scope 前 | 该测试**通过**（已被证伪确认） |
| 3 | `has_fn != MANUAL_SYMBOL_EXISTS_ROWS` | 交叉断言**必须红** |
| 4 | `test_recount_script_matches_reality` 在 `-s` 下 | **无 stdout 输出** |
| 5 | 四类之和 != 合计 | **必须红**（`compute()` 内部一致性） |

**验收 1 与 2 是同一次证伪的两面**：修之前通过（缺陷），修之后红（正确）。
