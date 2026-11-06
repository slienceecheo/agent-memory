# Design

## Context

见 `proposal.md` 的 Why。这里只记录塑造方案的现状与约束。

**当前代码的四处接口**

| 位置 | 现状 |
|---|---|
| `src/memory/retrieval/rerank.py:42-80` | `RerankWeights(base, authority, status)`；`PREREGISTERED_WEIGHTS` 四组，均 0.4/0.3/0.3 类结构 |
| `src/memory/retrieval/rerank.py:124-129` | `FeatureScores(base, condition, authority, status)` |
| `src/memory/retrieval/vector.py:58` | 已有 `score = dot / (norm × candidate_norm)`，但算完就丢，只返回 `MemoryItem` |
| `evals/run_retrieval.py:772` | `FeatureScores(...)` 唯一的产品构造点；`:763` 是 `features_by_tag` 的写入点 |

**测试面（AST 实测）**

- `FeatureScores(...)` 构造 **17 处**（`evals` 2 + `tests` 15；`src` 里没有——产品构造点在 `evals`）
- `features` / `features_by_tag` 真实字典 **19 处 / 10 文件**
  （另有 5 处 `{"base": ...}` 单键的**签名探测**用法，不参与特征集，不受影响）
- 依赖字段名的断言 **6 处**（proposal 的 Impact 表逐个点名）
- `weights_name="uniform"` 调用 **48 处**（`lexical_only` 27 / `with_vector` 18 / `no_paths` 3）
- `PREREGISTERED_WEIGHTS["uniform"]` 下标 **9 处**
- 临时注册权重 **7 处**

**约束**

- `openspec/specs/evaluation-harness/spec.md` 的「恒常数字段不得作为排序特征」已经判定 `status` 要删。
  本次是执行既有规范，不是新增判断。
- embedding 非确定性已登记（`AGENTS.md`）：同文本重复调用可能给出不同向量。
  所以 cosine 分必须**从召回路径带出来**，不能在重排时重算。
- `results/*.json` 顶层必须保持 48 个；报告数字一律现场重跑复算（embedding 走缓存）。

## Goals / Non-Goals

**Goals**

1. `status` 从加权与 `features` 中移除，且**证明移除不改变任何名次**（它恒 1.0）。
2. `cosine` 的三处取值（召回分、`features_by_tag`、加权用分）**是同一个数**。
3. 换权重/换装置后，报告里的旧数字仍然可读、可追溯。
4. 缺陷 19/21 的验证与"预注册了哪些配置"解耦。

**Non-Goals**

1. 不重新设计召回或融合。`rrf_norm`、`FUSION_CAP`、dedup 位置一律不动。
2. 不给 `cosine` 做归一化或校准。它是原始余弦，值域 `[-1, 1]`；只对负值做 `max(0, x)` 截断到 `[0,1]`（见决策 D3）。
3. 不引入 ANN 或新的向量库。
4. 不在本次把 `uniform` 改名。改名是纯噪声 diff，且 47/48 处调用与名字无关。
5. 不把上界估计（0.8167 / 0.7222）写成结论；它只能作为 5b 的预测栏。

## Decisions

### D1. 先删 `status` 再加 `cosine`，而不是"用 cosine 顶掉 status 的位置"

**做法**：`FeatureScores.base / condition / authority / cosine`；`RerankWeights.base / authority / cosine`。
**两个 dataclass 都加 `kw_only=True`**（决策见 D1b）。

**为什么不是"就地替换"**：两者数量相同，但语义不同。
`status` 的 0.3 权重是**空转**，`cosine` 的权重是**有效信号**。
如果把"删掉空权重"和"加一个真信号"混在一个 commit 里，
`git bisect` 无法回答"名次变化是删 status 引起的还是加 cosine 引起的"。

**否决的备选**：

| 备选 | 否决理由 |
|---|---|
| 保留 `status` 作第 4 个观测字段 | spec 已判定恒常数字段不得作为观测保留；保留就是绕过已立法的规则 |
| 保留 `status` 但权重设 0 | 权重和恒为 1，给一个恒 1.0 的字段零权重等于缩小其余三项的可分配空间，且读代码的人会以为它在起作用 |
| 加 `cosine` 作第 5 个字段（`base/condition/authority/status/cosine`） | 四权重结构又要扩成五权重，权重和仍为 1；且 `status` 仍在消耗权重 |

