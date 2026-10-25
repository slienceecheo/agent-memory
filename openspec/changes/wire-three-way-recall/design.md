# Design: 把三路召回接进评测入口

## Context

见 `proposal.md` 的 Why。这里只记实施需要知道的三条现状：

1. `evals/run_retrieval.py` 第 37 行只 import `recall_by_lexical`；
   第 192–193 行是 `rrf({"lexical": lexical})`——融合的是单列表
2. 第 228 行 `texts = [(item_id, item_id, 1.0) for item_id in order]`：
   `dedup` 的入参是 `(id, text, score)`，所以 text 拿到 UUID、score 是常数
3. 建池时没有任何 `embedding=` 写入，所以向量路径即使被调用也返回空

Embedding 侧已实测可用：`DashScopeEmbedder` 返回 1024 维，第二次调用
`network_calls` 不增长（缓存命中）。这条是 A1/A3 能落地的前提。

## Goals / Non-Goals

**Goals**

- 三路召回在评测入口被真实调用、各自返回非空、返回条数可观测
- `dedup` 收到原文与真实分数
- 三路全开与只开词面的差异成为可比数字
- 单开词面的结果与归档逐位相同（证明没动算法）

**Non-Goals**

- 不改 `src/memory/retrieval/` 的任何算法
- 不调权重、不改 `condition_match`
- 不铺 v2 数据集
- 不给检索结果打分以外的语义判断

## Decisions

### 决策 1：`dedup` 放在重排之前

**这是本设计最重要的一条，不能实现时随手定。**

`dedup` 的签名是 `(item_id, text, score)`，而 `run_retrieval` 手里只有 id 与
RRF 分。要传真文本必须回读 `store.get(item_id).text`。真正的问题是
**score 传 RRF 分还是重排分**——它决定去重发生在融合后还是重排后：

| 方案 | 位置 | 合并的是 | 风险 |
|---|---|---|---|
| **采用**：传 RRF 分 | 融合后、重排前 | 融合结果 | 无 |
| 否决：传重排分 | 重排后 | 最终排序 | **去重会推翻重排的结论** |

理由：去重的目标是"别把同一件事的两条都喂给重排器"。若排在重排之后，
一次合并就可能把重排精心排出的第 1 名干掉——那等于让一个二分类模型
覆盖四特征重排，权重的意义全部消失。

**否决的备选**：把 `dedup` 改成不依赖 score（用外部传入的顺序）。
否决理由：`dedup` 已有 13 条单元测试锁定"按分数降序、等义时保留高分者"，
改签名会让这些测试失去意义；而传真实 RRF 分就能满足同一语义。

### 决策 2：文本回读用批量查询，不用逐条 `get`

池最多 21 条、`top_k=5`，看起来逐条 `store.get()` 无所谓。但
`store.get` 每次都开一次新查询，且 `evaluate_case` 已经在一个
`TemporaryDirectory` 循环里跑了 N 次——逐条读会把单次评估的查询数
从 O(1) 推到 O(N)。

**采用**：一次 `SELECT id, source_text FROM items WHERE id IN (...)`，
用 `store.conn` 直查。**否决**：给 `SqliteStore` 加 `get_many()`
——那会改动 `src/`，超出本变更范围（Non-Goal）。

### 决策 3：`--paths` 用显式列表，不用三个布尔开关

```
--paths lexical,vector,adjacency   # 默认全开
--paths lexical                    # A5 回归
--paths ""                         # 零召回基线
```

**否决**：`--no-vector --no-adjacency` 三个开关。理由：三个布尔有 8 种组合，
其中 3 种自相矛盾（全关却仍要融合）；显式列表只有一种表达方式，
且"空列表 = 零召回"直接对应规格里的"全部关闭返回空结果"场景。

### 决策 4：邻接路径的输入取自 gold 的逻辑键

`recall_by_adjacency` 需要 `(subject, relation, condition)`。评测时
gold 的逻辑键是已知的，所以直接用 gold 的键调用。

**取舍**：这让邻接路径"知道答案在哪"。但它本来就只服务 BRANCH——
它的语义是"同一逻辑键下的其他条件分支"，与查询文本无关。
**若不加限制，它会把 gold 的兄弟全部召回，等于免费送分。**

因此**邻接路径必须报告"召回了 gold 自身之外的几条"**，并在 A3 里分开看
"邻接是否只是把兄弟塞进候选、并没有帮助定位"。若三路全开与
"词面+向量"（不含邻接）分数相同，说明邻接在该数据上无效——写进报告。

### 决策 5：向量写入用 document 侧，查询用 query 侧

