## 决策 1：两个池大小必须分别命名，不能互相推算

**这是本变更的核心，也是我最初判断错的地方。**

我原以为问题是"标注轴与派生轴不同源导致不可比"。实测**基线值恰好相同**：

| subject | 标注 A 基线 | 派生 within 基线 |
|---|---|---|
| `sample` | 0.3000 | 0.3000 |
| `billing` | 0.3333 | 0.3333 |

**真正的问题是 `n_competitors` 与 `competing_set` 是两个量，而只有 A 轴上它们满足 `n+1 == cs`。**

| 查询 | `n` | `cs` | `n+1` |
|---|---|---|---|
| `ledger-q11/q12`（C） | 0 | 12 | 1 |
| `billing-c1/c2/c3`（C） | 2 | 9 | 3 |

**A 轴成立，C 轴不成立。** 因为 `competing_set()` 对 A 轴返回"同 subject 同 relation"，
对 C 轴返回"同 subject 全部"——后者与 `n_competitors` 无关。

## 决策 2：`ranking_pool_size` 必须从竞争集取，不推公式

```python
N = len(competing_set(dataset, q))      # 对
N = n_competitors + 1                    # 对 A 轴，错 C 轴
```

**按后者，`ledger-q11/q12` 会得到 `N=1`，随机基线 `1.0`（随机也满分）**——
任何实测值都"不高于基线"，判据失去意义。

**这就是"`< 0.9999` 在 v3 下失效"的机制**，比"轴不同源"具体得多。

## 决策 3：`axis_baseline()` 保留，新增 `axis_baseline_derived()`

**不修改现有函数**：v2 的报告与门禁依赖它，改了会动 v2 的数字。
新增一个函数，两者并存。

**验收用 `sample`**：

```
axis_baseline_derived(sample) == {"relation_within": 0.3000, "relation_cross": 0.0833}
```

`0.0833 = 1/12`。**若得到 `1.0`，说明用了 `n_competitors + 1`。**

## 决策 4：`F24` 在 v3 下改用派生轴，判据改成"比随机好"

| 段 | v2 | v3 |
|---|---|---|
| 数据侧 | `axis_baseline(dataset, Axis.A)` | `axis_baseline_derived()["relation_within"]` |
| 结果侧分母 | 标注 A 的 id 集合 | 派生 within 的 case |
| 结果侧判据 | `ratio < 0.9999`（不满分） | **`ratio > baseline`** |

**"不满分"在 v3 下没有意义**：

| 装置 | 满分意味着 |
|---|---|
| v2 | 数据太简单（坏） |
| v3 | 排序有效（好） |

**两个方向相反**，所以阈值不能沿用。

## 决策 5：可追溯性单独加一条，不靠门禁的轴选择

**我最初说"选 C 才能保留可追溯性"是错的。**

可追溯性来自**报告里写不写那个数字**，不来自门禁用哪套轴。
门禁同时用两套会有两个 `passed`，而 `Check` 只有一个。

所以：**门禁用派生轴（一套），报告报"标注与派生不一致 N/M"（另一套）**。

实测基线：`sample` 0/12、`billing` **3/12**。

## 决策 6：`billing` 的派生 within 基线是 0.2778，不是 0.3333

**这是"重新分组"的实证**：

| 分组 | 构成 |
|---|---|
| 标注 A | 9 条，每条 `N=3` -> `1/3`，基线 0.3333 |
| 派生 within | **12 条**（9 条 `N=3` + 3 条 `N=9`）-> 混合，基线 **0.2778** |

那 3 条 `C` 标注变成 within 后，池大小是 9 而不是 3——
**派生轴不是把标注改名，是真的按池结构重新分组。**

## Risks / Trade-offs

| 风险 | 缓解 |
|---|---|
| 有人把 `n_competitors + 1` 当池大小 | 验收 2 断言 cross 基线是 `1/12` |
| `F24` 在 v3 下变红引起误读 | 那是真实结果（billing 派生 within 实测 0.0833 < 基线 0.2778） |
| 两套轴口径并存造成混乱 | 名字分开：`axis_baseline` / `axis_baseline_derived` |

## 不做的事

- **不造 v3 数据**
- **不定 margin**：`ratio > baseline` 不需要；将来要 margin 需 v3 数据
- **不改 `axis_baseline()`**：v2 口径保留