**怎么测**：commit ① 之后跑**改前 vs 改后自身快照**的比对（tasks 0.0 / 0.3 / 2.11），
`rank_after_fusion` / `rank_after_rerank` / `rerank_top1_tag` / `fusion_tags` 四项差异必须全为 0。
**不能用 `test_a5_regression`**：它比的是冻结的 v2 四特征归档，上限是 ≤20%，差异 0 在那里不可能达到。
因为 `cosine` 此时全是 0.0，`status` 全是 1.0，两者对相对顺序的贡献都是常数。

### D1b. 两个 dataclass 加 `kw_only=True`，让"字段移位"变成 TypeError

```python
@dataclass(frozen=True, slots=True, kw_only=True)
class RerankWeights:
    base: float
    authority: float
    cosine: float

@dataclass(frozen=True, slots=True, kw_only=True)
class FeatureScores:
    base: float
    condition: float
    authority: float
    cosine: float
```

**问题**：全仓库有 **7 处** `RerankWeights(0.4, 0.3, 0.3)`（位置参数，已实测，
全部在 `tests/`，`src/` 0 处）。改字段后第三位从 `status` 变成 `cosine`，
于是 `(0.4, 0.3, 0.3)` 变成 `base=0.4, authority=0.3, cosine=0.3`：
**不报错、和仍为 1、行为不变**（因为 cosine 恒 0.0，所以第三项仍空转），
但代码里出现一个"像是特意配了 cosine 0.3"的假象，后续 commit 会误读它。

**为什么不用"审计这 7 处"**：审计可以漏——新增一处就漏一次，而且漏了不会失败。
`kw_only=True` 让这 7 处**立刻** `TypeError: takes 1 positional argument but 4 were given`
（实测确认报错文本含 `positional`）。于是修复从"人记得去查"变成"编译器指路"。

**实测影响面**：

| 项 | 数量 | 影响 |
|---|---|---|
| `RerankWeights` 位置参数构造 | **7 处**（全在 tests） | 必须改 |
| `RerankWeights` 关键字构造 | 20 处 | 不受影响 |
| `FeatureScores` 位置参数构造 | **0 处** | 不受影响（预防性加 `kw_only`） |
| `FeatureScores` 关键字构造 | 17 处 | 不受影响 |
| `disabled_weights()` / `PREREGISTERED_WEIGHTS` | 全部关键字 | 不受影响 |

**为什么 `FeatureScores` 也要加**（虽然它 0 处位置参数）：
它的第 4 位同样从 `status` 变成 `cosine`。
今天没有位置参数调用，是**运气**，不是设计。

**但更硬的理由是：`FeatureScores` 的字段顺序与产物键序本来就不一致。**

| 位置 | `FeatureScores` 字段 | `features_by_tag` 键 |
|---|---|---|
| 1 | `base` | `base` |
| 2 | **`condition`** | **`authority`** |
| 3 | `authority` | `cosine` |
| 4 | `status` | —（`condition` 不在这里） |

`condition` 夹在第 2 位，而它在产物里根本不进 `features`。
所以任何"按位置对应"的代码**本来就是错的**——不是"改字段后才错"。
`kw_only` 让这种错误从"静默错位"变成"构造即报错"。

这比"第 4 位变过"更根本：**位置参数在 `FeatureScores` 上从来就没有过正确的用法。**

**否决的备选**：

| 备选 | 否决理由 |
|---|---|
| 只审计 7 处，不加 `kw_only` | 新增一处就再漏一次；漏了不失败，属于静默失效 |
| 只给 `RerankWeights` 加 | `FeatureScores` 的第 4 位同样在变，同型风险只修一半 |
| 保留位置参数但改字段顺序（把 `cosine` 放第 1 位） | 字段顺序有意义（`base` 是主信号）；为兼容位置参数改语义顺序是本末倒置 |

