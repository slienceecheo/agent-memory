## Why

### 1. `uniform` 与 `mixed` 是**同一个对象**，不是两组配置

```python
_DEFAULT_WEIGHTS = RerankWeights(base=0.2, authority=0.2, cosine=0.6)

PREREGISTERED_WEIGHTS = {
    "uniform": _DEFAULT_WEIGHTS,
    "mixed": _DEFAULT_WEIGHTS,   # <- 同一个对象
}
```

实测：`uniform is mixed` → **True**，`id()` 也相同。

**这本身不算错**——值相同的两组配置在字典里是合法的。**错的是它的注释**：

```python
# 与默认同值，但**独立的键**：它回答"给无信号项留余量会损失多少"，
# 是稳健性对照。哪天默认改了，它仍应指向 0.2/0.2/0.6。
"mixed": _DEFAULT_WEIGHTS,
```

注释承诺了"默认改了它仍指向旧值"，而**同一对象做不到这件事**。实测（改源码后重新导入）：

| 常量 | 把默认改成 `0.4/0.3/0.3` 后 |
|---|---|
| `uniform` | 0.4 / 0.3 / 0.3 |
| `mixed` | **0.4 / 0.3 / 0.3**（跟着变） |
| `DEFECT18_WEIGHTS` | **0.2 / 0.2 / 0.6**（不动） |

**所以这是"注释与实现不符"**——项目已登记的第 4 种坏断言形态。
而 `DEFECT18_WEIGHTS` 就在同一份文件里，证明这个意图**有正确的实现方式**。

**判据是 `is`，不是 `==`**：

```
uniform  vs mixed        ==:True   is:True    ← 坏
DEFECT18 vs uniform      ==:True   is:False   ← 好（值同、对象不同）
```

"两组同值"不是缺陷，`DEFECT18_WEIGHTS` 与默认同值且完全正确。
缺陷只在"同一对象"。

### 2. `mixed` 这个名字已经被另一个概念占用

```python
# evals/datasets/retrieval_v2.py:35
class Axis(StrEnum):
    A = "A"
    C = "C"
    MIXED = "mixed"
```

`Axis.MIXED` 是**查询轴**（由 `retrieval-dataset-v2.md` 定义：混合两轴查询），
而 `PREREGISTERED_WEIGHTS["mixed"]` 是**权重配置**。两者同名、无关。

实测撞车：

```python
set(PREREGISTERED_WEIGHTS) & {a.value for a in Axis}
= {"uniform","mixed","cosine_only"} & {"A","C","mixed"}
= {"mixed"}
```

**后果**：`grep mixed` 返回两种东西；读 `--weights mixed` 与轴 `mixed` 混淆；
`test_v2_baselines` 断言 `set(baselines) == {"A","C","mixed"}`（轴），
`test_preregistered_naming` 断言 `set(PREREGISTERED_WEIGHTS) == {...}`（权重）——
两个 `mixed` 在两个不相干的集合里。

### 3. 它当前提供的对照信息是零

`mixed` 的原始定义是"给无信号项留余量"。但现在**那就是默认配置**。
"有退路的配置"成了默认之后，它作为对照的价值归零——对照的意义来自与默认不同。

### 4. 别名会产出重复产物（潜伏，未触发）

`--weights mixed` 会产出 `retrieval-*-mixed-*.json`：文件名不同、内容相同。
而 `_bump_run_count` 会把它记成另一次实验。

实测：现有 31 份产物的 `weights` 分布是
`uniform: 27 / auth_heavy: 1 / base_heavy: 1 / cond_heavy: 1 / status_only: 1`，
**没有任何 `mixed`**。所以这是潜伏风险，尚未被触发。

**但这条不能写成 MUST，因为它不可观察**：产物只记 `weights` 名字，
不记数值；且历史产物含 `auth_heavy` / `base_heavy` / `cond_heavy` / `status_only`
四个现已不存在的名字，所以任何"产物名 → 当前配置"的检查都会在历史文件上失败。

## What Changes

**1. 删除 `PREREGISTERED_WEIGHTS["mixed"]`**

```python
PREREGISTERED_WEIGHTS = {
    "uniform": _DEFAULT_WEIGHTS,                  # 默认（0.2/0.2/0.6）
    "cosine_only": RerankWeights(0.0, 0.0, 1.0),  # 上界
}
```

同时删掉那条声称它是独立锚点的注释——**注释承诺的性质从未成立**。

**2. 新增 spec requirement：权重名不得与数据集轴值同名**

```
权重配置名 MUST NOT 与数据集轴值同名。
```

判据：`set(PREREGISTERED_WEIGHTS) & {a.value for a in Axis}` 必须为空集。
**实测现在红**（交集是 `{"mixed"}`），删掉 `mixed` 后立刻绿——这是可证伪的形态。

**3. 明确不新增 `_ANCHOR_WEIGHTS`**

