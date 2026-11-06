## Why

### 1. `status` 早该删掉：spec 已经写明，代码还没做

`openspec/specs/evaluation-harness/spec.md` 的「恒常数字段不得作为排序特征」已经判定：

> 当某个特征在候选池内恒为常数时，MUST NOT 让它参与加权，MUST NOT 把它作为"观测事实"保留在 `features` 里。
> `status` | 恒 1.0（无方差） | ❌ | **删除**

那个判断的依据是上一轮已归档的 `recall-active-only-contract`：三条召回路径只返回 `ACTIVE` 的 5 条断言。
先例也已登记在同一处——`temporal_validity`（同样恒 1.0）与 `recency`（场景没有时间字段）。

**所以这不是"想加个新特征"，而是"实现落后于自己的规范"。** 当前 `RerankWeights` 里 `status` 仍占 1/3 权重，
`FeatureScores` 里仍有 `status` 字段，`features` 仍在写它。

数值上它的净效是零：池内每条候选都是 `ACTIVE`，`0.3 × 1.0` 对所有候选取同一个常数，
只给 `rerank` 的浮点和加一个偏移量，不改变任何一对候选的相对顺序。

### 2. cosine 是唯一通过全部泄漏与噪声判据的第三特征

四项泄漏判据（v2 数据，已归档在 `cosine-*` 三个变更里）：

| 判据 | `sample` | `billing` |
|---|---|---|
| gold 与干扰项的均值差 | +0.1673 | +0.1156 |
| gold 唯一最高 | 9/10 | 10/12 |
| 分布重叠（`min(gold) < max(dist)`） | ✅ | ✅ |
| 干扰项之间的秩相关 `rho` 中位数 | +1.000 | +1.000 |

噪声边界：缓存命中时逐位相同；未命中时 `cos = 0.9971`；把向量旋转 4.36° 后 `|Δcos|` 最大 **0.0061**，
低于阈值 **0.01**（1.6 倍余量）。5700 次扰动、0 次名次翻转。`sample` 的噪声是最小正 gap 的 45%，
余量 55%——紧，但成立。

**必须同时登记的弱处**：`billing` 每个 case 只有 2 个干扰项，`rho` 只能取 `±1`，统计力很弱。
所以本节支持的是"未发现 gold 检测器特征"，不是"证明 cosine 不是 gold 检测器"。

### 3. cosine 补的是 lexical 的结构性盲区，不是"分数更高"

这一条是本次变更的核心论证，它不依赖任何分数比较：

**`sample`**

| 量 | lexical | cosine |
|---|---|---|
| 排序空间（gold 在池内） | 6 条 | **10 条** |
| 共同 6 条上的 top-1 | 5/6 | 5/6（**完全相同**） |
| 仅 cosine 覆盖的 4 条 | — | 4/4 命中，`ledger-q3/q4/q7/q8`，**全部 implicit，bigram 全 0** |

**`billing`**

| 量 | lexical | cosine |
|---|---|---|
| 共同 9 条上的 top-1 | 8/9 | **9/9** |
| 仅 cosine 覆盖的 3 条 | — | 1/3 命中（`a2`/`a9` implicit、`c3` **explicit**） |

**所以准确的表述是**：cosine 覆盖了 lexical 未能召回的 case，其中 6/7 是 implicit；
lexical 在这些查询上字面重叠为 0，**连候选都进不了融合**，不是"排序排错了"。

**明确不做"增益是 lexical 的 3 倍"这类比较**：lexical 的基线是 0.6667 / 0.6111，
cosine 的基线是 0.0833 / 0.1111，分母不同，相减没有意义——这是 `same-caliber-gain` 已经立法的不变式。

### 4. `mixed` 会损失增益，而且损失量可测

同一池、同一基线下的有效比较（预测值，来自实施前的上界估计）：

| 配置 | `sample` | `billing` |
|---|---|---|
| `mixed` (0.2 / 0.2 / 0.6) | +0.4167 | +0.5556 |
| `cosine_only` (0 / 0 / 1) | **+0.8167** | **+0.7222** |
| 损失 | **49%** | **23%** |