**这与项目其它 dataclass 不一致，必须写明理由**：
`Check("F24", "A 轴未饱和", True, ...)` 等仍用位置参数，而且**不改**。
区别是：`Check` 的五个字段含义从未变过；
`RerankWeights` 的第三位变过**两次**（`condition` → `status` → `cosine`），
`FeatureScores` 的第四位也变过（`status` → `cosine`）。
**"字段含义会变"才是 `kw_only` 的理由，不是"位置参数不好"。**
这句话要写进 `rerank.py` 的注释，否则下一个人会问"为什么只有它"。

### D2. `recall_by_vector_scored` 返回 `(item, score)`，旧签名投影

```python
def recall_by_vector_scored(store, query_vector, *, limit=20) -> list[tuple[MemoryItem, float]]: ...
def recall_by_vector(store, query_vector, *, limit=20) -> list[MemoryItem]: ...
```

**为什么不是改 `recall_by_vector` 的返回类型**：它有 6 处调用方
（`test_recall.py`、`test_pipeline.py`、`test_l6c_paths_return_data.py`、`test_recall_active_only.py`、`run_retrieval.py`），
全部只想要 `MemoryItem`。改返回类型会让 6 处同时改，而其中 5 处完全不需要分数。

**为什么不是"重排时再算一次 cosine"**：`AGENTS.md` 已登记 embedding 非确定性
（未命中缓存时 `cos = 0.9971`，跨变体 0.9976）。重算会引入第二次调用，
于是"排序用的 cosine"与"记录的 cosine"可能是两个数，
而差异只在缓存未命中时出现——正好是最难归因的形态。

**否决的备选**：

| 备选 | 否决理由 |
|---|---|
| 返回 `dict[str, float]`（id → score） | 调用方还要再 `store.get()`，多一次往返；且顺序信息丢失 |
| 给 `MemoryItem` 加 `score` 字段 | 污染存储模型，那个模型有 fingerprint（`test_fingerprint.py`），加字段会改指纹 |
| 重排时重算 | 见上，引入非确定性 |

**怎么测**：新增断言"`features_by_tag[tag]["cosine"]` 等于独立调用 `recall_by_vector_scored` 得到的分数"。
必须**独立调用一次**再比，不能用 `features_by_tag` 自比（那是恒真）。

### D3. `cosine` 截断到 `[0,1]`，不是映射

`rerank._validate` 要求所有特征落在 `[0,1]`。余弦的理论值域是 `[-1,1]`。

**做法**：`cosine = max(0.0, raw_cos)`。

**为什么不是 `(raw + 1) / 2`**：那会把"毫无关系"（0.0）变成 0.5，
而 0.5 在加权里与"中等相似"不可区分。截断保留"0 = 无信号"这个语义，
与 `authority_score(THIRD_PARTY) = 0.0` 的处理一致。

**代价**：负余弦的候选之间失去区分度（全部变 0）。
**实测这在 v2 数据上没有影响**：最低的 gold cosine 是 0.4517（`billing`），
干扰项最低也在 0.2 以上（分布重叠判据已记录 `min(gold) < max(dist)`）。
若 v3 数据出现负余弦，这条截断要重新评估。

**怎么测**：`test_cosine_feature_is_truncated_to_unit_interval`——
构造一对 `raw = -0.3` 与 `raw = -0.9` 的候选，断言两者 `cosine` 都是 0.0；
再构造 `raw = 0.5`，断言 `cosine == 0.5`（不是 0.75）。

### D4. 缺陷载体是独立常量，不是预注册的一项

```python
DEFECT18_WEIGHTS = RerankWeights(base=0.2, authority=0.2, cosine=0.6)
```

**为什么是 `0.2/0.2/0.6` 而不是别的**：缺陷 19 的成立条件是
`w.authority × (1 − 0) > w.base × (1.000 − 0.910)`，即 `w.authority > 0.09 × w.base`。
`0.2 > 0.09 × 0.2 = 0.018`，成立且余量 11 倍。
同时 `authority` 必须 `> 0`——这是缺陷能被验证的前提。

**为什么 `DEFECT21_WEIGHTS` 不需要单独存在**：缺陷 21 的原等式
（`penalty == bonus`）在 v3 已经**失去对象**（`condition` 没有权重）。
`test_authority_penalty_equals_condition_bonus` 保留的是"罚分仍压倒 base 优势"这个观察，
与缺陷 19 是同一个结构断言、同一组算术。给它们两个同值常量只会让读者以为
"这里有两个不同的缺陷需要不同的权重"。

