## Why

**第一条：result-side 门禁读的是历史产物，而报告把它们当成"当前装置的门禁"。**

实测 6 条门禁读的文件与当前代码的指纹对比：

| 门禁 | 读的文件 | 产物指纹 | 当前代码 |
|---|---|---|---|
| `L6b` / `L8` | `a3-with-dedup.json` | `899e2b6-dirty` | `0fbc3d2-dirty` |
| `L6c` | `a3-lexical-vector-adjacency.json` | `899e2b6-dirty` | `0fbc3d2-dirty` |
| `F19b` / `F20` | `v2-*-condition-ablation.json` | `47e4785-dirty` | `0fbc3d2-dirty` |
| `F24` | `v2-*-lexical-vector-adjacency.json` | `47e4785-dirty` | `0fbc3d2-dirty` |

**没有一条读过当前装置的产物。** 而它们的 `passed` 值照样被计入"ledger 21/27、billing 24/27"。

这不是"门禁错了"，是**门禁的适用域没被表达**：一个 v2 装置的门禁在 v3 装置下当然仍能算出 v2 的数字，但那个数字不回答"当前装置怎么样"。

更危险的是 **`F24` 会反向变绿**：

| 配置 | A 轴 SEH@1 | F24 判据（< 0.9999） | 真实含义 |
|---|---|---|---|
| v2 三路（冻结） | 1.0000 | **红**（满分=测不到区分） | 装置健康，指标饱和 |
| v3 单路（实测） | 0.8333 | **绿** | **排序能力下降**，不是"不饱和" |

**同一个门禁，在两种装置下绿/红的意义相反。**

**第二条：`F24` 的分母混用了"全部 A 标注"与"已评分 A"。**

实现（`check_v2_dataset.py:1022-1027`）：

```python
dataset_a = {q.query_id for q in dataset.queries if q.axis is _Axis.A}
ranks = {c["case_id"]: c["rank_after_rerank"] for c in cases}
hit = sum(1 for qid in dataset_a if ranks.get(qid) == 1)
ratio = hit / len(dataset_a)          # <- 分母是全部 A 标注
```

`ranks.get(qid)` 对**未评分**（池不足 K 被 skip）的 case 返回 `None`，
`== 1` 为 False —— **算作未命中，但仍留在分母里**。

实测（`n_scored/len(dataset_a)`）：

| 文件 | A 标注 | 已评分 | hit | F24 口径 | 正确口径 |
|---|---|---|---|---|---|
| `v2-sample-lexical.json` | 10 | **6** | 6 | **0.6000** | **1.0000** |
| `v2-billing-lexical.json` | 9 | **7** | 7 | **0.7778** | **1.0000** |
| `v2-sample-threeway.json` | 10 | 10 | 9 | 0.9000 | 0.9000 |
| `v2-billing-lexical-vector-adjacency.json` | 9 | 9 | 9 | 1.0000 | 1.0000 |

**这不是 v3 引入的**：它在三路配置下恰好不显形（池够大，全部 case 都被评分），
只有单路配置会低报。而 `F24` 只 `glob` 三路文件 —— 所以**它自己的低报从未被自己发现**。

**两条为什么必须同一个变更**：修了适用域，`F24` 会在 v3 下返回"不适用"，
于是它内部的分母混用**会被那层"不适用"永久盖住**。
只做第一条，等于给一个已有缺陷加了一个更厚的遮蔽层。

## What Changes

**核心区分不是"读的文件新不新"，而是"判据是否依赖装置"。**

| 门禁 | 判据 | 依赖装置？ | 处置 |
|---|---|---|---|
| `L6b` | 池内向量都写入（范数非零） | ❌ | **照跑** |
| `L8` | dedup 收到的分数有方差 | ❌ | **照跑** |
| `L6c` | 三路召回都返回非空 | ❌ | **照跑** |
| `F19b` | implicit 的 gold 被召回 | ❌（召回不依赖排序） | **照跑** |
| `F20` | condition 对 A 轴有贡献 | **✅ 判据随装置消失** | 不适用 |
| `F24` | A 轴 SEH@1 不满分 | **✅ 阈值语义随装置反转** | 不适用 |