`base` 0.2 与 `authority` 0.2 在这里不是"留余量"，是主动加噪声——两者的信号都已被实测证否
（`base` 严格等价于融合顺序，`authority` 是分层过滤器）。
**所以主配置是 `cosine_only`，`mixed` 只作稳健性对照。**
预注册 `mixed` 而不写明它会损失 23%–49%，实施后看到它分数低会误以为 cosine 不如预期。

### 5. 这会推翻已归档结论 5 的装置前提，必须显式登记

结论 5 的命题是"三路融合的 top-1 低于 lexical 单路"，它建立在 `base + authority + status` 三项之上。
上界估计显示，换装置后同一池上 threeway 会从 0.30 / 0.08 跳到 0.90 / 0.83。

**这不是"结论错了"，是"它的装置前提变了"。** 但如果不登记，报告里那些数字会在换装置后变成
"没有标签的旧装置数字"，而读的人会以为它们在描述当前系统。

## What Changes

**1. 特征集：`status` 删除，`cosine` 加入**

| 结构 | 变更前 | 变更后 |
|---|---|---|
| `FeatureScores` | `base` / `condition` / `authority` / `status` | `base` / `condition` / `authority` / **`cosine`** |
| `RerankWeights` | `base` / `authority` / `status` | `base` / `authority` / **`cosine`** |
| `features`（结果文件） | `base` / `authority` / `status` | `base` / `authority` / **`cosine`** |

`condition` 仍是审计字段，不参与加权（本次不动）。
`status_score()` 保留为测量用映射（`test_effective_feature_count` 用它证明"池内无方差"），但不再进 `rerank`。

**2. 预注册权重：分两个阶段，`uniform` 保留为历史接口名**

**commit ① 阶段**（只换字段，不改数值）：

| 名字 | 权重 | 第三项是什么 |
|---|---|---|
| `uniform` | 0.4 / 0.3 / **0.3** | 临时乘 `cosine = 0.0` |
| `base_heavy` | 0.8 / 0.1 / 0.1 | 同上 |
| `auth_heavy` | 0.2 / 0.7 / 0.1 | 同上 |
| `status_only` | 0.2 / 0.1 / 0.7 | 同上 |

**第三项权重此刻是空的——和 `status` 时代一样空。这是刻意的**：
数值一字不改，于是 commit ① 的 diff 只有字段名，`rank_after_rerank` 必须逐条不变。
若在这一步顺手改数值，就无法回答"名次变化是删 `status` 引起的还是改权重引起的"。

**commit ③ 阶段**（数值与命名一起改）：

| 名字 | 权重 | 回答什么问题 |
|---|---|---|
| `uniform` | 0.2 / 0.2 / 0.6 | 默认配置。**名字是历史遗留，它从未在 v3 里"均匀"过** |
| `mixed` | 0.2 / 0.2 / 0.6 | 与默认同值；"给无信号项留余量会损失多少" |
| `cosine_only` | 0 / 0 / 1 | 只用有信号的特征能做到多好（上界，主配置） |

删除 `base_heavy` / `auth_heavy` / `status_only`——它们描述的"base 主导 / authority 主导 /
status 主导"三个轴里，`status` 已不存在，另两个已被证否为信号。
留着它们会让"预注册"看起来在做网格搜索，而实际只有一个有意义的轴（cosine 占多少）。

**`uniform` 与 `mixed` 是同值但不同职责**：`uniform` 是"默认"这个接口名，
`mixed` 是"留余量"这个语义名。两者当前同值，所以用**同一个数字源**定义它们
（一个常量喂两个键），避免两份数字各自漂移。

**为什么保留 `uniform` 而不改名**：`weights_name="uniform"` 有 48 处调用
（`lexical_only` 27 / `with_vector` 18 / `no_paths` 3）。