**否决的备选**：

| 备选 | 否决理由 |
|---|---|
| 读 `PREREGISTERED_WEIGHTS["mixed"]` | 生命周期耦合：删掉 `mixed` 会让缺陷验证静默失效 |
| 在测试里写 `RerankWeights(0.2, 0.2, 0.6)` 字面量 | 与 `test_handoff_v3_method` 的"不许抄常量"冲突；且无法被"载体独立"断言检查 |
| 用现状 `uniform` 的 `0.4/0.3/0.3` | 那是已废弃的三项装置；用它会掩盖"换装置后缺陷是否仍成立"这个问题 |

**怎么测**：
1. `test_defect18_numbers_match_weights`：用 `DEFECT18_WEIGHTS` 算出 `0.0180 / 0.2000 / 0.1820`。
2. `test_defect18_carrier_is_independent_of_preregistered`：**行为断言，不是值断言**。
   暂时把 `PREREGISTERED_WEIGHTS` 里每一项都改成 `RerankWeights(1.0, 0.0, 0.0)`，
   再重算缺陷算术，断言 `0.0180 / 0.2000 / 0.1820` 三个数**一字不变**；跑完恢复原表。
3. 结构断言 `penalty > advantage` 单独存在，与数值断言分离。

**为什么不能写 `DEFECT18_WEIGHTS != PREREGISTERED_WEIGHTS["mixed"]`**：
两者当前都是 `0.2/0.2/0.6`——**这个断言在正确的实现上也会红**。
值相等是设计意图（应答同一个算术问题），耦合与否是**读取路径**的问题，
只有"改掉预注册表而缺陷数字不变"这个行为能区分两者。
这是"断言两个东西不同、但构造时又让它们相等"的形态，必须避免。

### D5. `uniform` 保留为历史接口名；数值改动推到 commit ③

**commit ① 只改字段名，数值一字不动**：

```python
PREREGISTERED_WEIGHTS = {
    "uniform":    RerankWeights(0.4, 0.3, 0.3),   # 第三项此刻是 cosine=0.3 -> 空转
    "base_heavy": RerankWeights(0.8, 0.1, 0.1),
    "auth_heavy": RerankWeights(0.2, 0.7, 0.1),
    # status_only 删除：名字指向已不存在的特征
}
```

**`status_only` 在这一步就删，不改成 `cosine=0.7`**：它的名字含义是"status 主导"，
而 `status` 已不是特征。改名成别的会变成一个新配置（那是决策，不是机械替换）。
实测删它不影响任何测试——`test_report_consistency.py` 里的 `"status_only"` 是**文件名片段**
（拼 `results/retrieval-independent-status_only-...json`），不查 `PREREGISTERED_WEIGHTS`。

**commit ③ 才换成最终形态**：

```python
_DEFAULT = RerankWeights(0.2, 0.2, 0.6)
PREREGISTERED_WEIGHTS = {
    "uniform": _DEFAULT,                          # 历史遗留接口名
    "mixed": _DEFAULT,                            # 语义名，同值
    "cosine_only": RerankWeights(0.0, 0.0, 1.0),  # 主配置（上界）
}
DEFECT18_WEIGHTS = RerankWeights(0.2, 0.2, 0.6)
```

**为什么必须分两步**：commit ① 的门禁是"所有名次逐条不变"。
而 `uniform` 从 `0.4/0.3/0.3` 变成 `0.2/0.2/0.6` 会**改变排序**——
`base` 权重从 0.4 降到 0.2，`authority` 从 0.3 降到 0.2。
若在 commit ① 同时改数值，`rank_after_rerank` 差异率不再为 0，
"删 `status` 没有副作用"这件事就无法被证明。

**commit ① 里第三项是空转，这不矛盾**：`cosine = 0.0`，所以 `0.3 × 0.0 = 0`。
与 `status` 时代 `0.3 × 1.0 = 0.3`（全池常数）在**相对顺序上等价**。
两者都不改变任何一对候选的先后，这正是门禁能成立的原因。

