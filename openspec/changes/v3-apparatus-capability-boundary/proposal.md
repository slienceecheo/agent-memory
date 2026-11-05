## Why

**实测确认：v3 的三个排序特征里没有一个承载"语义相关性"。**

这不是缺陷报告，是**能力边界**。它决定了 v3 能回答什么问题，以及数据侧**不得做什么**。

| 特征 | 实测性质 | 依据 |
|---|---|---|
| `status` | **恒为常数** | 候选池内方差 0/10、0/12 |
| `base` | **等于融合顺序** | `rrf_norm` 严格单调（实测），按 base 排 = 按 fusion_score 排 |
| `authority` | **分层过滤器，层内由融合顺序裁决** | 22 个 case，同层逆序 **0** 个 |

所以 v3 的 rerank 层最多做到"融合顺序 + 元数据先验"，**不含语义相关性信号**。

## 三个实测结论（都可复现）

### 1. `status` 恒为常数

```
记忆库的 status 取值：sample {'ACTIVE'}  billing {'ACTIVE'}
候选池内 status 有方差：0/10、0/12
```

原因是召回只返回 ACTIVE 条目。所以 `uniform` 里分给 status 的 0.3 权重**是空的**。

**验证方式**：保持 `base:authority` 比例不变，只加 status：

```
D  (0.50/0.50/0.00) -> sample 0.3000  billing 0.1667
E  (0.45/0.45/0.10) -> sample 0.3000  billing 0.1667   逐条相同
F  (0.35/0.35/0.30) -> sample 0.3000  billing 0.1667   逐条相同
```

**E、F 与 D 逐条相同**——status 完全中性，不是"权重被稀释"。

> 注意：我最初对比 (0.5,0.5,0) 与 (0.4,0.3,0.3) 得出"加 status 有害"，
> 那是错的：`base:authority` 从 1:1 变成了 4:3，变化来自**再分配**。修正后的对照如上。

### 2. `base` 等于融合顺序

```
rrf_norm 输入 [0.0, 0.1, 0.5, 1.0, 2.0, 5.0]
rrf_norm 输出 [0.0, 0.02, 0.1, 0.2, 0.4, 1.0]   严格单调递增
```

`rrf_norm` 是融合分的**严格单调变换**，所以"按 base 排序"与"按融合顺序排"是同一个顺序。

**因此 `base-only` 的 ratio 不是"base 拖后腿"，而是融合顺序本身的 top-1 率**：

```
sample  2/10 = 0.2000     billing 2/12 = 0.1667
```

融合是 lexical + vector + adjacency 三路**召回**的产物。
**它测的是召回质量，不是重排能力。**

### 3. `authority` 是过滤器，不是信号

实测 22 个 case（sample 10 + billing 12）：

| 量 | sample | billing |
|---|---|---|
| gold 唯一最高 authority | **0/10** | **0/12** |
| gold 与他人并列最高 | 8/10 | 10/12 |
| gold 低于最高 | 2/10 | 2/12 |
| gold mean − distractor mean | **−0.0244** | **+0.0213** |
| 同层逆序的 case 数 | **0/10** | **0/12** |

**"同层逆序 0"是关键判据**：在 auth-only 下，同一 authority 层内部各条目的相对顺序
与融合顺序**完全一致**。所以 authority 的全部作用是**把低层推到高层之后**，
层内裁决仍由融合顺序完成。

`auth-only` 的 0.40 / 0.17 从哪来：它不是"authority 选中了 gold"，
而是"低 authority 的干扰项被推到后面，gold 在剩余项里靠融合顺序恰好靠前"。

**sample 上 gold 的平均 authority 比干扰项还低（−0.0244）**——
它不是靠"更有权威"赢的。

## What Changes

**1. 新增 `tests/retrieval/test_v3_capability_boundary.py`**

| 断言 | 判据 |
|---|---|
| `test_status_has_no_variance_in_pools` | 池内 status 方差 == 0 |
| `test_rrf_norm_is_strictly_monotonic` | base 排序 == 融合顺序 |
| `test_authority_is_a_filter_not_a_signal` | 同层逆序 == 0（22 个 case） |
| `test_gold_authority_has_no_systematic_advantage` | `|mean_gold − mean_distractor| < 0.05` |
| `test_no_case_has_gold_as_unique_top_authority` | 唯一最高 == 0/22 |

**2. v3 数据侧的禁止事项（写成断言）**

| 禁止 | 理由 |
|---|---|
| MUST NOT 为了让增益出现而让 authority 与 gold 相关 | 那是重造 v2 的 condition 直通 |

**这条是本变更最重要的一条。** 详见 design.md 决策 2。

**3. 明确 v3 的预期增益 ≈ 0，且这个 0 可解释**

不是因为"装置坏了"，而是因为三个特征都不含语义相关性。

## Impact

- 代码：**无**
- 测试：新增 `test_v3_capability_boundary.py`
- 文档：HANDOFF §0 增加"v3 能力边界"一段
- 数据 / 结果文件：**无**

## 验收

| # | 判据 | 可被违反的形式 |
|---|---|---|
| 1 | 池内 status 方差 | 必须为 0（若 >0，说明召回不再只返回 ACTIVE） |
| 2 | `rrf_norm` 单调性 | 必须严格递增（若平了，base 会引入并列） |
| 3 | auth-only 同层逆序 | 必须为 0（若 >0，authority 含额外信号） |
| 4 | `|mean_gold − mean_distractor|` | 必须 < 0.05（若超，说明数据里有 authority 泄漏） |
| 5 | gold 唯一最高 authority 的 case 数 | 必须为 0（若 >0，任务退化成"选权威最高"） |
| 6 | 人工制造 authority 与 gold 的相关性 | 断言 4/5 **必须红** |

**验收 4、5 与 6 的关系**：4、5 是**防泄漏的守卫**，6 是它们的证伪。
没有 6，4 和 5 可能只是"这份数据恰好如此"，而不是"数据不得变成那样"。
