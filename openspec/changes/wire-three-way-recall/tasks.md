# Tasks

按 TDD 顺序：每个行为先写会失败的测试，再实现。

## 1. 评测入口的可观测性（先让"跑没跑"可见）

- [x] 1.1 在 `evaluate()` 的结果里增加 `path_returns: dict[str, int]`，记录每路返回条数。
  验证：`uv run --no-sync pytest tests/retrieval/test_run_retrieval.py -q` 新增用例断言
  这个键存在且三路都在；当前应失败（只记录 lexical 一路）
- [x] 1.2 加 `--paths` 参数（逗号分隔，默认 `lexical,vector,adjacency`），
  并让空列表等于"零召回基线"。
  验证：`uv run --no-sync python -m evals.run_retrieval --split dev --paths "" --no-dedup`
  输出 `SEH@5=0.000`（不是 1.000）

## 2. 池内写入向量

- [x] 2.1 `_item()` 增加可选 `embedding` 参数；建池时对每条候选生成
  `document` 侧向量并随 `store.insert(..., embedding=...)` 写入。
  验证：`uv run --no-sync pytest tests/retrieval/test_run_retrieval.py -q`
  新增用例断言池内每条都有向量（查 `vec_items` 行数 == 池大小）
- [x] 2.2 查询侧生成 `query` 侧向量并调用 `recall_by_vector`。
  验证：`uv run --no-sync python -m evals.run_retrieval --split dev --paths vector --no-dedup`
  的 `path_returns["vector"] > 0`（当前应为 0）
- [x] 2.3 结果 JSON 记录 embedding 网络调用次数。
  验证：同一命令连跑两次，第二次 `embedding_network_calls == 0`（缓存命中）

## 3. 邻接路径接入

- [x] 3.1 用 gold 的逻辑键调用 `recall_by_adjacency`，并把结果并入 `rrf()`。
  验证：`--paths adjacency --no-dedup` 在 `dev` 上 `path_returns["adjacency"] > 0`
- [x] 3.2 记录邻接召回的"gold 之外的条目数"。
  验证：新增测试断言该计数等于 `len(adjacency) - (1 if gold in adjacency else 0)`，
  且结果 JSON 里字段存在
- [x] 3.3 三路一起进 `rrf()`，各路线性可关。
  验证：`--paths lexical,vector` 与 `--paths lexical,vector,adjacency` 的
  `path_returns` 键集合不同，且关闭的那一路不在其中

## 4. `dedup` 传参修正（设计决策 1 与 2）

- [x] 4.1 写失败测试：断言 `dedup` 收到的第二字段等于 `item.text`、分数有方差。
  验证：`uv run --no-sync pytest tests/retrieval/test_run_retrieval.py -q -k dedup_inputs`
  先红
- [x] 4.2 用一条 `SELECT id, source_text FROM items WHERE id IN (...)` 批量回读文本，
  把 `(id, text, rrf_score)` 传给 `dedup`。
  验证：4.1 的测试转绿；`uv run --no-sync pytest tests/retrieval/test_dedup.py -q` 13 条仍全绿
- [x] 4.3 把去重移到重排之前（融合 → 去重 → 重排），并在代码注释里写明理由。
  验证：新增测试断言"全部判无关时输出顺序 == 输入顺序"（常数分数不再重排），
  且 `--no-dedup` 与默认配置的 `path_returns` 相同、`rank_after_rerank` 可不同

## 5. 单路回归（A5）

- [x] 5.1 用 `--paths lexical` 重跑 `dev`，与归档逐条比对。
  **原计划写到 `results/retrieval-a5-regression-*.json`，实际改为在进程内重跑**
  （`test_a5_regression.py` 直接调 `evaluate()`），理由：A5 的目的是"证明单开词面时
  算法未变"，逐条比对已经做到；多一份文件只是多一个副本，而 `results/` 里的文件越少，
  被误引用的机会越小。这一偏差如实记在这里，不假装产物存在。
- [x] 5.2 逐位对比归档结果的 `rank_after_fusion`、`rank_after_rerank`、`attribution`、
  top-1 稳定 tag（A5-a）。**A5-b（完整融合序列）本项不覆盖：旧集不可执行，仅 v2 适用。**
  验证：`uv run --no-sync pytest tests/retrieval/test_a5_regression.py -q` 全绿；
  若不同则列出差异 case，不静默通过