**`uniform` 与 `mixed` 用同一个常量喂两个键**，避免两份数字各自漂移。
但保留两个键：`uniform` 是"默认"这个接口，`mixed` 是"留余量"这个语义。
单键会让"哪天默认改了"自动改掉语义名，而它们的生命周期本就不同。

**为什么删 `base_heavy` / `auth_heavy` / `status_only`**：三者分别描述
"base 主导 / authority 主导 / status 主导"。`status` 已不存在，
`base` 与 `authority` 都已被证否为信号（前者恒等于融合顺序，后者是分层过滤器）。
保留它们会让"预注册"看起来在做 7 组网格搜索，而实际只有一个有意义的轴。

**`test_preregistered_count_is_five` 不改**：它断言 `len <= 5`，3 组仍然绿。
删掉它等于失去"不超过 5 组"这条纪律的记录。

**怎么测**：
1. `test_default_weights_are_the_preregistered_values`：`PREREGISTERED_WEIGHTS["uniform"]`
   的三元组 == `(0.2, 0.2, 0.6)`。替代被删除的 `test_uniform_weights_are_the_preregistered_values`。
2. `test_preregistered_names_describe_questions`：名字集合恰好是
   `{"uniform", "mixed", "cosine_only"}`。
3. `test_preregistered_weights_exist_and_sum_to_one` 已有，不变。

### D6. `test_rerank_never_improves_top1` 降级，不删除、不改 base-only

**做法**：保留测试与断言，改 docstring 与失败消息，写明"这条记录的是三项装置下的实测事实"。

**为什么不能删**：它记录的 `billing` 2/12 → 1/12 是"authority 分层主动破坏融合顺序"的
唯一量化证据。那是"为什么必须删 authority 权重"的依据，删了就没有出处。

**为什么不能改成 base-only**：`test_base_only_equals_fusion_top1` 已经断言
"base-only top-1 == 融合 top-1"。再改一条 base-only 就是**两条测试守同一件事**，
而它们会一起绿、一起红，无法区分是哪一层坏了。

**怎么做**：删掉 `__v3` 这个临时权重，改成**从产物内联复现历史公式**。

`features_by_tag` 在 `run_retrieval` 里是**与权重无关**地写出来的
（它记录融合后整池候选的每个特征，和用哪组权重排序无关）。
所以只要用任意一组合法权重跑一次 `evaluate`，就拿到了 `base` / `authority`，
再补上历史装置里恒为 1.0 的 `status`：

```python
# 三项装置的历史公式，不经过现行 rerank()
score = 0.4 * base + 0.3 * authority + 0.3 * 1.0
```

排序后按 `fusion_tags` 的位置破并列——**与 `recompute_order` 的两步裁决同构**，
只是权重与特征集是历史值。

**为什么这样能精确复现**：`status_score(ACTIVE) = 1.0`，所以 `0.3 × 1.0` 是
加在所有候选上的同一个常数。加常数不改变任何一对候选的相对顺序，也不改变并列结构。
**这正是这条测试要记录的事实本身**：三项装置里那个第三项是空转的。

**并且这条前提必须被断言**：测试开头断言"当前池里每条候选的 `status_score` 都是 1.0"
（直接读 `features_by_tag` 覆盖不到的 store 层，或用 `_STATUS_SCORE[ACTIVE] == 1.0` +
数据集 status 集合 == `{ACTIVE}`）。若哪天这个前提破了，历史复现就不再成立，
测试必须红而不是给出一个看似合理的新数字。

**否决的备选**：

| 备选 | 否决理由 |
|---|---|
| 删掉整条测试 | 丢失"authority 主动破坏"的唯一证据 |
| 改成 base-only | 与 `test_base_only_equals_fusion_top1` 重复 |
| 加 `pytest.mark.skip` | 跳过 = 不执行，记录价值归零；且 `skip` 会被当成"暂时" |
| 保留临时注册 `RerankWeights(0.4, 0.3, 0.3)` | 换字段后第三项是 `cosine`，于是"历史三项装置"变成"cosine 占 0.3"，名不符实 |
| 新增独立的三项 `RerankWeights` 类 | 为一个已废弃的装置维护第二套代码路径；内联公式只需 3 行 |

### D7. 报告双套数字并列，靠"装置标签"而不是"日期"区分