`text_type` 必须分开（同文本两侧余弦仅 0.842）。池内条目用 `document`，
查询用 `query`。这是 `docs/embedding.md` 已记录的坑，不是新决定，但
**写错会让向量路径看起来"跑了但没用"**，所以进 design 留痕。

写入的文本用什么？**用 `subject + relation + value + memory_text`**
（与 `items_fts` 的索引内容一致），不是只用 `value`。
理由：只用 value 会让"深夜"这种短值与其他短值难以区分。

### 决策 6：A5 回归用独立的结果文件名

重跑会推高 `run_count`，而 `test_report_consistency.py` 断言
`retrieval-test-*` 的运行次数必须为 1。

**采用**：A5 回归写到 `results/retrieval-a5-regression-*.json`，
不进 `_bump_run_count` 的主计数（或单独键名），并在文件里写
`"purpose": "A5 regression: 单开词面，验证算法未变"`。
**否决**：直接重跑 `retrieval-test-uniform-*.json`。理由：那会把
"报告集只跑一次"的纪律破坏掉，而这条纪律本身是 C4 的教训。

### 决策 7：A5 拆成两段，适用范围不同

原始要求是"排名逐位相同"。实测后发现需要拆开，因为两段的可执行性完全不同：

| 段 | 比什么 | 旧集 | v2 |
|---|---|---|---|
| **A5-a** | `rank_after_fusion`、`rank_after_rerank`、`attribution`、**top-1 的稳定 tag** | ✅ | ✅ |
| **A5-b** | 完整融合序列（用稳定 tag，不是 uuid） | ❌ 不可执行 | ✅ |

#### A5-b 在旧集上不可执行，三条原因

1. **归档结果从未记录融合序列。** 归档 `per_case` 只有 8 个键
   （`case_id` / `has_gold` / `pool_size` / `rank_after_fusion` /
   `rank_after_rerank` / `seh` / `srs` / `attribution`），没有序列可作基线
2. **就算补建基线也不会失败。** 旧集 independent 的 26/26 条 case 召回集
   只有 1 个候选，完整序列恒为 `[gold]`，任何实现都会通过。
   这与 C4 缺陷 3、以及 A 轴 `SEH@5` 饱和是同一形态：
   **检查看起来合理，但在当前数据上无法失败**
3. **候选 id 由 `uuid4` 生成，跨运行不可比。** 实测两次独立建库的 id 完全不同

因此 **A5-b 的适用范围写死为 v2**（v2 尚未运行，基线天然干净）。
旧集只做 A5-a。

#### 为什么不回退代码补建旧集基线

考虑过 `git stash` 回到 `c4b3152` 跑一次存 `fusion_tags` 作基线。否决理由：

- 那次跑出来的 id 同样是 uuid4，仍不可比；能比的只有顺序，而顺序在
  单候选池上恒为 `[gold]`——**花一步去建一个永远不会失败的基线**
- 回退再前进要跑两趟 `run_retrieval`，会搅动 `retrieval-run-count.json`
  的键，而 `test_test_split_was_run_only_once` 依赖它

#### top-1 那一项为什么必须有

前两项（两个 rank）加 `attribution` 有一个盲区：

- `rank_after_fusion` 相同
- `rank_after_rerank` 相同
- `attribution` 相同（都是 `None`，即成功）
- **但排第一的换成了另一条**

这种情况三项都抓不到，而它正是"改坏排序"最直接的形态。
用 `rerank_top1_tag`（稳定 tag，`gold-<case_id>` 或 `d-<case_id>-<i>`）
而不是 uuid，使这一项在旧集上也有结构性约束：若把 gold 挤出第一名，
rank 就不再是 1，第一项会先失败。

#### 稳定 tag 从哪里来

`build_pool` 之前，每条候选的 `entry.id` 是构造时给的稳定 tag
（`gold-<case_id>` / `d-<case_id>-<i>`）；`store.insert()` 之后才变成 uuid4。
所以在插入时同时记一份 `tag_by_id: dict[str, str]`，
输出 `fusion_tags` 与 `rerank_top1_tag` 时反向映射回来。

### 决策 8：`path_returns` 用「数字 + case 数 + 均值」

只报总数有歧义：`lexical=41` 可能是"33 条各返回 1.2 条"，
也可能是"1 条返回 41 条、其余 32 条返回 0"——后者说明某个 case 的池异常大，
是数据缺陷。均值能立刻区分，成本几乎为零。

所以输出形如：

```
path_returns: lexical=41 (33 cases, mean 1.24) vector=- adjacency=-
```

`0` 与 `null` 的区分必须保留：`0` = 跑了但返回空，`null` = 没开或没接线。
再加一列 `paths_unwired`，区分"没开"与"开了但代码里没有调用点"——
它只列**已启用但代码里没有调用点**的路径；没启用的路径是"没开"，
不是"没接上"，两者诊断方向相反。