| 类别 | 处数 | 说明 |
|---|---|---|
| 把 `uniform` 的**具体数值**写进断言 | **4** | `test_rerank.py` 三元组、`test_defect18_authority` 三个数、`test_defects_20_21` 罚分关系、`diagnose_c4_leak` 一处 |
| 从 `result["weights"]` 反查表，不硬编码 | 若干 | `test_rank_recompute` / `_end_to_end` / `test_per_case_features` |
| **断言名次/分数** | **10 个函数** | `seh_at_k`、`rank_after_rerank`、`rerank_order_tags`、`attribution` 等 |
| 只依赖"名字存在且合法" | 其余 | `test_determinism` 要求两次一致、`test_fusion_cap` 只数 `path_returns`、`test_pool_vectors` 只看向量写入 |

**所以"改名"省下的不是 48 处，而是避免一次与判据无关的重命名**；
而"改数值"确实会让那 10 个函数里的部分变红——那是 commit ③ 的实测范围，
不是"随手改个常数"。

**但"它不均匀"必须写进 spec**，不能只写代码注释——`rerank.py` 的注释已经解释过三次，读者仍然误会过。

**3. 缺陷载体独立于预注册**

```python
# 缺陷 19/21 的载体：authority 仍有非零权重时，罚分能否推翻 base 优势
DEFECT18_WEIGHTS = RerankWeights(base=0.2, authority=0.2, cosine=0.6)
```

`test_q4_loses_to_unrelated_entries_on_authority` 与 `test_authority_penalty_equals_condition_bonus`
改为读这个常量，不再读 `PREREGISTERED_WEIGHTS[...]`。

**理由不是"改名"，是生命周期不同**：`PREREGISTERED_WEIGHTS` 随实验设计变，
`DEFECT18_WEIGHTS` 只在缺陷算术需要重新验证时变。绑在一起会让"换一组实验配置"意外地
改变"缺陷是否成立"。项目已有先例：`test_authority_weight_threshold_is_quantified` 就用独立权重。

算术（实测）：

| 载体 | `advantage` | `penalty` | 净差 | 缺陷 |
|---|---|---|---|---|
| 现状 `uniform` (0.4/0.3/0.3) | 0.0360 | 0.3000 | 0.2640 | 成立 |
| `DEFECT18_WEIGHTS` (0.2/0.2/0.6) | **0.0180** | **0.2000** | **0.1820** | **成立** |
| `cosine_only` (0/0/1) | 0.0000 | 0.0000 | 0.0000 | **被修** |

`d_base = 1.000 − 0.910` 保持写死在测试里（它是数据属性，不是权重属性）。

**3b. 两个 dataclass 加 `kw_only=True`**

`RerankWeights` 与 `FeatureScores` 都必须用关键字参数构造，位置参数 MUST 抛 `TypeError`。

**这不是清理，是防"静默移位"**：实测有 **7 处** `RerankWeights(0.4, 0.3, 0.3)` 位置参数调用
（全在 `tests/`，`src/` 0 处）。改字段后第三位从 `status` 变成 `cosine`，于是
`(0.4, 0.3, 0.3)` 变成 `base=0.4, authority=0.3, cosine=0.3`——
**不报错、和仍为 1、行为不变**，但代码里出现"像是特意配了 cosine 0.3"的假象。

`kw_only=True` 让这 7 处立刻 `TypeError`（实测报错含 `positional`），
修复从"人记得去查"变成"编译器指路"。

**影响面实测**：`RerankWeights` 位置参数 7 处、关键字 20 处；
`FeatureScores` 位置参数 **0 处**、关键字 17 处。
所以 `FeatureScores` 加 `kw_only` 是零成本预防（它的第 4 位同样从 `status` 变 `cosine`）。

**这是全项目唯一使用 `kw_only` 的 dataclass，理由必须写在代码里**：
`Check(...)` 等仍用位置参数且不改，因为它们的字段含义从未变过。
**"字段含义会变"才是理由，不是"位置参数不好"。**

**4. 向量召回同时返回候选与其余弦分**

新增 `recall_by_vector_scored`，返回 `list[tuple[MemoryItem, float]]`；旧签名 `recall_by_vector`
保留并投影（6 处调用方不受影响）。
**必须加断言**：`features_by_tag[*]["cosine"]` 等于该候选在向量路召回时的余弦分，
MUST NOT 在重排阶段重算——重算会引入第二次 embedding 调用，而两次调用的结果不保证逐位一致
（`AGENTS.md` 已登记该非确定性）。

