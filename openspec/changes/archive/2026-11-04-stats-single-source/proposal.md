## Why

**同一个数字在两处以不同形式出现，而它们之间没有结构约束。**

实测十次归档、十次手改统计数字，其中**四次漏改**：

| 漏的地方 | 类型 |
|---|---|
| 142 时的四类分项 | A 类（可算，但当时没脚本） |
| `1.2%` 的两个分母 | B 类 |
| 190 时的 four-way split | A 类 |
| 本轮 198/282 | A 类 |

**根因不是"手工不可靠"，是"三处真相"**：

```
spec（实际内容）  ->  recount_specs.py（算出数）  ->  HANDOFF（写下来）
                                                       ^
                                              测试断言的是这里的字面量
```

测试与文档、脚本都无连接。**所以"脚本算对了但回填漏了"能连续发生四次。**

**更严重的一处**：`recount_specs.py` 里 5 个分子是硬编码的。

```python
print(f"| 符号存在 | 1/{total_must} = {1 / total_must * 100:.1f}% |")
print(f"| 行为符合 | 0/{total_must} = 0.0% |")
print(f"| 人工映射表 | 3/{total_must} = {3 / total_must * 100:.1f}% |")
print(f"| Scenario 分母 | 3/{total_sc} = {3 / total_sc * 100:.1f}% |")
print(f"| MUST 分母 | 1/{total_must} = {1 / total_must * 100:.1f}% |")
```

**只有分母是算的，分子全是字面量。** 若把这 5 行改成"测试读脚本"，
它读的仍是写死的 `1/0/3/3/1`——**看起来自动，实际一半手写**。

**所以数字必须分三类，不能一刀切**：

| 类型 | 例子 | 能否自动化 |
|---|---|---|
| **A. 纯计算** | `282`、`198`、四类细分、合计 | ✅ 完全自动 |
| **B. 分子人工 + 分母计算** | `1/198 = 0.5%`、`3/282 = 1.1%` | ⚠️ **只自动分母** |
| **C. 纯文案** | "本节有两个 1.2%" | ❌ 保留字面 |

## What Changes

**1. `recount_specs.py` 抽出 `compute()`**

现在脚本只有一个 `main()` 打印字符串，**没有可被 import 的数据结构**：

```
ImportError: cannot import name 'compute'
顶层名: ['NORM', 'NORM_ANY', 'Path', 'ROOT', 'SPECS', 'VERB_PATTERN', 'main', 're']
```

**这是接口问题，不是设计问题**——"测试读脚本"现在做不到。

`compute(root=None) -> dict`，`root` 是参数（测试要在临时目录上验证）。

**2. 5 个硬编码分子改成显式命名常量**

```python
MANUAL_SYMBOL_EXISTS_ROWS = 1
MANUAL_BEHAVIOR_VERIFIED_ROWS = 0
MANUAL_MAPPING_ROWS = 3
MANUAL_MAPPED_SCENARIOS = 3
```

**并在 docstring 写明它们为什么不能算**：

| 分子 | 为什么不能算 |
|---|---|
| `1`（符号存在） | 与 `has_fn` 巧合相等，但定义是"能在 src 里 exists" |
| `0`（行为符合） | 人工判定"没有任何测试验证行为" |
| `3`（人工映射表） | 数 HANDOFF 表格行 -> 测试依赖文档 -> 循环 |
| `3`（Scenario 分母） | 人工登记者"有几个 scenario 有映射测试" |

**3. A 类断言改为读 `compute()`**

已改（本变更前两步验证）：

- `test_scenario_count_is_real`
- `test_must_coverage_numbers_are_real`
- `test_section_0_6_has_the_four_way_split`

**判据从"断言字面量"改为"断言 HANDOFF 里写的是 spec 算出的数"**。

**4. B 类与 C 类保留字面，但 MUST 标注来源**

HANDOFF 里那 5 行加"分子来源=人工"的说明；spec 里写明它们不自动化。

## Impact

- 代码：`evals/tools/recount_specs.py`（加 `compute()`、5 个常量）
- 测试：3 条改为读 `compute()`
- 文档：`HANDOFF.md` §0.6 标注 B 类分子来源
- 数据 / 结果文件：**无**

## 验收

| # | 判据 | 可被违反的形式 |
|---|---|---|
| 1 | `from evals.tools.recount_specs import compute` 成功 | **当前 ImportError** |
| 2 | A 类断言读 `compute()` | 断言里仍有 `== 282` 这类字面量 |
| 3 | 改错 HANDOFF 的 Scenario 合计 -> 红 | 已证伪 |
| 4 | 改错四类百分比 -> 红 | 已证伪 |
| 5 | 改错四类合计 -> 红 | 已证伪 |
| 6 | B 类分子是**显式常量**，不是 f-string 里的字面量 | 藏在 `f"...{1}..."` 里读者看不出 |
| 7 | spec 写明三类，并说明 B 类为什么不自动化 | 否则下一个人会试图"自动化"那 5 个分子 |

**验收 6 是本变更的实质**：它把"人工结论"从"隐式的字面量"变成"显式的常量"。
