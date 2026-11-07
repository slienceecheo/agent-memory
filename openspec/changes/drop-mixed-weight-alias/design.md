# Design

## Context

见 `proposal.md` 的 Why。这里只记录塑造方案的事实。

**当前状态**（实测）：

| 项 | 值 |
|---|---|
| `PREREGISTERED_WEIGHTS` 的键 | `{"uniform", "mixed", "cosine_only"}` |
| `uniform is mixed` | **True**（同一对象，`id()` 相同） |
| `set(PREREGISTERED_WEIGHTS) & {a.value for a in Axis}` | `{"mixed"}` |
| 产物里 `weights == "mixed"` 的数量 | **0 / 31** |
| 产物是否记录权重数值 | **否**（只有名字） |

**依赖方向**：`Axis` 在 `evals.datasets.retrieval_v2`（评测层），
`PREREGISTERED_WEIGHTS` 在 `memory.retrieval.rerank`（产品层）。

## Goals / Non-Goals

**Goals**

1. 预注册表里不再有与轴值同名的键。
2. 删掉那条"承诺独立生命周期但实现做不到"的注释。
3. 把"不得互为别名"写成可判定的要求，且判据是 `is` 而不是 `==`。

**Non-Goals**

1. 不改 `uniform` 的名字或数值。
2. 不改 `Axis.MIXED`——它是数据集协议的一部分，改了会让历史产物的 `axis` 字段失效。
3. 不新增 `_ANCHOR_WEIGHTS`（见 D2）。
4. 不写"同实验不得多份产物"的 MUST（见 D3）。

## Decisions

### D1. 删除 `mixed`，不是给它换一个新数值

**否决的备选：给 `mixed` 一个不同的数值**（如 `0.3/0.1/0.6`），让它成为真正的对照。

**否决理由**：那个数值没有来源。只有两种可能：

| 来源 | 问题 |
|---|---|
| 拍一个"看起来合理"的数 | 先看结果再调参数 = HARKing |
| 在 `uniform` 与 `cosine_only` 之间插值 | 那只是权重敏感性的一个采样点，不是"另一个问题" |

而权重敏感性已有独立机制（`test_rank_recompute` 的离线复算），不需要靠预注册表来测。

**否决的备选：保留 `mixed` 但在报告里标注"与 uniform 同值"**。

**否决理由**：报告里多一行零信息的数字，且那一行会随着默认值变化而与 `uniform`
脱钩（因为它们是同一对象）——标注"同值"的那一刻就已经不准确了。

### D2. 不新增 `_ANCHOR_WEIGHTS`

**背景**：`mixed` 的注释声称了一个真实需求——"默认改了之后仍能跑旧配置"。

**这个需求已经有正确实现**：`DEFECT18_WEIGHTS`。

| 常量 | 用途 | 实现 | `is` 默认 |
|---|---|---|---|
| `_DEFAULT_WEIGHTS` | 默认配置 | 独立字面量 | — |
| `DEFECT18_WEIGHTS` | 缺陷 19 的算术锚点 | **独立字面量** | **False** |
| ~~`PREREGISTERED_WEIGHTS["mixed"]`~~ | 声称是锚点 | 指向默认 | **True** ❌ |

而且 `DEFECT18_WEIGHTS` 的独立性不只靠"对象不同"——
它有一条**行为断言**守着（清空预注册表后三个数 `0.0180 / 0.2000 / 0.1820` 不变）。

**所以删 `mixed` 不损失任何能力**：它只是那个概念的一个坏副本，
而正本就在同一个文件里、相隔十几行。

**若将来确实需要"默认改后仍能跑旧配置"**：正确做法是 git 的历史版本，
或一个显式的历史配置名（且该名字必须通过"不与轴值同名"这条 requirement）。

### D3. "同实验不得多份产物"不写成 MUST

**风险是真的**：`--weights <别名>` 会产出内容相同、文件名不同的产物，
而 `_bump_run_count` 会把它记成另一次实验。

**但判据不可观察**：

| 想做 | 为什么做不到 |
|---|---|
| 从产物判断"两份是同一配置" | 产物只记 `weights` 名字，**不记数值** |
| 用"产物名 → 当前配置"查表 | 历史产物含 `auth_heavy` / `base_heavy` / `cond_heavy` / `status_only` 四个**已删除**的名字，查表会失败 |

