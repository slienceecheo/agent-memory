# Tasks

## 0. 为什么要有这个变更

上一轮修好了 `main()` / `--json` 的三态，但**两条测试仍在用旧判据**。

| subject | 旧判据（`not passed`） | 新判据（`applicable and not passed`） | 差值 |
|---|---|---|---|
| `sample` | `F13 F17b F18 F20 F21a F21b F24 F6` | `F13 F17b F18 F21a F21b F6` | **F20、F24** |
| `billing` | `F20 F21b F24 F6` | `F21b F6` | **F20、F24** |

**旧测试此前没红，只因 `F20`/`F24` 恰好出现在 HANDOFF 别处的解释文字里**
（就是我上一轮写"不适用不算失败"那段）——**测试被一段解释自己的文字满足了**。

## 1. 修 `test_every_failing_gate_is_classified` 的判据

- [x] 1.1 把 `if not r.passed` 改为 `if r.applicable and not r.passed`
  - 附注释说明这是 `main()` 那个 bug 的同型实例
  - 验证：`pytest tests/retrieval/test_handoff_current.py -q` 通过

- [x] 1.2 证伪（双向）
  - 删 `F17b`（真失败）-> **必须红**
  - 删 `F20`（不适用）-> **必须不红**
  - **已做**：
    ```
    删 F17b -> 红："未通过项 F17b 没在 HANDOFF 里出现"
    删 F20  -> 不红（正确）
    ```

## 2. 修 `test_accepted_failures` 的语义边界

- [x] 2.1 改名：`test_accepted_failure_actually_fails`
      -> `test_accepted_failure_failed_in_v2_apparatus`
  - docstring 写明"本测试读冻结文件，验的是 v2 装置下的失败"
  - 附装置对照表
  - 验证：`pytest tests/retrieval/test_accepted_failures.py -q` 通过

- [x] 2.2 补 `ACCEPTED_FAILURES["F24"]` 的范围
  - 旧：`"正确的失败：billing A 轴 SEH@1 = 1.0000"`
  - 新：`"正确的失败：**billing** A 轴 SEH@1 = 1.0000（sample 上是通过）"`
  - 理由：`sample` 的 `F24` 在冻结文件里是**通过**，旧描述没写清

- [x] 2.3 在 `ACCEPTED_FAILURES` 上方的注释里写明
  - 这份清单读的是冻结的 v2 装置文件
  - 当前 v3 装置下 `F20`/`F24` 是 `applicable=False`，与"失败"无关

## 3. 验收

- [x] 3.1 `openspec validate test-three-state --strict` 通过
- [x] 3.2 **归档前**跑 `openspec validate --all --strict`
- [x] 3.3 全量测试通过
  - **实测**：1634 passed, 3 skipped
- [x] 3.4 `run_all()` 数字不变
- [ ] 3.5 归档

## 4. 不在本变更范围

- **不改 `main()` / `--json`**：上一轮已完成
- **不做"测试读脚本输出"**：范围比预估大——
  13 处断言分三类（单一数字 / 百分比 + 分母 / 章节结构），
  第三类是文案而非数字，不该读脚本。需先分类再决定。
