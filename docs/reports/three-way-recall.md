# 三路召回的第一次可测数字

> 生成日期：2026-10-26
> 数据集：`dev`（33 条有 gold）
> 代码指纹：四份结果均为 `code_diff_hash = 189db1d9`
> 复算：
> ```
> uv run --no-sync python -m evals.run_retrieval --split dev --no-dedup --paths lexical --out results/a3-lexical.json
> uv run --no-sync python -m evals.run_retrieval --split dev --no-dedup --paths lexical,vector --out results/a3-lexical-vector.json
> uv run --no-sync python -m evals.run_retrieval --split dev --no-dedup --paths lexical,vector,adjacency --out results/a3-lexical-vector-adjacency.json
> uv run --no-sync python -m evals.run_retrieval --split dev --paths lexical,vector,adjacency --out results/a3-with-dedup.json
> ```

## 0. 先说这组数字不能用来回答什么

这是本报告最重要的一节。**三路召回的数字第一次可测，但四条路径里有三条的输入仍有问题。**

### 不能得出的结论

| 不能说的 | 为什么 |
|---|---|
| **"向量路径有贡献"** | 向量输入不含条件（缺陷 14 修复后），BRANCH 的两条分支向量文本完全相同；且池 14 条 < `FUSION_CAP=20`，截断从未生效 |
| **"邻接路径有害"** | 邻接在 dev 上没有合法目标（缺陷 16）：6/6 条 BRANCH 的真兄弟不在池中。它召回的全是非兄弟。**这不是"邻接不好"，是"没测到邻接"** |
| **"dedup 有用/无用"** | `dedup` 在池里没有合法合并目标（缺陷 15）：`build_pool` 已按 `_key` 去重。MRR 的 +0.0025 来自 uuid 排序（缺陷 8 残留），跨进程不可复现 |

### 能得出的结论

1. **接上向量使 `SEH@1` 从 0.9091 掉到 0.8182，MRR 从 0.9545 掉到 0.8864。**
   在池 14 条、且金标与查询同源的数据上，向量路径的净效果是**稀释**。

2. **接上邻接使 `SEH@1` 从 0.8182 掉到 0.6667。**
   8 条掉出第 1；全部 8 条的抢位者都是邻接注入的条目。

3. **两个下降都不是"路径能力差"，是"路径的输入有问题"。**
   证据：缺陷 14（向量输入含答案）、缺陷 16（邻接无目标）。

> 这一节的作用与 C4 报告第 0 节相同：**防止这份报告被当成"三路召回效果不好"的证据。**
> C4 防的是"1.000 被当成能力"，这里防的是"0.667 被当成能力差"。

## 1. 四组配置的数字

同一 `code_diff_hash`、同数据、同权重（`uniform`）、`k=5`、池 14–15 条。

| 配置 | SEH@1 | MRR | `path_returns`（总和） |
|---|---|---|---|
| `lexical` | **0.9091** | **0.9545** | lexical=41 |
| `lexical,vector` | 0.8182 | 0.8864 | lexical=41, vector=462 |
| `lexical,vector,adjacency` | **0.6667** | **0.8030** | + adjacency=13 |
| 三路 + `dedup` | 0.6667 | 0.8056 | 同上 |

### 两条必须同时报的理由

`SEH@1` 与 MRR 在第四行给出**不同的故事**：

- `SEH@1` 上第三、四行**完全相同**（都是 0.6667）
- MRR 上第四行**高 0.0025**

那 0.0025 来自 `dev-branch-05` 在并列分数下由 uuid 决定的名次（缺陷 8 残留）。
**只报 `SEH@1` 会看不见它，只报 MRR 会把它当成"dedup 有贡献"。**

## 2. 掉位分解

### 2.1 按 `SEH@1`（定义 A：掉出第 1 名）

| 状态 | 条数 |
|---|---|
| `lexical` 下已在第 1 | 30/33 |
| `lexical` 下不在第 1 | 3/33（`branch-01`、`02`、`05`） |
| 接上 vector + adjacency 后，**原先第 1 中掉位** | **8** |
| 原先第 1 中仍在第 1 | 22 |
| 原先不在第 1 中回到第 1 | 0 |
| **最终第 1** | **22/33 = 0.6667** |

掉位的 8 条：

```
dev-branch-03   dev-branch-04   dev-branch-06
dev-merge-05    dev-noop-05     dev-sup-02
dev-sup-03      dev-sup-05
```

### 2.2 按名次变差（定义 B，对应 MRR）