**只有 2 条，不是 6 条。** 把 `L6c` 判成"不适用"等于永久关掉一条
在 v3 下仍然有效的门禁——它测的是"三路召回都返回非空"，与 condition 加权无关。

**1. `Check` 增加"适用域"**

`applicable: bool = True`。`applicable=False` 时 `passed` MUST 为 False
（构造时校验）：**"不适用"不是"通过"**。

**2. 装置签名只依赖文件自身的结构事实**

| 格式 | 判据 | 为什么是结构事实 |
|---|---|---|
| 有 `per_case` | 有 `features` -> v3 | v2 的代码不写这个键 |
| 消融聚合 | 两轴逐条 rank 相同 -> v3 | condition 不参与加权，消融不改变名次 |

**不用 `apparatus` 常量字段**：常量可以说谎。若有人回退代码或抄旧脚本，
产出的文件仍会写 `apparatus: "v3"`——那就是一行常量。

**3. `F24` 的分母改为"已评分 A"**

```python
scored_a = [qid for qid in dataset_a if ranks.get(qid) is not None]
ratio = hit / len(scored_a) if scored_a else 0.0
```

**预期数字变化**（实测）：

| subject | 修前 | 修后 | 差异 |
|---|---|---|---|
| `sample` | 21/27 | **19/27** | -2（F20、F24） |
| `billing` | 24/27 | **23/27** | -1（F24 原就失败） |

`billing` 只减 1 的原因：F24 在 billing 上原本就被"满分"判为失败，
变成"不适用"后仍不是通过——通过数不变，但语义从"失败"变成"不适用"。

## Impact

- 代码：`evals/tools/check_v2_dataset.py`（`Check` 结构、`apparatus_signature`、
  `F20`/`F24` 的适用域分支、`F24` 分母）
- 测试：`test_gate_applicability.py`（分类）、`test_gate_apparatus_binding.py`（签名）、
  `test_f24_denominator.py`（分母）
- 数据：**无**
- 结果文件：**无**（不重跑、不新增、不改写）
- **既有测试的期望值**：8 条要改——
  - `test_f24_axis_a_saturation.py` 4 条：v2 装置下的行为，用 `monkeypatch`
    设回 `CURRENT_APPARATUS="v2"`
  - `test_fingerprint_tag_consistency.py` 2 条：比对时排除 `F20`/`F24`
    （它们的判定变化是有意产出，不是装置不确定性），并断言仍比对了 >= 25 条
  - `test_handoff_current.py` / `test_v2_sample_layers.py`：数字 21->19、24->23

## 验收

| # | 判据 | 可被违反的形式 |
|---|---|---|
| 1 | 分类正确 | **只有** `F20`/`F24` 不适用；`L6b`/`L8`/`L6c`/`F19b` 照跑 |
| 2 | 真实 v2 文件 | 2 条不适用、4 条给出真实结论 |
| 3 | **签名与内容矛盾** | 两份消融文件带相反的 `apparatus` 常量，签名必须按结构判 |
| 4 | `F24` 在单路配置上不再低报 | 用 `v2-sample-lexical.json` 断言 `1.0000` 而非 `0.6000` |
| 5 | **当前装置识别为 v3** | 否则"不适用"可能因签名算错而恒真——所有门禁静默变"不适" |
| 6 | **分类不能写宽** | 把 `L6c` 误判成"不适用"时测试必须红（已证伪） |
| 7 | 三路数字不变 | 修分母 MUST NOT 改变分母恰好等于已评分的文件 |

**验收 6 是这套判据的自检**：没有它，把 6 条全判"不适用"也能通过——
而那等于永久关掉 4 条有效门禁。

**验收 5 是这套判据的自检**：它保证"不适用"不是一个恒真的返回值。
没有它，签名函数写错会让 6 条门禁全部变成"不适用"，而全部显示为"已处置"。

## 不做的事

- **不跑 v3 数据**：本变更不产出结果文件，验收全在 `tmp_path` 与现有 v2 文件上完成
- **不改 `run_all()` 的通过数**：见上表
- **不修 `L6b`/`L8`/`L6c` 的读法**：它们读 `a3-*`，那是另一代产物；本变更只加适用域，不改它们的判据
