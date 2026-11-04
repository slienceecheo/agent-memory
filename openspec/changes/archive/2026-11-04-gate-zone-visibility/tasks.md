# Tasks

## 0. 为什么要有这个变更

**"造完 v3 数据谁来验"的答案是 3 条，不是 6/7 条。**

| 门禁 | 发现方式 | 能看到 `results/v3/` |
|---|---|---|
| L6a / L6b / L6c / L8 | 写死 v2 文件名 | ❌ |
| F19b / F20 / F24 | `result_files()` | ✅ |

前 4 条看不到 v3 **是适用域不是遗漏**，但没登记，所以读者会以为都在验。

## 1. 修 `_ablation_for_subjects` 的遮蔽缺陷

- [x] 1.1 优先返回签名等于 `CURRENT_APPARATUS` 的产物
  - 无当前装置产物时回落第一个（保持旧行为）
  - 验证：`_ablation_for_subjects` 返回 `sig == "v3"`、`source` 以 `v3-` 开头

- [x] 1.2 证伪：放 v3 消融产物，`F20` 的结论必须改变
  - 修前：`(False, False)`（被 v2 遮蔽）
  - 修后：`(True, True)`，detail 含 `drop=+0.0000`
  - **已做**，两个方向都确认

  **注意证伪判据**：不能是"`result_files()` 返回值里包含 v3"。
  实测过 `result_files` 返回了 v3 而 `_ablation_for_subjects` 仍选 v2——
  **"能发现文件"与"用了那个文件"是两件事**。

## 2. 修登记表：补 `L6a`（6 -> 7）

- [x] 2.1 `RESULT_SIDE_GATES` 补 `L6a`
- [x] 2.2 计数断言 6 -> 7，并拆成三组（7 / 4 / 3）

## 3. 修登记表：两处写错的文件

- [x] 3.1 `L6b`：`a3-with-dedup.json` -> `a3-lexical-vector-adjacency.json`
  - 它读 `THREE_PATH_RUN`，与 `L6a` 同一个文件

- [x] 3.2 `F24`：`v2-*-lexical-vector-adjacency.json` -> `*-lexical-vector-adjacency.json`
  - **后果最重**：带 `v2-` 前缀时，v3 产物不会被这条登记检查，
    "有人重跑就自动失效"的机制对 v3 不触发
  - 实测：旧方式 `glob("v2-*")` 找到 2 个且看不到 v3；
    新方式 `result_files("*")` 找到 4 个且看到 v3

## 4. 新增 `test_registry_matches_implementation`

- [x] 4.1 AST 派生每条门禁实际读什么（递归跟进模块内 helper）
- [x] 4.2 与登记逐条比对，**含空集**（登记不能只增不减）
- [x] 4.3 分组比对：写死路径族、发现式族

- [x] 4.4 双向证伪（5 个方向全部符合预期）

  | # | 构造 | 期望 | 实测 |
  |---|---|---|---|
  | A1 | `L6b` 登记改回 `a3-with-dedup.json` | 红 | 红 |
  | A2 | 删掉 `L6a` 登记 | 红 | 红 |
  | A3 | `F24` 加回 `v2-` 前缀 | 红 | 红 |
  | B1 | 把 `L1`（不读文件）塞进登记 | 红 | 红 |
  | B2 | `L6a` 从写死组挪到发现组 | 红 | 红 |

  **A 是"删真失败要红"，B 是"加不适用项也要红"**——
  后者防的是"登记表变成只增不减的清单"。

## 5. 新增 `tests/retrieval/test_gate_zone_visibility.py`

- [x] 5.1 `test_v3_product_is_not_shadowed_by_v2`
  - 判据：放 v3 产物后 `F20` 的 `(applicable, passed)` 改变
  - 断言 `(True, True)`，不是"至少没报错"

- [x] 5.2 `test_ablation_picks_current_apparatus_first`
  - 判据：选中的签名 == `CURRENT_APPARATUS`

- [x] 5.3 `test_fixed_path_gates_are_blind_to_v3`
  - 判据：放 v3 产物后 `L6a`/`L6b`/`L6c`/`L8` 的结论**完全不变**
  - 这是"它们不看 v3"的可执行证据

- [x] 5.4 `test_v3_aware_gates_are_exactly_three`
  - 判据：走 `result_files()` 或 `_ablation_for_subjects` 的门禁**恰好 3 条**
  - 从 `ALL_CHECKS` 的源码体派生，不是凭印象列
  - **跳过 docstring**：否则"提过"会被当成"用了"
  - **取代号保留大小写**：`f19b` -> `F19b`（`.upper()` 会给 `F19B`）

## 6. HANDOFF 的"谁来验"必须被断言守住

- [x] 6.1 HANDOFF §0 写清 7 条读文件、3 条能看到 v3、4 条写死
- [x] 6.2 新增 `test_handoff_gate_counts_are_derivable`
  - 判据：文档里的三个数字 == `_derive_reads()` 的派生结果
  - 不是"文档里有这几个数字"，是"数字 == 派生值"

- [x] 6.3 双向证伪

  | # | 构造 | 期望 | 实测 |
  |---|---|---|---|
  | A1 | 文档 `7 条` -> `6 条` | 红 | 红 |
  | A2 | 文档 `3 条能看到` -> `4 条` | 红 | 红 |
  | A3 | 文档 `其余 4 条` -> `5 条` | 红 | 红 |
  | B1 | 给 `L6a` 接上 `result_files()`（结构变化） | 红 | 红（"派生 4 条能看到 v3"） |

  **B1 是这条断言存在的理由**：谁给 `L6a` 接上 `result_files()`，
  文档里"只有 3 条"立刻变成错的，而 27 条门禁照常全绿。

## 7. 验收

- [x] 7.1 `openspec validate gate-zone-visibility --strict` 通过
- [x] 7.2 全量测试：`1643 passed, 3 skipped`（本变更前 1637 + 6 新增）
- [x] 7.3 `ruff` / `mypy` 干净
- [x] 7.4 **归档前**跑 `openspec validate --all --strict`
- [x] 7.5 归档

## 8. 不在本变更范围

- **不改 `_load_run` 的三态**：现在"缺文件 -> 失败"，改成"不适用"会改
  4 条门禁的行为，是另一个决策
- **不造 v3 数据**
- **不改 `apparatus_signature` 的判据**