**5. 结果文件新增 `cosine_gap` / `cosine_band`**

三态，不是布尔：`stable`（`gap >= 0.01`）/ `noise`（`0 <= gap < 0.01`）/ `negative`（`gap < 0`）。
负 gap 是"cosine 已排错"，与"可能翻转"处置相反，不能压成 `cosine_unstable`。

**6. 报告与测试的连带修改**

| 项 | 处置 |
|---|---|
| 结论 5 | **限定到三项装置**，不是修改；新装置结果另立为 5b（实施后测量） |
| 报告 §6 每个数字 | 标注产生它的权重配置；同一命题两套数字并列保留，MUST NOT 覆盖 |
| `test_rerank_never_improves_top1` | **降级为历史记录**（记录三项权重下 `billing` 2/12 → 1/12 的破坏），docstring 写明"结论只对三项装置成立" |
| `test_uniform_weights_are_the_preregistered_values` | 拆为"默认权重数值"+"缺陷载体独立"两条；原测试删除 |
| 2 处临时注册 `(0.4,0.3,0.3)` | `fusion_dilution` / `same_caliber` 要按新装置重测 |

`test_rerank_cannot_reorder.py` 的 `__v3` 权重（`0.4,0.3,0.3`）要删掉，只留 `__base`——
但**这条测试本身不改成 base-only**：`test_base_only_equals_fusion_top1` 已单独验证结构恒等，
把这条也改成 base-only 会让两条测试重复。它记录的是"三项权重下重排主动破坏了结果"，那个事实有独立价值。

## 对已归档结论的影响

这次变更**推翻了一个已归档结论的装置前提**，而它不是"数字更新"。逐条登记：

### 1. 结论 5（`fusion-dilution-conclusion`）：限定到三项装置

该结论的命题是"三路融合的 top-1 低于 lexical 单路"，
依据是配对后 `sample 5/6 vs 3/6`、`billing 8/9 vs 1/9`。

**这些数字全部产生于 `base + authority + status` 的三项装置。**
换装置后，同一池上 threeway 的预测值为 `0.90` / `0.83`（`sample` / `billing`），
而三项装置是 `0.30` / `0.08`。

**处置**：结论 5 不改写，**加装置限定**；新装置的结果另立 §6.14（5b）。
**不做的**：不把 5b 写成"结论 5 被推翻"——`billing` 的 `−0.0278` 是三项装置下的实测事实，
它仍然成立，只是不再描述当前系统。

### 2. `test_rerank_never_improves_top1`：降级为历史记录

它记录的 `billing` 2/12 → 1/12 是三项装置下的实测。加 cosine 后，
同一批 case 的 top-1 会显著上升，这条断言不再成立。

**处置**：保留测试与数字，改判据为"内联复现三项装置的公式"，docstring 写明"结论只对三项装置成立"。
**不做的**：不删除（它是"authority 主动破坏融合顺序"的唯一证据）、不改 base-only（会与
`test_base_only_equals_fusion_top1` 重复）。

### 3. 报告 §6 的每个数字：必须标注权重配置

现有 `0.3000 / 0.0833 / +0.2167 / −0.0278` **没有装置标签**。
加 cosine 后它们会变成"旧装置的数字"，而报告里没有任何东西提示这一点。

**处置**：给 §6 结论表加表头标签 `uniform-v3-three-features（0.4/0.3/0.3）`，
新数字标 `uniform-v3-cosine（0.2/0.2/0.6）`。这条同时成为一条 spec requirement
（「报告数字必须标注产生它的权重配置」）。

### 4. `test_handoff_v3_method.py:1888`：一条已存在的坏断言，处置是**删除**

```python
assert "w.condition" in p21, "缺陷 21 的加成必须用 w.condition"
```

**实测**：`test_defects_20_21.py` 里 `w.condition` 只出现 **1 次**，
位置是 docstring 第 100 行 `bonus = w.condition × 1.0`。
`RerankWeights` 从来没有 `condition` 字段。