**做法**：结论 5 的表头写装置名，5b 另起一节。

| 节 | 装置 | 数字来源 |
|---|---|---|
| §6（结论 5） | `uniform-v3-three-features`（0.4/0.3/0.3） | 已归档实测 |
| §6.14 新增（5b） | `uniform-v3-cosine`（0.2/0.2/0.6） | 实施后实测 |

**为什么用装置名而不是"旧/新"**：`旧` 与 `新` 随时间失效——三个月后读的人不知道
"新"指哪一次。装置名可反查到 `PREREGISTERED_WEIGHTS` 的具体一行。

**为什么不是"重跑并覆盖"**：覆盖会丢失"装置变化带来了多少差异"这个信息，
而那正是"加 cosine 值不值得"的唯一内部证据。

**怎么测**：`test_report_numbers_carry_apparatus_label`——
定位到 §6.5.1 那张表的表头行，断言表头含装置标签；
再定位到 §6.14 的表头，断言标签与 §6 不同。

**为什么不在本次引入 `v3c-*` 文件名前缀**：文件名约定必须同时改
`run_retrieval` 的输出命名、`result_files()` 的扫描、以及所有按
`retrieval-{split}-{weights}...` 拼路径的测试（`test_a5_regression` / `test_report_consistency` /
`test_archive_evidence` 至少 3 处）。那是一次与"加一个排序特征"无关的改动，
会把本次的三个 commit 撑成五个。
**代价是已知的**：本次产出的 v3 结果文件与旧 v3 结果文件在机器眼里同代。
所以报告标签是**人读的权威标注**，且 D7 的断言只守表头，不守文件名。
若将来要机器区分，必须另开一个只改命名的变更——**登记在这里，不悄悄留着**。

## Risks / Trade-offs

| 风险 | 影响 | 缓解 |
|---|---|---|
| **commit ① 后名次意外变化** | 说明 `status` 不恒 1.0，或 `cosine=0.0` 没有被真正置零 | 用**改前 vs 改后自身快照**的门禁（`rank_after_fusion` / `rank_after_rerank` / `rerank_top1_tag` / `fusion_tags` 四项差异全为 0）；**不用 `test_a5_regression`**——它比的是冻结的 v2 四特征归档，上限是 ≤20%，差异 0 在那里不可能达到。红了先查 `status` 池内方差，不要先改断言 |
| **`apparatus_signature` 分不出这两代 v3** | **后果：一份 v3 产物在机器眼里无法判断是"三项装置"还是"cosine 装置"。** 若将来出现"同一份结果、两种装置"的争议，只能靠人读报告表头裁决；而 `F20`/`F24` 这类门禁只判 `v2`/`v3`，对两代 v3 都执行同一套阈值——**装置换代的阈值变化不会被门禁发现** | `apparatus_signature` 的判据是"有没有 `features` 键"，两代 v3 都有。**本次不改它**（改它会破坏 `CURRENT_APPARATUS == "v3"` 与所有 `v3` 门禁）。补救：报告表头 MUST 标注权重配置（D7 的断言守表头）；**并登记下一步的产物命名约定 `v3c-*`（`c` = cosine）——但本次不实施**，理由见下方"为什么不是现在做" |
| **`cosine` 与召回分不逐位相等** | 复算验收会以无法归因的方式失败 | D2 的独立比对断言；且 `cosine` 只从 `recall_by_vector_scored` 带出，重排里不做任何重算 |
| **`max(0, x)` 让负余弦全部变 0** | 若 v3 数据出现负余弦，负值候选之间失去区分度 | 实测 v2 最小 gold cosine 是 0.4517，干扰项也全为正；`test_cosine_feature_is_truncated_to_unit_interval` 断言截断行为，若数据变化需重新评估 |
| **`sample` 的噪声余量只有 55%** | 若 embedding 模型升级，噪声可能超过最小 gap，`stable` band 失效 | 噪声边界测试已存在（`test_cosine_band.py`）；模型变更时它会红，届时重测而不是调阈值 |
| **`billing` 只有 2 个干扰项，`rho` 统计力弱** | "cosine 有信号"的结论强度有限 | 报告已登记为"未发现 gold 检测器特征"（弱），不写成"证明"；本次不改这个表述 |
| **测试改动 47 处，一次 commit 无法评审** | 评审者无法逐行确认 | 分 3 个 commit，每个都有独立出口（见 Migration Plan） |
| **`uniform` 与 `mixed` 同值** | 读者以为它们是同一个东西 | spec 里写明两者回答不同的问题；断言 `!=` 常量而不是 `!=` 对象 |
| **报告 5b 的数字是"预测"不是"实测"** | 读者当成结论引用 | 5b 表头写"上界估计（手工重排，未经 `run_retrieval`）"；实施后才填实测栏 |

