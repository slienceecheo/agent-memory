## Why

**两件"没有断言守着"的事，都在同一轮里被发现。**

### 1. 第五种坏断言形态：覆盖范围被高估

`test_adjacency_returns_only_active` 是**行为断言**——它调用路径、看返回结果。

而 `adjacency` 路线有**两层** ACTIVE 过滤：

| 层 | 位置 |
|---|---|
| SQL | `AND status = 'ACTIVE'` |
| Python | `if item.status is Status.ACTIVE` |

**实测删掉 Python 那层之后，行为断言仍然绿**（SQL 已经过滤了）：

| 删掉什么 | 行为断言 | 源码断言 |
|---|---|---|
| `vector.py` 的 SQL 过滤 | **红** | **红** |
| `adjacency.py` 的 Python 过滤 | **绿** | **红** |

**那条行为断言完全正确，但它只覆盖链路的一层**，
而名字（`test_adjacency_returns_only_active`）与位置让人以为覆盖整条链。

### 2. `CAPABILITIES` 漂移，而写死的数字无人守

`test_spec_normative_words.py` 的 `CAPABILITIES` 漏掉 `retrieval-apparatus`
（它加得晚，而清单是手写的）。

**后果**：那个测试数的是 5 个能力的 Scenario，而全仓库有 6 个。
它的 docstring 里写死了一个数字，而那个数字：

| 版本 | 含义 | 现在 |
|---|---|---|
| 曾 | `must_lines` | 409 |
| 曾 | 5 个能力的 Scenario 和 | **365** |
| 写死的 | **以上都不是** | 它是归档那一刻的旧值 |

**同一类问题已经出现第六次**：一个数字被写死在文字里，而断言不依赖它。

## What Changes

**1. HANDOFF 的形态表从四种扩到五种**

```
| 5 | 覆盖范围被高估 | 断言的粒度 | 删掉链路的另一层，看断言红不红 |
```

**并附实测对照表**（vector 两列红、adjacency 绿/红）。

**2. 新增"顺带发现：手写清单会漂移"**

含两条修法：
1. 断言 `CAPABILITIES` 覆盖所有能力
2. **docstring 里不写具体数字**

**3. 新增 `tests/test_assertion_forms.py`（5 条）**

| 断言 | 判据 |
|---|---|
| `test_handoff_lists_five_assertion_forms` | 表有 1–5 五行，**且标题数字 == 5** |
| `test_handoff_has_the_overestimated_coverage_form` | 对照表两行，且 adjacency 行**同时有绿和红** |
| `test_handoff_warns_about_handwritten_lists_drifting` | "修法两条"的两条都在 |
| `test_handoff_says_not_to_hardcode_numbers_in_docstrings` | 禁令本身 + 理由 |
| `test_capabilities_covers_all_specs` | `CAPABILITIES` == `openspec/specs/` |

**4. 修 `CAPABILITIES`：补 `retrieval-apparatus`**

补齐后比例从 `185/365`（5 能力）变成 `185/380`（6 能力）= **48.7%**，
仍在断言区间 `[0.4, 0.7]` 内。

**5. 删掉 docstring 里写死的数字**

改成"要知道当前值，跑一次并看失败消息里的 `{bare}/{total}`"。

## Impact

- 代码：**无**
- 测试：新增 `test_assertion_forms.py`；改 `test_spec_normative_words.py`
- 文档：`HANDOFF.md`（形态表 + 漂移小节 + 标题"四种"→"五种"）
- 结果文件：**无新增**

## 验收

| # | 判据 | 可被违反的形式 |
|---|---|---|
| 1 | 标题写"四种"而表有 5 行 | **必须红** |
| 2 | 删掉表格第 5 行 | 必须红 |
| 3 | adjacency 行的「绿」改成「红」 | **必须红**（不对称消失） |
| 4 | 删掉"修法两条"整段 | 必须红 |
| 5 | 删掉修法第 2 条 | 必须红 |
| 6 | `CAPABILITIES` 漏一项 | 必须红 |

**验收 3 是本变更的核心**：它证明断言抓的是"行为与源码的差异"，
而不只是"那一行还在"。

**验收 1 是自我指涉的**：标题里的"四种"本身就是一个没有断言守着的数字，
而本变更给它加了断言。
