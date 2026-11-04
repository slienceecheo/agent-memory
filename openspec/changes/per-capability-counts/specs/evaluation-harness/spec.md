## ADDED Requirements

### Requirement: 分项计数必须逐行复算，不得只验合计

当文档用表格按能力（或其他维度）拆分某个总数时，每一行的数字
MUST 与计算函数逐个比对，MUST NOT 只断言合计。

**合计断言抓不到分项错误**：合计对时分项写错，合计断言**必然通过**。

#### Scenario: 分项写错而合计不动必须被发现

- **WHEN** 把某张按能力拆分的表里一行的数字改错，合计保持不变
- **THEN** 必须有断言变红
- **AND** 红的时候 MUST 指出是哪张表、哪个能力、写的是多少、真值是多少

**实测三处**（都是这个形态，都曾经全绿）：

| 表 | 写错的行 | 合计 | 结果 |
|---|---|---|---|
| MUST/SHALL 行表 | `evaluation-harness` 64，实际 143 | 226 一直对 | 三条断言全绿 |
| Scenario 表 | 98 改成 97 | 300 不动 | 三条断言全绿 |
| 要求数表 | `evaluation-harness` 13，实际 18 | 59 是**对的** | 无任何断言 |

#### Scenario: 分项之和必须等于该表声明的合计

- **WHEN** 表格里同时有分项与合计
- **THEN** MUST 断言 `sum(分项) == 合计`

**为什么需要两条而不是一条**：

| 检查 | 抓什么 | 能被单独违反吗 |
|---|---|---|
| 逐行 == `compute()` | 某行数字写错 | ✅ 改一行 |
| `sum(分项) == 合计` | 少了/多了一行，或合计被手改 | ✅ 删一行 / 改合计 |

**不要加第三条"合计 == `compute()` 总和"**：它在前两条都通过时**必然成立**
（逐行全对 → 分项和 == `compute()` 总和；再等于合计 → 合计 == 总和），
所以**永远不会被单独违反**。那是恒真断言，不是判据。
本项目已有明确纪律：判据必须能与意图一起被违反。

**实测**：要求数表的分项之和是 54、合计 59 —— 第二条抓它；
把每行都改成正确值后，`sum` 自然等于 `compute()` 总和，第三条无事可做。

#### Scenario: 定位表格必须用表头，不能用字符串包含

- **WHEN** 从一个 Markdown 小节里取某张表
- **THEN** MUST 先按表头定位该表，再解析它的行
- **AND** MUST NOT 用 `f"| `{name}` | {value} |" in section`

**两个实测原因**：

1. **同节有多张两列表**：§0.6 里既有 MUST/SHALL 行表又有四类细分，
   只按"两列 + 反引号"筛会同时抓到，导致 MUST 表被读成四类表的数字
   （实测 `conflict-resolution` 被读成 35 而不是 9）。
2. **加粗写法不统一**：文档里同时存在 `` | `cap` | 30 | `` 与
   `` | **`cap`** | **30** | ``。字符串匹配要枚举所有组合，
   实测漏掉了 `retrieval-apparatus` 那一行。
3. **`in section` 会被别处的数字顶替**：正文里出现同一个数字也会通过。

### Requirement: 产物缺失的语义必须按产物族区分

不同产物族的"缺失"含义不同，处置 MUST 不同，且该映射 MUST 被断言固定。

| 产物族 | 缺失的含义 | 处置 |
|---|---|---|
| 一次性实验产物（`a3-*.json`） | **那次实验没做** | `applicable=True, passed=False`（失败） |
| 每代产物（`v2-*` / `v3-*`） | **这代还没数据** | `applicable=False`（不适用） |

#### Scenario: 一次性实验产物缺失必须判失败

- **WHEN** `results/a3-*.json` 不存在
- **THEN** 读它的门禁 MUST 判 `applicable=True, passed=False`
- **AND** MUST NOT 判成不适用

**为什么**：把 `a3-*.json` 缺失判成"不适用"，等于把"实验没做"
从失败列表里移出去——**用不适用掩盖没检查**，正是本项目一直在防的形态。

**实测当前行为**（`results/` 为空目录）：

```
L6a: applicable=True  passed=False  "缺少 a3-lexical-vector-adjacency.json"
L6b: applicable=True  passed=False  "缺少 a3-lexical-vector-adjacency.json"
L6c: applicable=True  passed=False  "缺少真实运行结果 a3-..."
L8:  applicable=True  passed=False  "缺少 a3-with-dedup.json"
```

#### Scenario: 每代产物缺失必须判不适用

- **WHEN** `results/` 下没有任何同类产物（既无 v2 也无 v3）
- **THEN** 读它的门禁 MUST 判 `applicable=False`
- **AND** MUST NOT 判成失败

**为什么两者必须配对写**：只写"一次性产物缺失要红"，
读者会以为"所有缺文件都该红"；只写"每代产物缺失要不适用"，
读者会以为可以给 `_load_run` 加三态。**两句话合起来才是完整映射。**

#### Scenario: "不改"的决定必须写成断言

- **WHEN** 评审确认某个"看起来该改"的行为其实是正确的
- **THEN** MUST 把它写成断言，MUST NOT 只写进文档或口头结论

**为什么**：否则下一个人会重新提出同样的改法。本变更的
`test_fixed_path_gates_fail_when_artifact_missing` 就是为此存在——
它不是因为"这里可能有 bug"，而是因为"这里曾经被误判为 bug"。

**证伪**：把那 4 条门禁改成"缺文件 -> 不适用"，该断言变红
（"L6a 在 a3-*.json 缺失时被判成**不适用**"）。
