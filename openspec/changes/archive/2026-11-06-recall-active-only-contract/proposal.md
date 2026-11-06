## Why

**`status` 恒为 1.0 不是"v2 数据的性质"，而是结构必然。**

三条召回路径全部只返回 ACTIVE：

| 路径 | 过滤位置 |
|---|---|
| `lexical.py` | 包装 `search_text`，它只返回 ACTIVE |
| `vector.py` | `WHERE i.status = 'ACTIVE'` |
| `adjacency.py` | `AND status = 'ACTIVE'` + Python 二次过滤 |

**而 `rerank.py` 的 docstring 已经为两个同类特征写好了删除理由**：

> **已删除的两个特征**（审查实测它们在 ACTIVE-only 上恒为常数）：
> - `temporal_validity`：所有召回路径只返回 ACTIVE，恒为 1.0
> - `recency`：场景文件没有时间字段，全部同一 `BASE_TIME`
> 
> 留着它们只会让"重排有效"看起来成立，实际上是排序没变。

**`status` 是第三个，理由一字不差。**

## 但这个契约没有断言守着

实测现有覆盖：

| 位置 | 测什么 | 强度 |
|---|---|---|
| `test_rerank_variance.py:110` | `len({status_score(ACTIVE)}) == 1` | 测**函数**，不是召回路径 |
| `test_v3_capability_boundary.py:140` | 记忆库 `status == {"ACTIVE"}` | 测**数据集**，不是召回路径 |
| `test_rerank.py:53` | `ACTIVE > CONFLICTED` | 测**值域**，不是池 |

**三条都是间接的。删 `status` 之前必须有一条直接断言。**

## What Changes

**1. 新增 `tests/retrieval/test_recall_active_only.py`（5 条）**

| 断言 | 判据 |
|---|---|
| `test_lexical_returns_only_active` | 行为：给含非 ACTIVE 的 store，lexical 不返回它们 |
| `test_vector_returns_only_active` | 行为：同上（**非 ACTIVE 也写了向量**） |
| `test_adjacency_returns_only_active` | 行为：只抓 SQL 层 |
| `test_all_three_paths_agree_on_active_only` | 源码：三处过滤都在 |
| `test_adjacency_has_python_side_refilter` | 源码：Python 二次过滤在 |

**2. 记录"行为断言守不住 Python 二次过滤"这个事实**

实测：把 adjacency 的 `if item.status is Status.ACTIVE` 删掉，
**行为断言仍然通过**（SQL 已经过滤了）。

**所以行为断言与源码断言的分工必须写清**：
- 行为断言守 SQL 层
- 源码断言守 Python 层

**若以为一条行为断言能守住两层，一层被删掉时不会有任何提示。**

## Impact

- 代码：**无**
- 测试：新增 `test_recall_active_only.py`
- spec：本变更**只登记契约**，不删 `status`
- 结果文件：**无新增**

## 验收

| # | 判据 | 可被违反的形式 |
|---|---|---|
| 1 | vector 删掉 SQL 的 ACTIVE | 行为断言 + 源码断言**都红** |
| 2 | adjacency 删掉 Python 二次过滤 | **源码断言红，行为断言仍绿** |
| 3 | lexical / vector / adjacency 都返回非 ACTIVE | 对应行为断言红 |
| 4 | 三条路径的过滤语义不一致 | `test_all_three_paths_agree` 红 |

**验收 2 的"行为断言仍绿"本身是结论**，不是缺陷——
它说明那条行为断言只覆盖 SQL 层。

## 后续变更（不在本次范围）

**删 `status` 特征**（`cosine` 替换它）是一个中等变更：

| 项 | 数量 |
|---|---|
| 假 features 构造 | **16 处 / 8 文件** |
| 字段断言 | **5 处** |
| spec requirement | **2 条** |

**必须先有本变更的契约断言，才能删。**
否则删掉之后，没有任何东西守着"它为什么可以删"。