写一条不可观察的 MUST，结果是它必然变成"永远绿"或"永远红"——
本项目已登记过这两种形态。

**处置**：写进本 design 的风险表（见下），**不写进 spec**。

### D4. 轴值撞车的断言写在测试里，不写在 `rerank.py` 里

`Axis` 在评测层，`PREREGISTERED_WEIGHTS` 在产品层。
若在 `rerank.py` 里 import `Axis`，产品代码就依赖了评测层——依赖方向反转。

```python
# tests/retrieval/test_preregistered_naming.py
def test_weight_names_do_not_collide_with_axis_values() -> None:
    from evals.datasets.retrieval_v2 import Axis
    from memory.retrieval.rerank import PREREGISTERED_WEIGHTS

    overlap = set(PREREGISTERED_WEIGHTS) & {a.value for a in Axis}
    assert not overlap, f"权重名与轴值撞车：{sorted(overlap)}"
```

**这条现在是红的**（`{"mixed"}`），删完变绿。可证伪。

## Risks / Trade-offs

| 风险 | 影响 | 缓解 |
|---|---|---|
| **`--weights <别名>` 产出重复产物** | 文件名不同、内容相同，`_bump_run_count` 记成两次实验 | **不验证**，理由是不可观察（D3）。缓解是注册表不得有别名（本次的 requirement）；加新权重名前必须人工确认它不与既有键同值 |
| 删 `mixed` 会让某些读者以为"少了一组实验" | 报告少一行 | `mixed` 从未被任何产物使用（31 份里 0 份）；它提供的对照信息是零 |
| 断言写在测试里，产品层不知道有这个约束 | 将来有人直接改 `rerank.py` 加一个撞名的键，`rerank.py` 本身不会报错 | 测试会红。这是正确的分层：产品不该知道评测层的轴名 |
| 用 `is` 做判据可能被误读成"值必须不同" | 有人据此给锚点换不同的值 | spec 里明确写：`DEFECT18_WEIGHTS` 与默认**同值但不同对象**是正确形态 |
| **删键后注释指向不存在的键** | `rerank.py:98-99` 会变成"它等于 [不存在的键]"，而它是默认值理由的唯一解释 | 迁移计划第 2 步要求**重写**这两行，不是删除；验证是 `grep mixed rerank.py` 零命中 |
| 两处 docstring 继续描述 `mixed` | 测试不会红（docstring 不参与断言），但文档说谎 | tasks 2.2 明确列出 `test_preregistered_naming.py:13,30-31`；验证是同文件 `grep mixed` 零命中 |

## Migration Plan

一个 commit 即可，但**第 2 步不是"删两行注释"**：

1. 写轴值交集断言（**先红**）
2. 删 `"mixed"` 条目，并**重写默认值的理由**——`rerank.py:98-99` 是
   "默认值为什么是 0.2/0.2/0.6"的唯一解释，而它把支点放在 `mixed` 上。
   删掉后必须换成独立成立的解释（与 `DEFECT18_WEIGHTS` 同值 + 缺陷 19 的算术条件）
3. 改名字集合断言、删 `test_mixed_and_default_...`、清两处 docstring
4. 改 `test_feature_set_cosine.py` 的 docstring 措辞
5. 改两处文档（命名表 + §6.12.5 的"本节不做这个改动"）

**回滚**：`git revert` 单个 commit。无数据迁移，无产物变更。

**回填的时机在归档之后**：`recount_specs.py` 只扫 `openspec/specs/`，
不扫 `changes/`（实测 6 个 vs 45 个 `spec.md`）。apply 期间改 delta 不改 462/399/106；
归档合进主 spec 后才变——那一刻 `test_must_coverage_numbers_are_real` 会红，
回填是把 HANDOFF 拉到新数。

## 怎么被测量

| 设计决定 | 对应指标 |
|---|---|
| D1 删而不是改值 | `set(PREREGISTERED_WEIGHTS) == {"uniform", "cosine_only"}` |
| D2 锚点已有正确实现 | 改默认值后 `DEFECT18_WEIGHTS` 仍为 `(0.2,0.2,0.6)`（改源码 + 重导验证） |
| D3 不写 MUST | 无断言；理由记在本文件 |
| D4 断言在测试层 | `set(W) & {a.value for a in Axis} == set()`，且在 `tests/` 下 |
