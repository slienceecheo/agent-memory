# Tasks

## 0. 为什么要有这个变更

**两件"没有断言守着"的事，都在同一轮发现。**

| # | 事 | 形态 |
|---|---|---|
| 1 | 行为断言只覆盖 SQL 层，名字却像覆盖整条链 | **第五种：覆盖范围被高估** |
| 2 | `CAPABILITIES` 漏项 + docstring 写死数字 | 手写清单漂移 |

## 1. 核实第五种形态

- [x] 1.1 `adjacency` 有两层 ACTIVE 过滤

  | 层 | 位置 |
  |---|---|
  | SQL | `AND status = 'ACTIVE'` |
  | Python | `if item.status is Status.ACTIVE` |

- [x] 1.2 实测"删掉 Python 层后行为断言仍绿"

  | 删掉什么 | 行为断言 | 源码断言 |
  |---|---|---|
  | `vector.py` 的 SQL | **红** | **红** |
  | `adjacency.py` 的 Python | **绿** | **红** |

- [x] 1.3 结论：行为断言只覆盖 SQL 层

## 2. 核实 `CAPABILITIES` 漂移

- [x] 2.1 清单漏 `retrieval-apparatus`
  - `test` 数 5 个能力的 Scenario（当时 365）
  - 全仓库 6 个（380）

- [x] 2.2 docstring 写死的数字既不是 5 能力和，也不是全部
  - 它是归档那一刻的旧值

## 3. 改 HANDOFF

- [x] 3.1 标题"四种" → **"五种"**
- [x] 3.2 表格加第 5 行（覆盖范围被高估 / 断言的粒度 / 删掉链路的另一层）
- [x] 3.3 加实测对照表（vector 两列红、adjacency 绿/红）
- [x] 3.4 加"顺带发现：手写清单会漂移"小节 + 两条修法

## 4. 新增 `tests/test_assertion_forms.py`（5 条）

| 断言 | 判据 |
|---|---|
| `test_handoff_lists_five_assertion_forms` | 1–5 五行 + **标题数字 == 5** |
| `test_handoff_has_the_overestimated_coverage_form` | 两行都在 + **adjacency 行同时有绿和红** |
| `test_handoff_warns_about_handwritten_lists_drifting` | "修法两条"两条都在 |
| `test_handoff_says_not_to_hardcode_numbers_in_docstrings` | 禁令 + 理由 |
| `test_capabilities_covers_all_specs` | 清单 == 目录 |

## 5. 修 `test_spec_normative_words.py`

- [x] 5.1 `CAPABILITIES` 补 `retrieval-apparatus`
- [x] 5.2 新增 `test_capabilities_list_covers_all_existing_specs`
- [x] 5.3 删掉 docstring 里写死的数字（`179/359`、`49.9%`、`175`）

## 6. 双向证伪（11 个方向全部符合预期）

| # | 构造 | 期望 | 实测 |
|---|---|---|---|
| A | 标题改回"四种" | 红 | 红（"标题写四种形态，而表里有 5 行"） |
| B | 删掉表格第 5 行 | 红 | 红 |
| C | 删掉 adjacency 那一行 | 红 | 红 |
| **C2** | **把 adjacency 的「绿」改成「红」** | **红** | **红（不对称消失）** |
| D | 删掉"修法两条"整段 | 红 | 红 |
| D2 | 删掉修法第 2 条 | 红 | 红 |
| E | 删掉"docstring 里不写具体数字" | 红 | 红 |
| F | `CAPABILITIES` 漏一项 | 红 | 红 |
| G | 原文本（3 条） | 绿 | 绿 |

**C2 是核心**：它证明断言抓的是"差异"，不只是"行还在"。

**A 是自我应用**：标题里的"四"本身就是一个没守着数字，
本变更给它加了断言。

## 7. 证伪过程中修正的两处

- [x] 7.1 **A 最初没红**：断言只看表格，不看标题
  - 已加"标题数字 == 表格行数"的检查

- [x] 7.2 **C/E 最初没红**：替换的是段落里出现多次的词
  - `行为断言` 4 次、`手写` 2 次、`docstring` 2 次
  - 已改成定位到表格行 / 具体禁令句

**这两次都是同一个形态**：字符串在段落里出现多次 -> 删一处仍绿。

## 8. 验收

- [x] 8.1 `openspec validate assertion-form-5-and-capability-drift --strict` 通过
- [ ] 8.2 **归档前**跑 `openspec validate --all --strict`
- [ ] 8.3 全量测试通过
- [ ] 8.4 归档

## 9. 不在本变更范围

- **不删 `status`**（下个变更）
- **不加 `cosine`**
- **不改 `_scenarios` 的切分逻辑**
