# Tasks

## 0. 为什么要有这个变更

**`status` 恒 1.0 是结构必然，不是 v2 数据的性质。**

三条召回路径全部只返回 ACTIVE：

| 路径 | 过滤位置 |
|---|---|
| `lexical.py` | 包装 `search_text`（只返回 ACTIVE） |
| `vector.py` | `WHERE i.status = 'ACTIVE'` |
| `adjacency.py` | `AND status = 'ACTIVE'` + Python 二次过滤 |

**所以 `status` 应该删除。而删除的前提是"召回只返回 ACTIVE"——
这个契约此前没有任何断言。**

## 1. 核实先例

- [x] 1.1 `rerank.py` docstring 已为两个同类特征写了删除理由

  ```
  **已删除的两个特征**（审查实测它们在 ACTIVE-only 上恒为常数）：
  - temporal_validity：所有召回路径只返回 ACTIVE，恒为 1.0
  - recency：场景文件没有时间字段，全部同一 BASE_TIME
  ```

  **`status` 是第三个，理由一字不差。**

- [x] 1.2 `condition` 不能类比
  - `condition` 池内有方差（0.0/0.5/1.0）-> 审计有内容
  - `status` 恒 1.0 -> 审计一个常数

## 2. 核实现有覆盖（都不够）

- [x] 2.1 三条间接覆盖

  | 位置 | 测什么 | 漏什么 |
  |---|---|---|
  | `test_rerank_variance.py:110` | `status_score` 的取值数 | 测**函数**，不是路径 |
  | `test_v3_capability_boundary.py:140` | 记忆库的 status 集合 | 测**数据集**，不是路径 |
  | `test_rerank.py:53` | ACTIVE > CONFLICTED | 测**值域**，不是池 |

- [x] 2.2 **直接断言不存在** -> 本变更补上

## 3. 新增 `tests/retrieval/test_recall_active_only.py`（5 条）

- [x] 3.1 三条行为断言（构造含 `SUPERSEDED`/`CONFLICTED` 的 store）

  **关键**：给非 ACTIVE 也写向量，否则 vector 测试会假绿。

- [x] 3.2 两条源码断言
  - `test_all_three_paths_agree_on_active_only`
  - `test_adjacency_has_python_side_refilter`

- [x] 3.3 **发现"行为断言守不住 Python 二次过滤"**

  | 删掉什么 | 行为断言 | 源码断言 |
  |---|---|---|
  | `vector.py` 的 SQL | **红** | **红** |
  | `adjacency.py` 的 Python 过滤 | **绿** | **红** |

  已把分工写进 docstring。

## 4. 双向证伪（13 个方向全部符合预期）

| # | 构造 | 期望 | 实测 |
|---|---|---|---|
| 基线 | 5 条 | 绿 | 绿 |
| A1 | `vector.py` 删 SQL 的 WHERE | 行为红 | 红 |
| A2 | 同上 | 源码红 | 红 |
| B1 | `adjacency.py` 删 Python 过滤 | **源码红** | 红 |
| B2 | 同上 | **行为绿** | 绿 |
| D | 恢复后 | 全绿 | 绿 |

**B2 的"绿"是本变更的核心发现**：
它说明行为断言只覆盖 SQL 层。

## 5. 验收

- [x] 5.1 `openspec validate recall-active-only-contract --strict` 通过
- [ ] 5.2 **归档前**跑 `openspec validate --all --strict`
- [ ] 5.3 全量测试通过
- [ ] 5.4 归档

## 6. 不在本变更范围

**删 `status`** 是下个变更，规模：

| 项 | 数量 |
|---|---|
| 假 features 构造 | **16 处 / 8 文件** |
| 字段断言 | **5 处** |
| spec requirement | **2 条** |

**必须先有本变更的契约断言，才能删。**
