## ADDED Requirements

### Requirement: 门禁的产物来源必须登记且可从源码复算

当门禁读取 `results/` 下的产物时，它读哪个文件、用什么方式发现
MUST 被登记成可执行的事实，MUST NOT 只写在文档或注释里。

**"谁在读文件"必须能从源码复算**：手写的清单会漂移，本项目已实测到三处。

#### Scenario: 登记的读法必须等于源码的读法

- **WHEN** 登记表声明某条门禁读某个文件
- **THEN** MUST 有断言用 AST 从 `check_v2_dataset.py` 派生出该门禁实际读什么
- **AND** 派生的结果 MUST 与登记逐条相等
- **AND** MUST **含空集**：派生说某条不读文件，登记里就不能有它

**为什么不能用"登记的文件都存在"代替**：那只能抓到"文件没了"，抓不到
"登记写的是另一个文件"。实测 `L6b` 登记成 `a3-with-dedup.json`，而它实际读
`a3-lexical-vector-adjacency.json`——两个文件都存在，所以存在性检查全绿。

#### Scenario: 派生必须递归跟进模块内 helper

- **WHEN** 门禁经模块内 helper 间接读文件（`F19b`/`F20` 经 `_ablation_for_subjects`）
- **THEN** 派生 MUST 跟进这些 helper
- **AND** MUST NOT 只看 check 函数体

**为什么**：只看函数体会漏掉 `F19b`/`F20`，而它们恰好是**能看到 v3** 的那一族。

#### Scenario: 发现方式决定能否看到分区，必须分开登记

- **WHEN** 某条门禁用 `_load_run(name)` 或直接拼 `ROOT/"results"/"<name>"` 读文件
- **THEN** 它 MUST 登记在"写死路径"那一族
- **AND** 该族 MUST 被断言为**看不到** `results/<zone>/` 的产物

- **WHEN** 某条门禁用 `result_files(pattern)` 读文件
- **THEN** 它 MUST 登记在"发现式"那一族
- **AND** `pattern` MUST NOT 带装置版本前缀（如 `v2-`）

**为什么前缀是错的**：`result_files()` 扫 `results/` 顶层 + `ZONE_NAMES`，
前缀是装置的事、由 `apparatus_signature` 判断。带 `v2-` 前缀的登记
会在 v3 产物出现时**匹配不到**，于是"有人重跑就自动失效"的机制不触发。
实测：旧方式 `glob("v2-*")` 找到 2 个且看不到 v3；新方式 `result_files("*")`
找到 4 个且看到 v3。

#### Scenario: 门禁数量断言必须分组

- **WHEN** 断言 result-side 门禁的条数
- **THEN** MUST 同时断言总数（7）与两族各自的条数（4 / 3）

**为什么**：只断言总数时，把一条从写死组挪到发现组不会红——
但它的**适用域**完全变了（从"看不到 v3"变成"看得到"）。

### Requirement: 产物选择必须优先当前装置

当同一类产物存在多个装置签名的版本时，门禁 MUST 优先选择签名等于
`CURRENT_APPARATUS` 的那一份，MUST NOT 取"排序后的第一个"。

#### Scenario: 当前装置产物存在时不得被判为跨装置不适用

- **WHEN** `results/` 下同时存在 v2 与 v3 的同类产物
- **THEN** `_ablation_for_subjects` MUST 返回签名等于 `CURRENT_APPARATUS` 的那份
- **AND** 相应门禁 MUST **执行判据**，MUST NOT 报"由 v2 装置产物"

**实测**：旧实现 `for path in candidates` 取第一个匹配的，而 `sorted()` 让
`v2-sample-...` 排在 `v3-sample-...` 前面，于是：
`F20` 拿到 v2 文件 -> 判"跨装置不适用" -> **v3 产物被遮蔽**。

**为什么"排序后的第一个"必然错**：`results/` 顶层永远有 v2 产物，
所以只要有同类 v2 文件，v3 产物就永远轮不到。

#### Scenario: 没有当前装置产物时保持旧行为

- **WHEN** 所有候选产物的签名都不等于 `CURRENT_APPARATUS`
- **THEN** MUST 取第一个匹配的
- **AND** 相应门禁的跨装置判定 MUST 照常生效

**为什么不能改成"没有就报空"**：那会把"这代还没数据"变成"失败"，
与三态语义冲突。

#### Scenario: 遮蔽的证伪必须让结论真的改变

- **WHEN** 验证"v3 产物不被遮蔽"
- **THEN** 判据 MUST 是"放 v3 产物后该门禁的 `(applicable, passed)` 改变了"
- **AND** MUST NOT 是"`result_files()` 的返回值里包含 v3 路径"

**为什么**：`result_files()` 返回了 v3，`_ablation_for_subjects` 仍可能选 v2。
**"能发现文件"与"用了那个文件"是两件事**——实测过前者为真、后者为假。

### Requirement: 文档里的门禁计数必须能从源码复算

当文档陈述"几条门禁读 `results/`""几条能看到某个分区"时，
这些数字 MUST 有断言要求它们等于从源码派生的结果，
MUST NOT 只是写在文档里由人维护。

#### Scenario: 读文件的门禁数变化时必须被发现

- **WHEN** 新增一条读 `results/` 的门禁，或让已有的门禁改变发现方式
- **THEN** 文档里对应的计数 MUST 变红

- **AND** 断言 MUST 从源码派生，MUST NOT 从文档反向推断

**为什么**：这些数字是给读者回答"造完 v3 数据谁来验"的。
上一轮读代码得出的答案是"6 条"，实际 7 条；再读一次得出"4 条写死"，
而登记表里写的是另外两个文件名。**凡是没有断言守着的数字，都会漂移。**

#### Scenario: 两族必须互补且覆盖全部读文件的门禁

- **WHEN** 断言写死路径族与发现式族
- **THEN** MUST 断言两族无交集
- **AND** MUST 断言两族并集 == 全部读文件的门禁集合
- **AND** MUST 断言"能看到分区"的集合 == 发现式族

**为什么**：只断言各自条数时，把一条从写死组挪到发现组不会红——
但它的适用域完全变了。并集/交集断言能抓到这种"条数没变、性质变了"的改动。