"默认改了仍能跑旧配置"这个需求，正确实现是 `DEFECT18_WEIGHTS` 那种
**独立字面量**，而不是给默认值挂第二个键。这个项目的锚点先例已经存在且正确。

**4. 不动 `DEFECT18_WEIGHTS`**

它已经是独立对象（`is` 为 False），且独立性由行为断言守着
（清空预注册表后 `0.0180 / 0.2000 / 0.1820` 不变）。本次只删坏副本。

**5. 顺手补一处漂移了两次、无人守着的数字**

`docs/HANDOFF.md:133` 写着"`PREREGISTERED_WEIGHTS` 三组"。实测 git 历史：

| 提交 | 该行 | 现实 |
|---|---|---|
| `e8ca4f7~1`（加 cosine 前） | 四组 | `uniform/base_heavy/auth_heavy/status_only` |
| `e8ca4f7`（加 cosine 后） | 三组 | `uniform/mixed/cosine_only` |
| 本次之后 | 应两组 | `uniform/cosine_only` |

**没有任何断言守着这个数字**，而它已经漂移过一次（`e8ca4f7` 是我手动改的，
若那次漏改没人会发现）。所以本次除了改成"两组"，还补一条
`test_handoff_preregistered_count_matches_reality`，
判据是 `len(PREREGISTERED_WEIGHTS)`，不从文档反推。

**为什么纳入本次范围**：它不是"顺手改一个数"，而是"补上第 N 处没有断言守着的数字"。
这类补充每做一次，就少一处漂移。

## Capabilities

### New Capabilities

无。

### Modified Capabilities

- `evaluation-harness`：`权重命名必须与语义一致` 增加"不得与轴值同名"，
  并从建议命名表里删掉 `mixed` 行

## 本次不做什么（范围边界）

| 不做 | 理由 |
|---|---|
| 不改 `uniform` 这个名字 | 它是历史接口名，48 处调用依赖它存在；改名是纯噪声 diff |
| 不改 `uniform` 的数值 | 本次只删一个别名，不碰默认配置 |
| 不新增 `_ANCHOR_WEIGHTS` | `DEFECT18_WEIGHTS` 已是正确先例；再加一个无信号的锚点只会让报告多一行 |
| 不写"同实验不得多份产物"的 MUST | 不可观察：产物只记名字不记数值，且历史产物含已删除的名字 |
| 不改 `Axis.MIXED` | 轴的值是数据集协议的一部分，由 `retrieval-dataset-v2.md` 定义；改它会让历史产物的 `axis` 字段失效 |
| 不重命名产品层的 `mixed` 到别处 | 它没有独立含义，改名只会保留一个空壳 |

## 可独立验收的理由

三条各自可判定的出口：

1. **删掉后轴值交集为空**：`set(PREREGISTERED_WEIGHTS) & {a.value for a in Axis} == set()`。
   删之前它是 `{"mixed"}`——一条**现在红、删完绿**的断言。
2. **`mixed` 不再存在**：`"mixed" not in PREREGISTERED_WEIGHTS`，且 `--weights mixed` 会被 argparse 拒绝。
3. **锚点行为的回归**：改默认值后 `DEFECT18_WEIGHTS` 仍为 `0.2/0.2/0.6`
   （用"改源码 + 重新导入"验证，不是运行时 monkeypatch）。

## Impact

**代码**

| 文件 | 变更 |
|---|---|
| `src/memory/retrieval/rerank.py` | 删 `"mixed"` 条目与其注释（5 行）；其余不动 |

**测试（3 处真代码 + 1 处 docstring）**

| 位置 | 变更 |
|---|---|
| `test_preregistered_naming.py:21` | 名字集合改成 `{"uniform", "cosine_only"}` |
| `test_preregistered_naming.py:51` | 删 `test_mixed_and_default_are_the_same_value_but_distinct_keys` |
| `test_preregistered_naming.py:67` | 随之删除（在该被删测试体内） |
| `test_feature_set_cosine.py:177` | docstring 提到 `mixed`，改措辞 |
| **新增** `test_weight_names_do_not_collide_with_axis_values` | 轴值交集断言 |

**文档**

- `docs/reports/v2-what-it-measures.md`：命名表删掉 `mixed` 行；
  并删掉 §6.12.5 结尾那句"本节不做这个改动——它需要单独变更"
  （**本次就是那个单独变更**）
- `docs/HANDOFF.md:133`：`PREREGISTERED_WEIGHTS` 三组 → 两组
- **新增断言** `test_handoff_preregistered_count_matches_reality`：
  HANDOFF 的组数必须等于 `len(PREREGISTERED_WEIGHTS)`

**不影响**：数据集、`results/*.json`（31 份产物里没有 `mixed`）、
`uniform` 的数值与语义、任何排序行为。

## 对已归档结论的影响

**无。** 本次删的是一个从未被任何产物使用过的名字（31 份产物里 0 份 `mixed`），
也不改任何权重数值。已归档的结论 5 与 5b 的数字不受影响。
