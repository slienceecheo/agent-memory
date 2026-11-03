## Why

**`F24` 的随机基线与"池大小"之间有一个恒等式，而它在 5 条查询上不成立。**

实测 `n_competitors + 1 == len(competing_set)`：

| 查询 | 标注轴 | `n_competitors` | `competing_set` | `n+1` |
|---|---|---|---|---|
| `ledger-q11` / `q12` | C | 0 | **12** | 1 |
| `billing-c1` / `c2` / `c3` | C | 2 | **9** | 3 |

**A 轴恒等式成立，C 轴不成立。**

原因：两个量被混用了。

| 量 | 定义 | 用途 |
|---|---|---|
| `n_competitors` | 池中与 gold **同 relation** 的候选数（不含 gold） | **轴派生**（>0 判 within） |
| `ranking_pool_size` | 实际参与排名的候选数（含 gold） | **随机基线** `1/N` |

`competing_set()` 返回的是 `ranking_pool_size`。把它当成 `n_competitors` 用，
就会出现"n=0 但池 12"的矛盾。

**后果**：若按 `n_competitors + 1` 推池大小，`ledger-q11/q12` 会得到 `N=1`，
随机基线 `1/1 = 1.0000`（随机也能满分）——**与真值 `1/12 = 0.0833` 差 12 倍**。
于是任何实测值都"低于基线"，判据失效。

**这才是 `< 0.9999` 这类阈值在 v3 下失效的真正机制**，
而不是"标注轴与派生轴不同源"（后者的基线值恰好相同，实测过）。

## What Changes

**1. 给两个量分别命名，不互相推算**

```python
n_competitors        # 轴派生用；不含 gold
ranking_pool_size    # 随机基线用；含 gold，等于 len(competing_set(dataset, q))
```

`ranking_pool_size` MUST 从 `competing_set()` 取，**MUST NOT** 由 `n_competitors + 1` 推算——
后者在 C 轴上差 12 倍。

**2. 新增 `axis_baseline_derived(dataset)`**

按**派生轴**分组算随机基线：

```python
for q in dataset.queries:
    axis = derive_axis(pool, gold)                  # 派生，不读 q.axis
    N = len(competing_set(dataset, q))              # ranking_pool_size
    groups[axis].append(random_seh_at_1(N))
```

**验收（现有 v2 数据即可验）**：

```
axis_baseline_derived(sample) == {"relation_within": 0.3000, "relation_cross": 0.0833}
```

`relation_cross = 0.0833` 就是 `1/12`——**它能抓住"用 n_competitors 推算池大小"这个错误**
（那会得到 `1.0`）。

**3. `F24` 的两段都改用派生轴**

| 段 | v2（现在） | v3（本变更后） |
|---|---|---|
| 数据侧 | `axis_baseline(dataset, Axis.A)`（标注） | `axis_baseline_derived()["relation_within"]` |
| 结果侧 | `dataset_a`（标注 A 的 id 集合） | 派生 within 的 case |
| 结果侧判据 | `ratio < 0.9999`（不满分） | **`ratio > baseline`（比随机好）** |

**"不满分"在 v3 下不是有意义的判据**：v2 里满分意味着"数据太简单"，
v3 里满分可能意味着"排序有效"。两个方向相反。

**4. 报告必须报"标注与派生不一致 N/M"**

这**不依赖门禁用哪套轴**：可追溯性来自报告里写不写那个数字。
实测 `sample` 0/12、`billing` **3/12**。

## Impact

- 代码：`evals/metrics/v2_baselines.py`（新增 `axis_baseline_derived`）、
  `evals/tools/check_v2_dataset.py`（`F24` 两段改用派生轴）
- 测试：新增 `test_derived_axis_baseline.py`
- 数据 / 结果文件：**无**
- **`F24` 在 v3 下从"不适用"变为"执行并判据"**，所以：
  - 真实 v2 数据上它仍不适用（产物签名是 v2）
  - 但若在 `tmp_path` 造 v3 产物，它会执行

## 验收

| # | 判据 | 可被违反的形式 |
|---|---|---|
| 1 | `axis_baseline_derived(sample)` | `{"relation_within": 0.3000, "relation_cross": 0.0833}` |
| 2 | **cross 基线是 1/12 而非 1/1** | 若写成 1.0，说明用了 `n_competitors+1` |
| 3 | `billing` 的派生 within 基线 | **0.2778**（9 条 1/3 + 3 条 1/9），不是 0.3333 |
| 4 | `F24` 在 v3 下用派生轴 | 造 v3 产物的 `tmp_path` 测试 |
| 5 | 报告含"标注与派生不一致 N/M" | `sample` 0/12、`billing` 3/12 |

**验收 2 是核心**：它是唯一能抓住"两个池大小混用"的断言。

## 不做的事

- **不造 v3 数据**：验收全用现有 v2 数据
- **不改 `axis_baseline()`**：v2 口径保留，供对比
- **不定 margin**：`ratio > baseline` 不需要 margin；若将来要 margin，需 v3 数据
