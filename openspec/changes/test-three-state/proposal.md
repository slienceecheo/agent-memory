## Why

**上一轮修好了 `main()` 与 `--json` 的三态，但有两条测试仍在用旧判据。**

**第一条：`test_every_failing_gate_is_classified` 把"不适用"当成"失败"。**

```python
failed |= {r.code for r in run_all(...) if not r.passed}
```

实测两个判据抓到的集合不同：

| subject | 旧判据（`not passed`） | 新判据（`applicable and not passed`） | 差值 |
|---|---|---|---|
| `sample` | `F13 F17b F18 F20 F21a F21b F24 F6` | `F13 F17b F18 F21a F21b F6` | **`F20`、`F24`** |
| `billing` | `F20 F21b F24 F6` | `F21b F6` | **`F20`、`F24`** |

**这条测试之前之所以没红，是因为 `F20`/`F24` 这两个字符串恰好出现在 HANDOFF 别处**
（就在我上一轮解释"不适用不算失败"的那段文字里）。

**这正是"断言总能通过"的形态**：它声称在检查"未通过项已被分类"，
实际检查的是"这个 code 在文档里出现过"。

**第二条：`test_accepted_failures` 的语义边界没写明。**

它读的是**冻结文件**（`v2-*-gates.json`，`47e4785-dirty`），所以验的是
"v2 装置下失败"，不是"现在失败"。而当前代码是 v3 装置：

| 来源 | `F20` / `F24` |
|---|---|
| 冻结文件（v2 装置） | `sample`：**都通过**；`billing`：`F20` 通过、`F24` 失败 |
| 当前 `run_all()`（v3 装置） | 都 `applicable=False` |

**两处都不算"互相矛盾"**——装置变了，适用性也变了。但测试名
`test_accepted_failure_actually_fails` 会让人以为它验的是"现在"。

顺带一处不准确：`ACCEPTED_FAILURES["F24"]` 只写"billing A 轴 SEH@1 = 1.0000"，
而 `sample` 的 `F24` 在冻结文件里是**通过**——描述没写清范围。

## What Changes

**1. `test_every_failing_gate_is_classified` 的判据改为 `applicable and not passed`**

**2. `test_accepted_failure_actually_fails` 改名为
`test_accepted_failure_failed_in_v2_apparatus`**

docstring 写明：**本测试读冻结文件，验的是 v2 装置下的失败；
当前装置下 `F20`/`F24` 是"不适用"，不是"失败"。**

**3. `ACCEPTED_FAILURES["F24"]` 的描述补上范围**

`"正确的失败：**billing** A 轴 SEH@1 = 1.0000（sample 上是通过）"`

## Impact

- 代码：**无**
- 测试：`test_handoff_current.py`（1 条判据）、`test_accepted_failures.py`（改名 + 描述）
- 数据 / 结果文件：**无**
- **`run_all()` 数字不变**

## 验收

| # | 判据 | 可被违反的形式 |
|---|---|---|
| 1 | 旧判据与新判据抓到的集合**必须不同** | 若相同，说明这条修复没有对象 |
| 2 | 从 HANDOFF 删掉一条**真失败**（`F17b`） | 测试必须**红** |
| 3 | 从 HANDOFF 删掉一条**不适用**（`F20`） | 测试**不得红**（它不属于未通过项） |
| 4 | 冻结文件与当前代码的 `F20`/`F24` 差异被写明 | 否则读者以为两处矛盾 |

**验收 2 与 3 是本变更的核心**：它们同时验证"抓得到真失败"与"不误抓不适用"。