- [x] 5.3 锁住 A5-b 的可执行前提：融合序列必须用**稳定 tag** 而非 uuid4。
  验证：`test_fusion_tags_are_stable_across_runs` 与
  `test_fusion_tags_never_contain_uuid` 通过

## 6. 路径贡献对比（A3）

- [x] 6.1 跑"三路全开"与"只开词面"两组（**实际在 `dev` 上跑，不是样例数据集**），
  输出 `SEH@1` / MRR。
  **偏差说明**：原计划在 `data/retrieval-v2/sample` 上跑，实测 `--dataset`
  指向 v2 目录会报 `PermissionError`（`run_retrieval` 只认 `.jsonl` 行格式，
  v2 是目录 + 不同字段结构）。v2 适配层未实现，记在后面的待办里。
  验证：`results/a3-lexical.json` / `a3-lexical-vector.json` /
  `a3-lexical-vector-adjacency.json` 三份同 fingerprint
- [x] 6.2 把差异写进 **`docs/reports/three-way-recall.md`**（新建，不是
  `v2-sample-validation.md`）。
  **偏差说明**：C4 报告已 10 章 40KB，且其主题是"为什么 1.000 不算能力"；
  三路实测是另一件事，混进去会让"修好装置"读成"修完变差了"。
  验证：`tests/retrieval/test_three_way_report.py` 10 条，报告数字可复算

## 7. 门禁与清单收敛

- [x] 7.1a **L6c** 从"查源码"升级为"读真实运行结果"
  （`results/a3-lexical-vector-adjacency.json` 的 `path_returns`）。
  验证：`check_v2_dataset` 的 L6c 显示 `{'lexical': 41, 'vector': 462, 'adjacency': 13}`
- [x] 7.1b **L6a + L6b** 改为读三路运行结果。
  L6a 判 `path_returns` 三路都 > 0 且 `paths_unwired` 为空；
  L6b 判每条 case 的 `pool_vectors == pool_size` 且 `min(pool_vector_norms) > 0.5`。
  **docstring 必须写明**：实测 462 条向量范数落在 [0.9996, 1.0004]（8 个不同值），
  判据在当前数据上恒真——它是"防止将来写坏"的门禁，不是"证明现在写对了"
- [x] 7.1c **L8** 改为读 `results/a3-with-dedup.json` 的 `dedup_input_scores`，
  断言每组分数有方差。验证：33/33 条 case 的 scores 都有方差
- [x] 7.1d **L7** 保持独立测试，**不从结果文件判**，并在 docstring 写明原因：
  `dedup_input_tags` 记的是"哪几条进了 dedup"，不是"传了什么文本"；
  用结果文件判 L7 会判错对象（这正是它此前"通过但没测到"的根源）
- [x] 7.2 更新 `docs/reports/c4-retrieval.md` 第 0.1 节：缺陷 7、8 标为已修复，
  附 A3 差异数据与 A5 回归结论。
  验证：`uv run --no-sync pytest tests/retrieval/test_c4_leak_disclosure.py -q` 先红后绿
- [x] 7.3 把对应 `locked_defect` 测试改成正向断言（缺陷 7、8 各两条），
  **不删除**其余条目。
  验证：`uv run --no-sync pytest -m locked_defect --collect-only -q` 的用例数
  从 12 降到 8；`tests/retrieval/test_locked_defect_manifest.py` 同步更新映射表并通过
- [x] 7.4 更新 `tests/retrieval/test_v2_sample_report.py` 里对门禁数字的断言。
  验证：`uv run --no-sync pytest tests/retrieval -q` 全绿

## 8. 质量门禁

- [x] 8.1 `uv run --no-sync pytest -q` 全绿（贴原始输出）
- [x] 8.2 `uv run --no-sync ruff check .` 与 `uv run --no-sync mypy` 通过（贴原始输出）
- [x] 8.3 `openspec validate wire-three-way-recall --strict` 通过（贴原始输出）

## Workflow follow-up

- 评审通过后归档本变更。
- 归档后打 tag `three-way-wired`，然后才开始铺 v2 的 15 个 subject。
