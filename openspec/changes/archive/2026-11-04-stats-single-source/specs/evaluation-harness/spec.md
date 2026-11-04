## ADDED Requirements

### Requirement: 报告的统计数字必须有单一来源

报告里的统计数字 MUST 由一个可被程序读取的函数产出
（`evals/tools/recount_specs.compute()`），MUST NOT 由测试断言硬编码的字面量。

**测试的判据 MUST 是"文档里写的是 spec 算出的数"**，
MUST NOT 是"文档里写的是测试里的字面量"。

#### Scenario: 测试从 compute() 读值

- **WHEN** 某测试要验证报告里的统计数字
- **THEN** 它 MUST 调 `compute()` 取值，并与**文档内容**比对

- **AND** MUST NOT 在测试里写 `assert total == 282` 这类字面量——
  那会让"文档"与"测试"成为两个真相来源

#### Scenario: 文档写错必须被抓到

- **WHEN** 报告里的某个数字被写错（与 spec 算出的不符）
- **THEN** MUST 有测试变红，且消息指出**期望值与实际值**

- **AND** 该判据 MUST 经过证伪：改错 Scenario 合计、改错四类百分比、
  改错四类合计，三种都必须红

#### Scenario: 数字必须分三类，不得一刀切

- **WHEN** 把统计数字改成"自动读取"
- **THEN** MUST 按下表分类处理：

  | 类型 | 特征 | 处置 |
  |---|---|---|
  | **A. 纯计算** | 分子与分母都能从 spec 算出 | 读 `compute()` |
  | **B. 分子人工 + 分母计算** | 分子是人工结论 | **只自动分母**；分子 MUST 是显式常量 |
  | **C. 纯文案** | 是说明，不是数字 | 保留字面 |

- **AND** MUST NOT 把 B 类当作 A 类处理——那会让"人工结论"伪装成"自动算出"

#### Scenario: B 类的分子必须是显式常量

- **WHEN** 某个统计数字的分子是人工判断的结果
- **THEN** 该分子 MUST 是一个**具名常量**（例如 `MANUAL_MAPPING_ROWS = 3`），
  MUST NOT 是 f-string 里的字面量

- **AND** 具名常量 MUST 带注释说明"为什么它不能算"

**为什么**：实测 `recount_specs.py` 里 5 个分子全是 f-string 里的字面量
（`f"| 符号存在 | 1/{total_must} ..."`）——读者看不出那个 `1` 是人工填的。
把它们改成具名常量之后，"这不是算出来的"变成可见的事实。

- **AND** 实测这些分子不能算的理由：

  | 分子 | 含义 | 为什么不能算 |
  |---|---|---|
  | `1` | "符号存在"= 1 条 | 与 `has_fn` 巧合相等，但定义是"能在 src 里 exists" |
  | `0` | "行为符合"= 0 条 | 人工判定"没有任何测试验证行为" |
  | `3` | "人工映射表"= 3 行 | 数 HANDOFF 表格行 -> 测试依赖文档 -> 循环 |
  | `3` | "Scenario 分母"= 3 | 人工登记者"有几个 scenario 有映射测试" |

#### Scenario: 统计脚本必须可被 import

- **WHEN** 测试需要读统计数字
- **THEN** 脚本 MUST 暴露一个返回结构化数据的函数

- **AND** 该函数 MUST 接受根目录作为**参数**（不是模块常量）——
  否则测试无法在临时目录上验证它

- **AND** 实测：本变更前脚本只有 `main()` 打印字符串，
  `from evals.tools.recount_specs import compute` 抛 `ImportError`
