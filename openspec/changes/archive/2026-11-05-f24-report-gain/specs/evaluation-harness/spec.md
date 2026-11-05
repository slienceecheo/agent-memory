## ADDED Requirements

### Requirement: `F24` 报告增益大小，不得设目标区间

`F24` 在 v3 下的结果侧 detail MUST 同时写出实测值、派生基线、以及两者的差。
MUST NOT 引入"目标区间"（如 `0.5 < ratio < 0.9`）。

#### Scenario: detail 必须能直接读出增益

- **WHEN** `F24` 的结果侧执行了
- **THEN** detail MUST 含 `实测 <hit>/<n>=<ratio>`
- **AND** MUST 含 `派生 within 基线 <baseline>`
- **AND** MUST 含 `差 <gain:+.4f>`

**为什么三个都要**：只报 `ratio` 时，"等于基线"与"远高于基线"
会写成一模一样的句子——那是两条相反的结论。

**实测**（v3 装置跑 v2 数据）：

| subject | baseline | ratio | 差 |
|---|---|---|---|
| `sample` | 0.3000 | 0.3000 | **+0.0000** |
| `billing` | 0.2778 | 0.0833 | **−0.1944** |

`sample` 的差为 0 是**结论**，不是"数据缺了基线"。
若 detail 只写 `ratio=0.3000`，读者无法把它与基线 0.3000 联系起来。

#### Scenario: 失败时也必须报增益

- **WHEN** `F24` 的结果侧判红（高于上限或低于基线）
- **THEN** detail MUST 仍然含差额

**为什么**："太容易"时的差值是 `+0.7222`——那是**数据有多容易**的量化。
只在通过时报，红的时候读者仍要手算。

#### Scenario: 负差值的负号必须保留

- **WHEN** `ratio < baseline`
- **THEN** detail MUST 写成 `差 -0.1944`，MUST NOT 写成 `差 0.1944`

**为什么**：`−` 与 `+` 是两条相反的结论（排序比随机差 vs 好）。
格式化必须用 `+.4f`（带符号），不能用 `.4f`。

#### Scenario: 不得引入目标区间

- **WHEN** 有人想"让这条门禁更严格"
- **THEN** MUST NOT 加 `target_low` / `target_high` / `TARGET_*` 之类的常量
- **AND** 该禁止 MUST 有断言守着

**为什么定区间会诱导改数据**：

| 做法 | 后果 |
|---|---|
| 定 `0.5 < ratio < 0.9` | 造数据时为让 ratio 落进区间而调难度 —— 为达标回头改数据 |
| 先造出来再看 | ratio 落进哪里都接受 —— 上限 `0.9999` 失去约束力 |

**报告差值不会诱导改数据**：它不判"落在哪"，只陈述"增益多少"。

#### Scenario: 这条限制本身必须可被违反

- **WHEN** 在 `F24` 的函数体里加 `TARGET_LOW = 0.5`
- **THEN** `test_f24_has_no_target_range` MUST 红

**为什么需要**：否则"不得设区间"只是一句话。
断言读的是 `F24` 函数体的源码文本，`TARGET_` 任一出现即红。