**两条断言互相矛盾**：

| 位置 | 断言 | 状态 |
|---|---|---|
| `test_defects_20_21.py:121` | `not hasattr(w, "condition")` | ✅ 正确 |
| `test_defects_20_21.py:132-134` | 改 `condition` 不改变得分 | ✅ 正确 |
| `test_handoff_v3_method.py:1888` | `"w.condition" in p21` | ❌ 只匹配到 docstring |

**所以它是第 4 种（注释与实现不符）+ 第 1 种（永远绿）的复合**：
断言对象是注释，而注释记录的是一个已废弃的规则。

**处置：删除，不修成更强的判据。**

理由是它想守的事**已经有两个断言在守**：
"字段不存在"由 `:121` 守，"condition 不影响排序"由 `:132-134` 守。
再写一条 AST 判据，只会得到第三条守同一件事的测试。

**已实测删除的安全性**：直接删掉第 1888 行，跑全量 `pytest tests/ -q`：

```
1755 passed, 4 skipped, 5 deselected in 514.34s (0:08:34)
```

**无一红。** 所以它确实是冗余的，删掉不损失任何保护。

**为什么这也更符合项目惯例**：本项目对"结论不再适用"的既有做法是
**降级为历史记录**（如 `test_rerank_never_improves_top1`），而不是"换个更强的判据
继续当当前判据"。这条断言的规则已废弃，所以它该走"记录后移除"，不是"加固"。

**不做的**：不改 `test_defects_20_21.py` 的 docstring——它是历史记录。
删掉的那行在 HANDOFF 记一句"它曾守一个不存在的字段"。

**不做的**：不改 `test_defects_20_21.py` 的 docstring——它是历史记录。

## Capabilities

### New Capabilities

无。本次变更只修改既有能力，不引入新能力。

### Modified Capabilities

- `retrieval-apparatus`：排序特征集（`status` → `cosine`）；逐条特征分持久化的三键换名；离线复算的三权重组；新增"cosine 特征值必须等于召回分"
- `evaluation-harness`：结果文件的三特征换名；`v3 排序特征的能力边界必须可复算` 的特征表；新增"预注册命名的历史遗留条款"、"报告数字必须标注装置配置"、"缺陷载体必须独立于预注册"
- `memory-retrieval`：`四特征重排` 的特征列表与"状态惩罚"场景（OpenSpec 不允许丢弃既有场景，故场景名保留、内容改为事实）

## 本次不做什么（范围边界）

| 不做 | 理由 |
|---|---|
| 不改召回、融合（RRF）、去重、gate 阈值 | 本次只换一个排序特征；动它们会让"差异归因"失去唯一变量 |
| 不加第四特征（不保留 `status` 作观测字段） | spec 已判定恒常数字段不得保留在 `features` 里；保留就等于把已立法的规则绕过去 |
| 不删除 `uniform` 这个名字 | 48 处调用点里，改名只会产生与判据无关的 diff |
| 不新增 `results/*.json` | 顶层 48 个是分区约束；复算一律现场重跑（embedding 走缓存，不产生 API 调用） |
| 不把上界估计写成结论 | `cosine_only` 的 0.90/0.83 是手工重排算的，没经过 `run_retrieval`；它只能进 5b 的"预测"栏 |
| 不改 v3 数据 | 换装置后重测同一份数据，才让"装置变化"成为唯一变量 |
| 不改 `condition` 的审计地位 | 本次只动排序特征集；`condition` 已在 v3 退出加权，不在本次范围 |
| 不修 `test_handoff_v3_method.py:1888` 那条坏断言的**历史 docstring** | 删掉断言本身（已实测删除后全量 1755 passed）；缺陷 21 的原始记录保留 |
| 不给其它 dataclass 加 `kw_only` | 只给字段含义变过的 `RerankWeights` / `FeatureScores` 加。`Check` 等字段含义从未变过，不加 |

## 可独立验收的理由

三条 commit 各自有一个可判定的出口，且第一条是"零副作用"证明：

