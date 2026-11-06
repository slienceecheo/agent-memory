## ADDED Requirements

### Requirement: 所有召回路径 MUST 只返回 ACTIVE

本项目的三条召回路径 MUST 只返回 `Status.ACTIVE` 的条目。
该契约 MUST 有断言守着，且断言 MUST 覆盖"路径级"而非"数据级"。

#### Scenario: 三条路径的过滤位置不同，但语义必须一致

- **WHEN** 检查召回路径的 ACTIVE 过滤
- **THEN** MUST 逐条验证每一路

| 路径 | 过滤位置 |
|---|---|
| `lexical` | 包装 `search_text`，它只返回 ACTIVE |
| `vector` | SQL `WHERE i.status = 'ACTIVE'` |
| `adjacency` | SQL `AND status = 'ACTIVE'` + Python 二次过滤 |

#### Scenario: "数据里只有 ACTIVE"不等于"路径会过滤"

- **WHEN** 断言"召回路径只返回 ACTIVE"
- **THEN** MUST 构造一个**含非 ACTIVE 的 store** 并调用路径
- **AND** MUST NOT 只用"现有数据集的 status 集合 == {ACTIVE}"

**实测反例**：`test_v3_capability_boundary.py:140` 断言记忆库的 status 全是 ACTIVE。
但那只证明**这份数据**没有非 ACTIVE 条目——
若某条路径去掉了过滤，它仍然通过（因为没有非 ACTIVE 可返回）。

**所以必须构造非 ACTIVE**。

#### Scenario: 非 ACTIVE 条目必须有向量，否则测试不成立

- **WHEN** 验证 `vector` 路径的 ACTIVE 过滤
- **THEN** MUST 给非 ACTIVE 条目也写入向量
- **AND** MUST NOT 只给 ACTIVE 写

**为什么**：若非 ACTIVE 没有向量，"它们没被召回"可能只是因为没向量，
而不是因为 status 过滤——测试会假绿。

### Requirement: 行为断言与源码断言的分工必须写明

当同一契约同时由行为断言与源码断言覆盖时，
MUST 写明各自覆盖哪一层，MUST NOT 让读者以为一条覆盖全部。

#### Scenario: 行为断言守不住 Python 二次过滤

- **WHEN** 删掉 `adjacency.py` 的 Python 二次过滤
  (`if item.status is Status.ACTIVE`)
- **THEN** 行为断言**仍然通过**（SQL 已经过滤了）
- **AND** 只有源码断言会红

**实测**：

| 删掉什么 | 行为断言 | 源码断言 |
|---|---|---|
| `vector.py` 的 SQL 过滤 | **红** | **红** |
| `adjacency.py` 的 Python 过滤 | **绿** | **红** |

**这个"绿"本身是结论，不是缺陷**：
行为断言只覆盖 SQL 层，Python 层由源码断言守。

**若不写清分工**，人会以为"一条行为断言守住了两层"——
而一层被删掉时不会有任何提示。

### Requirement: 恒常数字段不得作为排序特征

当某个特征在候选池内恒为常数时，
MUST NOT 让它参与加权，MUST NOT 把它作为"观测事实"保留在 `features` 里。

#### Scenario: 恒 1.0 的字段没有可审计的内容

- **WHEN** 某特征在池内恒为 1.0
- **THEN** MUST 删除它，MUST NOT 只把权重归零

**与 `condition` 的区别**：

| 字段 | 池内取值 | 有信息吗 | 处置 |
|---|---|---|---|
| `condition` | 0.0 / 0.5 / 1.0（有方差） | ✅ | **保留为审计字段** |
| `status` | 恒 1.0（无方差） | ❌ | **删除** |

**`condition` 有方差，所以"审计"有内容可审计。**
`status` 无方差，保留它只是留一个恒等常量。

#### Scenario: 删除必须有先例与前提

- **WHEN** 删除一个特征
- **THEN** MUST 指出同类先例与删除前提

**先例**（`rerank.py` 的 docstring 已记录）：

| 特征 | 删除理由 |
|---|---|
| `temporal_validity` | 所有召回路径只返回 ACTIVE，恒为 1.0 |
| `recency` | 场景文件没有时间字段，全部同一 `BASE_TIME` |
| **`status`** | **同 `temporal_validity`** |

**前提**：所有召回路径只返回 ACTIVE（由本变更的断言守）。

**若前提破裂**（某条路径返回非 ACTIVE），`status` 会有方差，
那时它应该重新成为特征。
