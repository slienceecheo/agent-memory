# Tasks

## 0. 为什么要有这个变更

**三处真相，测试与文档/脚本都无连接。**

```
spec  ->  recount_specs.py  ->  HANDOFF
                                   ^
                          测试断言这里的字面量
```

十次归档、十次手改、**四次漏改**，都是这个结构造成的。

**更严重**：脚本里 5 个分子是硬编码的（`f"...{1}/..."`），
所以"改成读脚本"会让一半手改伪装成自动。

## 1. `compute()` 接口（必须，否则后面做不到）

- [x] 1.1 抽出 `compute(root=None) -> dict`
  - **`root` 是参数**，不是模块常量（本项目踩过两次）
  - 返回 `scenarios` / `must_lines` / `per_capability` / `four_way` /
    `three_layer` / `coverage` / `bare_scenarios_pct` 等
  - 验证：`from evals.tools.recount_specs import compute` 成功

- [x] 1.2 `main()` 改为只负责打印（调 `compute()`）
  - 验证：`uv run --no-sync python evals/tools/recount_specs.py` 输出不变

## 2. 5 个硬编码分子改成显式常量

- [x] 2.1 定义四个具名常量（`SYMBOL_EXISTS` 与 `MUST 分母` 共用同一个）
  ```python
  MANUAL_SYMBOL_EXISTS_ROWS = 1
  MANUAL_BEHAVIOR_VERIFIED_ROWS = 0
  MANUAL_MAPPING_ROWS = 3
  MANUAL_MAPPED_SCENARIOS = 3
  ```
  - 每个都带注释说明"为什么不能算"
  - 验证：`compute()["three_layer"]["symbol_exists"]["numerator"] == 1`

- [x] 2.2 `main()` 打印时从 `compute()` 取分子，不再写 `{1}` / `{0}` / `{3}`
  - 验证：输出与之前逐行一致

## 3. A 类断言改为读 `compute()`

- [x] 3.1 `test_scenario_count_is_real`
  - 旧：从 spec 算出 282，断言 `== 282`
  - 新：`compute()["scenarios"]`，断言 **HANDOFF 里写的是同一个数**
  - 验证：`pytest -k scenario_count_is_real`

- [x] 3.2 `test_must_coverage_numbers_are_real`
  - 同上，用 `compute()["must_lines"]`
  - 验证：`pytest -k must_coverage_numbers_are_real`

- [x] 3.3 `test_section_0_6_has_the_four_way_split`
  - 四个百分比 + 合计都从 `compute()["four_way"]` 取
  - **顺手修了 docstring 里过期的"142"和"1/190"**
  - 验证：`pytest -k four_way_split`

- [x] 3.4 证伪（三种）
  - 改错 Scenario 合计（282 -> 999）-> **红**
  - 改错四类百分比（68.7% -> 99.9%）-> **红**
  - 改错四类合计（198 -> 999）-> **红**
  - **已做**，三种都按预期红

## 4. 文档标注 B 类来源

- [x] 4.1 HANDOFF §0.6 的三层表加说明："分子为人工结论，非算出"
- [x] 4.2 覆盖率那一行同样标注

## 5. 验收

- [x] 5.1 `openspec validate stats-single-source --strict` 通过
- [x] 5.2 **归档前**跑 `openspec validate --all --strict`
- [x] 5.3 全量测试通过
- [ ] 5.4 归档

## 6. 不在本变更范围

- **不自动化 B 类**：分子是人工结论，自动化会让它伪装成算出来的
- **不自动化 C 类**：`assert "本节有两个 1.2%"` 断言的是"必须有这个说明"，
  不是数字
- **不加"同节不允许重复百分比"**：§0.6 里现在每个百分比只出现一次，
  那条断言会恒真；真正防住它的是已写进 HANDOFF 的说明 + 配套测试