1. **结构 commit 后，全量测试绿，且所有名次逐条不变**——因为 `status` 恒 1.0，
   把它的 0.3 权重挪给一个恒为 0.0 的 `cosine` 不改变任何一对候选的相对顺序。
   这一条能把"字段改名"与"行为变化"彻底分开。
2. **填真 cosine 后，新增断言绿**（cosine 分等于召回分、`cosine_band` 三态覆盖、
   负 gap 与噪声带分开计数）。
3. **重测后，结论 5 的两套数字都在，且各自带装置标签**——覆盖旧数字会判为失败。

## Impact

**代码（3 个文件）**

| 文件 | 变更 |
|---|---|
| `src/memory/retrieval/rerank.py` | `FeatureScores` / `RerankWeights` 字段 + **`kw_only=True`**；`rerank` 加权式；`PREREGISTERED_WEIGHTS`；新增 `DEFECT18_WEIGHTS`；docstring 的"已删除的特征"表加 `status` |
| `src/memory/retrieval/vector.py` | 新增 `recall_by_vector_scored`；`recall_by_vector` 投影 |
| `evals/run_retrieval.py` | 特征构造点（`FeatureScores(...)`）；`features_by_tag`；`cosine_gap` / `cosine_band`；`recall_by_vector_scored` 接线 |
| `evals/tools/diagnose_c4_leak.py` | 1 处 `FeatureScores(...)` + 1 处 `status_score` |

**测试（约 50 处）**

> 下表数字是规划时用 AST 扫描得到的，**不是印象**。实施第一步（tasks 0.1）
> 会用同一套扫描重算一次；若与下表不符，先更新表再动手——否则就是"没有断言守着的数字"。

| 类别 | 数量 | 说明 |
|---|---|---|
| `FeatureScores(...)` 构造点 | **17 处** | `evals` 2 + `tests` 15（`src` 0：产品代码在 `evals` 里）；全部关键字 |
| `features` / `features_by_tag` 字典字面量 | **19 处 / 10 文件** | 只数含 `"base"` 键的真实特征字典；另有 5 处只含 `{"base"}` 或 `{"auth","base"}` 的**签名探测**用法，不受影响 |
| 依赖特征/权重**字段名**的断言 | **6 处** | 见下表 |
| 临时注册权重 | **7 处** | 全部是**位置参数**；`kw_only` 后必然 TypeError |
| `PREREGISTERED_WEIGHTS["uniform"]` 下标 | **9 处** | 2 处缺陷测试改读 `DEFECT18_WEIGHTS`；4 处在 `test_rank_recompute`，只依赖名字存在 |

**6 处字段名断言**（逐个点名，避免"大约几处"）：

| 位置 | 断言 |
|---|---|
| `test_per_case_features.py:73` | `set(features) == {"base","authority","status"}` |
| `test_rerank.py:123` | `w.status == 0.3`（随测试删除而消失） |
| `test_rerank.py:186` | `(weights.base, weights.authority, weights.status) == (1.0,0.0,0.0)` |
| `test_handoff_v3.py:76` | `fields == ["base","authority","status"]` |
| `test_rerank_three_weights.py:32` | `fields == {"base","authority","status"}` |
| `test_rerank_three_weights.py:43` | `fields == {"base","condition","authority","status"}` |

**48 处 `weights_name="uniform"` 调用的依赖类型**（也实测过）：

| 类别 | 处数 |
|---|---|
| 把数值写进断言 | 4 |
| 断言名次/分数（`seh_at_k` / `rank_after_*` / `attribution` 等） | 10 个函数 |
| 从 `result["weights"]` 反查表，不硬编码数值 | 若干 |
| 只依赖"名字存在且合法" | 其余 |

**文档**

- `docs/reports/v2-what-it-measures.md`：§6 全部数字加装置标签；§6.12.5 的四步计划改为"已实施"；
  新增 5b。
- `docs/HANDOFF.md`：装置描述（"排序特征 = 3（base/authority/status）"）与 §0.8 的
  `uniform.status = 0.25` 前提表。

**不影响**：数据集、`results/` 顶层文件数（仍 48）、embedding 缓存、LLM 网关。