### 决策 9：融合前按 `FUSION_CAP = 20` 截断各路

**动机（实测）**：

| 路径 | 每 case 返回条数 | RRF 单路总贡献（相对 1 条） |
|---|---|---|
| lexical | 最多 3（mean 1.24） | 1.0x – 3.0x |
| vector | 14（mean 14.00） | **12.7x** |

而且「向量第 14 名」单条得分 `1/74 = 0.01351` 已达「词面第 1 名」
`1/61 = 0.01639` 的 **82%**。RRF 是 `Σ 1/(k+rank)`，
长列表靠**条数**系统性占优，不是靠更相关。

`docs/retrieval.md` 记的 RRF 前提是 `L < k+2 = 62`；462（33 case 合计）
远超前提。不截断的话 A3 必然得出"三路更差"，而真实原因是长度失衡。

**截断长度取常数 20，不写成 `k*4`**：`k` 有歧义——RRF 的 `k=60`
给出 240（远超 62，等于没截），评估的 `K=5` 给出 20（本意）。
写成常数并在代码里解释，避免后人按 `k=60` 重算。

**必须记录的一个限制：cap 在旧数据上不生效。**

`build_pool` 会去掉重复逻辑键，所以 `1 + 20` 条实际只剩 **14** 条；
`recall_by_vector` 无阈值返回全部 14 条；14 < 20，一条都没截。

也就是说：

- cap 能防"一路几百条刷分"
- **cap 防不了"一路本来就召回得多"**——旧数据上的失衡仍在

这是本项目**第三个**"检查看起来合理、在当前数据上不生效"的案例
（前两个：`SEH@5` 饱和、`rank` 恒为 1）。
因此 `tests/retrieval/test_fusion_cap.py` 里有一条测试专门断言
"旧集上 cap 不生效"这一事实，使它在 v2（池 21 条）真正生效时能被察觉。

### 决策 10：A5-a 在旧集上的效力必须显式标注

旧集 26/26 条 case 只有一个候选，因此 `rank_after_fusion`、
`rank_after_rerank`、`rerank_top1_tag` 三项**在任何实现下都必然相同**。

> **A5-a 在旧集上通过，不能作为"排序未被改坏"的证据。**
> 它只能作为"没有崩溃"的烟雾测试。
>
> A5-a 的约束力只在 v2 上成立（池有 3–12 个候选）。
> 在此之前，"没改坏算法"的证据只有：单元测试通过、人工核对 diff。

为了让"弱通过"与"强通过"在数据里可见而不是靠人记得看池大小，
结果 JSON 增加一列：

```
a5_strength: "weak"     # 池内候选数 <= 1，仅烟雾测试
a5_strength: "strong"   # 池内候选数 >= 2，真实约束
```

## Risks / Trade-offs

| 风险 | 缓解 |
|---|---|
| 三路全开后 `SEH@1` 与只开词面完全相同 | 这正是 A3 要测的。写进报告，不隐瞒，不为了"有差异"去调权重 |
| 邻接路径白送 gold 的兄弟，虚高指标 | 决策 4：单独报告"邻接召回了几条 gold 之外的条目"，并在 A3 里对照"词面+向量" |
| 向量写入让首次评估很慢（21×N 次 embedding） | 缓存已生效（实测第二次调用不涨 `network_calls`）；首次运行数量写进结果 JSON |
| `--no-dedup` 与新默认行为重叠 | 保留 `--no-dedup`，它关的是"整个去重阶段"；`--paths` 关的是"召回路径"，两者正交 |
| 修改 `run_retrieval.py` 时顺手改了召回调用顺序 | A5 回归逐位对比 `rank_after_fusion` 与 `rank_after_rerank` |

## Migration Plan

无数据迁移。旧的 `results/*.json` 保留不动；A5 回归写到独立文件。

回滚：`run_retrieval.py` 的 `--paths` 默认值改回 `lexical` 即回到旧行为，
但**不执行回滚**——旧行为是本变更要修的缺陷。

## 如何被测量

| 决策 | 对应指标 |
|---|---|
| 决策 1（dedup 在重排前） | A2：入参断言 + 分数方差 > 0；`test_dedup` 现有 13 条不变 |
| 决策 2（批量回读） | 单次评估的 SQL 查询数（可在测试里计数） |
| 决策 3（`--paths`） | A1：L6a/L6b/L6c；零召回基线 `SEH@5 = 0` |
| 决策 4（邻接输入） | A3：三路全开 vs 词面+向量 的差异 |
| 决策 5（text_type 分开） | 向量路径返回条数 > 0（L6c） |
| 决策 6（A5 独立文件） | `test_test_split_was_run_only_once` 仍通过 |