| 定义 | BRANCH | 非 BRANCH | 合计 |
|---|---|---|---|
| **A：掉出第 1** | 3/6 | 5/27 | 8 |
| **B：名次变差**（含 2→3、2→4） | 6/6 | 5/27 | 11 |

**集中度必须写两个，且分母不同**：

| 定义 | BRANCH 占掉位 | BRANCH 占样本 | 集中度 |
|---|---|---|---|
| A | 3/8 = 37.5% | 6/33 = 18.2% | **2.1x** |
| B | 6/11 = 54.5% | 6/33 = 18.2% | **3.0x** |

定义 A 直接对应 `SEH@1 = 0.6667`；定义 B 描述"接每一路都在稀释"，对应 MRR。
**混在一起就会重演"7 条 vs 10 条"那次的分母之争。**

## 3. BRANCH 在四条路径上的盲区

BRANCH 的 6 条 case 落在**所有路径的盲区交集**里：

| 路径 | BRANCH 上的问题 |
|---|---|
| 词面 | 源行 `text` 描述的是 `candidate_value`，不是 `gold.value`（缺陷 11 第二来源） |
| 向量 | 条件不参与向量输入（缺陷 14 修复后），两个分支的向量文本完全相同 |
| 邻接 | 真兄弟 **0/6** 在池中（缺陷 16） |
| `condition_match` | gold 得 0.0，无条件干扰项得 0.5（缺陷 11 第一来源） |

### 6 条 BRANCH 在四种配置下的排名

| case | `lexical` | +vector | 3paths | 3paths+dedup |
|---|---|---|---|---|
| `dev-branch-01` | 2 | 3 | 3 | 3 |
| `dev-branch-02` | 2 | 3 | 3 | 3 |
| `dev-branch-03` | 1 | 2 | 3 | 3 |
| `dev-branch-04` | 1 | 3 | 4 | 4 |
| `dev-branch-05` | 2 | 4 | 4 | **3** |
| `dev-branch-06` | 1 | 1 | 2 | 2 |

**6/6 条全部掉位**（定义 B），而其余 27 条只有 5 条掉位。

> **`dev-branch-05` 的 dedup 列是 3，不是 4。** 这个差异跨进程不可复现
> （缺陷 8 残留：并列时按 uuid 排序）。实测 4 个独立进程得到 4 个不同的
> `gold` 位置（3 / 7 / 6 / 13）。**该单元格不应被引用为稳定值。**

## 4. 这份数据的方法学限制

| 限制 | 影响 |
|---|---|
| 池 14 条 < `FUSION_CAP = 20` | 融合截断从未生效；旧数据上的 RRF 失衡来自召回率不对称（lexical 1–3 条 vs vector 14 条），不是列表过长 |
| BRANCH 占 6/33 = 18% | 但贡献了 37.5%（定义 A）～54.5%（定义 B）的掉位 |
| `test` 与 `independent` 未使用 | `test` 的 gold 键与 dev 重合 41%（缺陷 10）；`independent` 池 100% 来自 dev（缺陷 9）。两者的数字都不可引用 |
| 四份同 fingerprint 但手工拼表风险 | 本项目曾因引用修复前的数字产出一张错表。**任何跨轮引用的数字都要从文件重新读，不能从对话历史里抄** |

### 表注（拼表者必读）

本报告所有数字来自四个文件：

```
results/a3-lexical.json
results/a3-lexical-vector.json
results/a3-lexical-vector-adjacency.json
results/a3-with-dedup.json
```

四份 `code_diff_hash` 均为 `189db1d9`，由
`tests/retrieval/test_a3_comparability.py::test_three_way_results_share_code_fingerprint` 保证。
**手工拼表时请只取同一 fingerprint 的文件。**

## 5. 一句话总结

**这是三路召回第一次可测的数字，不是三路召回的能力。**

`SEH@1` 从 0.9091 降到 0.6667，但两条下降路径的输入都有缺陷：
向量含答案（已修）、邻接无目标（待 v2）。**在 v2 数据造出来之前，
这份数字唯一能回答的问题是"装置里还剩哪些问题"，不是"哪条路径更好"。**

## 6. 原始结果

- `results/a3-lexical.json`
- `results/a3-lexical-vector.json`
- `results/a3-lexical-vector-adjacency.json`
- `results/a3-with-dedup.json`
- `results/a3-with-dedup-rerun.json`（验证不可复现性用，不引用其数字）
- `results/p2b0-judge-probe.json`（判官验证）
