# Proposal: 把三路召回真正接进评测入口（wire-three-way-recall）

## Why

`memory-retrieval` 规格里的「三路召回」写着：词面、向量、条件兄弟邻接三条路径，
**每条 MUST 可单独关闭，以便测量各自的贡献**。

这条 requirement **从未被端到端验证过**。实测 `evals/run_retrieval.py` 只
`import recall_by_lexical`（第 37 行），`recall_by_vector` 与 `recall_by_adjacency`
一次都没进过评测入口。于是 C4 报告的"三路召回"实际只跑了一路，
`rrf({"lexical": ...})` 融合的是一个单列表，四特征重排的对象在 independent 上
26/26 条只有一个候选。

**这不是"实现不完整"，是规格与实现长期不符**：规格说已验证，实际没有。
继续留着，下一个依赖这条规格做设计的人（C5 答案策略）会按一个不存在的能力规划。

同时有两个同源的入口缺陷必须一起修，它们与"三路只跑一路"是同一类问题——
**下游拿到的东西不是它声称的那样**：

- `dedup` 收到的是 `(item_id, item_id, 1.0)`：text 字段是 UUID、score 是常数。
  内部按 `(-score, id)` 排序于是退化为字典序，**把重排结果整块替换**
- 池构造里 `embedding=` 出现 0 次，所以即使接上 vector 一路，它也只会返回空列表

这三件事合起来使 v2 数据集无法开始：不修，v2 的数字只反映词面一路，
补多少查询都是白补。

## What Changes

### 一、评测入口接三路（`evals/run_retrieval.py`）

- 建池时**为每条候选写入 embedding**（document 侧，走缓存）
- 查询侧计算 embedding（query 侧），调用 `recall_by_vector`
- 用 gold 的 `(subject, relation, condition)` 调用 `recall_by_adjacency`
- 三路结果一起进 `rrf()`，各自**可单独开关**（`--paths lexical,vector,adjacency`）

### 二、`dedup` 改传真文本与真实分数

- `text` 从 `store.get(item_id).text` 读回，不是 id
- `score` 传**融合后、重排前**的 RRF 分（顺序见 design，这是一个真实的设计决定）
- 保留 `--no-dedup` 开关，使"去重有没有影响"仍然可测

### 三、规格补 delta（这是 MODIFIED，不是内部重构）

行为确实变了：从"只有词面参与融合"变成"三路参与且各自可关"。
不写 delta 的后果很具体——归档后 `specs/` 会继续声称一个从未验证过的能力。

### 四、重跑样例，量出三路的贡献

**关键验收**：三路全开 vs 只开词面的 `SEH@1` 必须有可观测差异。
若两者完全相同，说明新增两路在该数据上是噪声——**那也必须写进报告**，
而不是挂个绿勾了事。

## Capabilities

### New Capabilities

（无）

### Modified Capabilities

- `memory-retrieval`: 「三路召回」补齐"评测入口确实调用三路、且每路返回非空"的行为契约。
  该 requirement 当前写的是"每条路径 MUST 可单独关闭"，但没有要求
  "关闭后的结果确实不含该路候选"被端到端验证。
- `evaluation-harness`: 「检索质量的度量」增加测量前提——
  每路召回的**返回条数**必须可观测，否则"跑了"与"没跑"在结果上无法区分。

## 本次不做（范围边界）

- **不改 `src/memory/retrieval/` 的任何算法**：不改 BM25 排序、不改 RRF 公式、
  不改四特征权重、不改 `condition_match`。A5 会验证这一点
- **不改三路召回在 `src/` 里的 ACTIVE 过滤**（B 轴属于另一个变更）
- **不改 C3 的写路径判定**
- **不铺 v2 数据集**：本变更只让测量装置可用，造数据是下一步
- **不做答案生成**（C5）

## 为什么可以独立验收

四条验收都能在本变更内闭合，不依赖 v2 数据：

- A1–A2 是门禁项，可在样例与旧集上跑
- A3 需要差异数据，样例（12 条）就够
- A4 是 `locked_defect` 清单变化，可机器检查
- A5 是数字不变性，靠重跑对比

## 验收标准