## Migration Plan

三个 commit，每个结束后跑全量。**顺序不能换**。

**commit ①：结构（零行为变化）**

| 改动 | 数量 |
|---|---|
| `FeatureScores` 删 `status` 加 `cosine`；`RerankWeights` 同 | 2 个 dataclass |
| `rerank()` 加权式；`_validate` 字段名 | 2 处 |
| `PREREGISTERED_WEIGHTS` 换成 3 组；新增 `DEFECT18_WEIGHTS` | 1 个 dict + 1 个常量 |
| `run_retrieval.py:763,772` 写 `cosine=0.0` | 2 处 |
| `diagnose_c4_leak.py` | 1 处构造 |
| `FeatureScores(...)` 测试构造 | 15 处 |
| `features` / `features_by_tag` 字典字面量 | 19 处 |
| 字段名断言 | 6 处 |

**出口**：全量绿，且 `rank_after_rerank` 逐条不变。

**commit ②：填真 cosine + 新字段**

| 改动 | 数量 |
|---|---|
| `vector.py` 加 `recall_by_vector_scored`，旧函数投影 | 1 个新函数 |
| `run_retrieval.py` 接线，`cosine` 填真值 | 1 处 |
| `cosine_gap` / `cosine_band` 写入 `per_case` | 2 个字段 |
| 新增断言（D2/D3/band 三态） | 5 条 |

**出口**：`features_by_tag[*]["cosine"]` == 独立召回的分数；`cosine_band` 三态都被用到；
`per_case` 顶层键数从 30 变 32（+2 字段）。

**commit ③：重测与报告**

| 改动 | 数量 |
|---|---|
| `test_fusion_dilution` 的 `__concl5` 换成新装置 | 1 处 |
| `test_same_caliber` 的 `__cal` 换成新装置 | 1 处 |
| `test_rerank_cannot_reorder` 删 `__v3`，改用 D6 的内联历史公式 | 1 处 |
| 报告 §6 表头加装置标签；新增 §6.14（5b） | 2 处 |
| `HANDOFF.md` 装置描述与 §0.8 前提表 | 2 处 |

**出口**：两套数字都在，各自带标签；覆盖旧数字会红。

**回滚**：`git revert` 对应的一个 commit 即可。三个 commit 之间没有共享的状态迁移，
`results/` 无新增文件，`data/` 未改。

## 怎么被测量

| 设计决定 | 对应指标 |
|---|---|
| D1 先删后加 | **自身前后快照**的 `rank_after_rerank` / `rank_after_fusion` / `rerank_top1_tag` / `fusion_tags` 差异数（commit ① 必须全为 0）。**不用 `test_a5_regression`**：它比的是冻结的 v2 四特征归档，允许 ≤20% |
| **D1b `kw_only`** | **新增一处 `RerankWeights(0.4, 0.3, 0.3)` 会 `TypeError`**（实测报错文本含 `positional`）。判据是"构造抛错"，不是"扫描 0 命中" |
| D2 分数从召回带出 | `features_by_tag[*]["cosine"]` 与独立召回分的逐位相等数（必须全等） |
| D3 截断到 `[0,1]` | `test_cosine_feature_is_truncated_to_unit_interval` 的 3 个取值 |
| D4 载体独立 | `DEFECT18_WEIGHTS` 算出的 `0.0180 / 0.2000 / 0.1820` + 结构断言 |
| D5 默认权重 | `PREREGISTERED_WEIGHTS["uniform"]` 的三元组 |
| D6 历史记录 | `test_rerank_never_improves_top1` 的 `billing` 1/12（不变） |
| D7 双套数字 | §6 与 §6.14 的表头标签不同的断言 |