| 编号 | 条件 | 判定方式 | 阈值 |
|---|---|---|---|
| **A1** | 三路召回在评测入口被调用且各自返回非空 | L6a + L6b + L6c 全绿 | 三者同时通过 |
| **A2** | `dedup` 收到 `item.text` 与真实分数 | L7 + L8 绿 | 入参断言 + 分数方差 > 0 |
| **A3** | **三路全开 vs 只开词面，`SEH@1` 有差异** | 同数据同种子跑两组，报差异与配对 bootstrap 区间 | 差异 ≠ 0；区间与点估计一并报告 |
| **A4** | 对应 `locked_defect` 条目**变红** | `pytest -m locked_defect` 的清单变化 | 至少 L6a/L6b/L7-L8 四条变红；**不许删除测试** |
| **A5** | C4 已归档的检索算法行为不变 | 单路词面在新旧代码上逐位相同 | 26/26 条 case 的 `rank_after_fusion` 完全相同 |
| A6 | 质量门禁 | `pytest` / `ruff` / `mypy` / `openspec validate --strict` | 全绿 |

### A3 为什么是最关键的一条

L6a 证明"调用了"，L6b 证明"有数据"，L6c 证明"返回非空"。
**三条合起来仍证明不了"有贡献"**：如果三路全开和只开词面得到完全相同的分数，
那新增的两路就是噪声。

A3 要求给出差异数据，等于强迫这一步产出可比较的数字，而不只是绿勾。
**若差异为 0，结论是"另外两路在此数据上无贡献"，写进报告，不是失败。**

### A5 的一个必须提前说明的冲突

"A5：C4 已归档的数字不变" **不能按字面执行**，原因有三：

1. **`run_count` 会变。** 重跑 `test` 集会让 `retrieval-run-count.json` 里
   `retrieval-test-*` 从 1 变成 2，而 `test_report_consistency.py::test_test_split_was_run_only_once`
   会因此失败。那条断言保护的是"报告集只跑一次"的纪律
2. **接了三路之后数字本来就会变。** 这正是本变更的目的。若三路全开与只开词面
   分数完全相同，A3 就不成立
3. **"数字不变"与"行为改变"是两个命题。** 本变更确实改变检索行为（这是 MODIFIED 的理由），
   所以不能同时要求数字不变

因此 A5 改成**可验证的精确命题**：

> **A5（修正版）**：以 `--paths lexical` 单开词面，在新代码上重跑旧数据，
> 26/26 条 case 的 `rank_after_fusion` 与 `rank_after_rerank` 必须与归档结果**逐位相同**。

这直接验证"没有顺手改坏召回算法"，且不依赖"总分不变"这种模糊说法。
`run_count` 的处理：新增独立计数键（如 `retrieval-dev-...-a5check`），
或按协议在结果 JSON 里显式记录 `purpose: "A5 regression"`，
**不覆盖** `test` 集原有的运行计数。

## Impact

| 路径 | 作用 |
|---|---|
| `evals/run_retrieval.py` | 接三路召回、池内写向量、`dedup` 传真文本与分数、加 `--paths` |
| `evals/metrics/v2_baselines.py` | 复用 `competing_set`，不另写池定义 |
| `evals/tools/check_v2_dataset.py` | L6a/L6b/L6c/L7/L8 五项从"检查源码"升级为"真实断言" |
| `tests/retrieval/test_c4_leak_disclosure.py` | 缺陷 7/8 的 `locked_defect` 条目改为正向断言 |
| `tests/retrieval/test_l6c_paths_return_data.py` | 保持，作为 L6c 的行为基础 |
| `docs/reports/c4-retrieval.md` | 更新缺陷 7/8 状态：已修复，并给出 A3 差异数据 |
| `docs/reports/v2-sample-validation.md` | 门禁从 11/17 更新为实际通过数 |
| `openspec/specs/memory-retrieval/spec.md` | 三路召回 requirement 补"端到端被调用"场景 |
| `openspec/specs/evaluation-harness/spec.md` | 检索度量补"每路返回条数可观测" |

**依赖**：DashScope embedding（需网络，已缓存则可离线）。若不联网，
A1/A3 无法验证——这一点必须在实施时先确认，不能静默跳过。

**不改**：`src/memory/store/`、`src/memory/resolver/`、`src/memory/retrieval/*.py` 的任何算法。
