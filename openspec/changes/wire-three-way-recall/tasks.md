# Tasks

按 TDD 顺序：每个行为先写会失败的测试，再实现。

## 1. 评测入口的可观测性（先让"跑没跑"可见）

- [ ] 1.1 在 `evaluate()` 的结果里增加 `path_returns: dict[str, int]`，记录每路返回条数。
  验证：`uv run --no-sync pytest tests/retrieval/test_run_retrieval.py -q` 新增用例断言
  这个键存在且三路都在；当前应失败（只记录 lexical 一路）
- [ ] 1.2 加 `--paths` 参数（逗号分隔，默认 `lexical,vector,adjacency`），
  并让空列表等于"零召回基线"。
  验证：`uv run --no-sync python -m evals.run_retrieval --split dev --paths "" --no-dedup`
  输出 `SEH@5=0.000`（不是 1.000）

## 2. 池内写入向量

- [ ] 2.1 `_item()` 增加可选 `embedding` 参数；建池时对每条候选生成
  `document` 侧向量并随 `store.insert(..., embedding=...)` 写入。
  验证：`uv run --no-sync pytest tests/retrieval/test_run_retrieval.py -q`
  新增用例断言池内每条都有向量（查 `vec_items` 行数 == 池大小）
- [ ] 2.2 查询侧生成 `query` 侧向量并调用 `recall_by_vector`。
  验证：`uv run --no-sync python -m evals.run_retrieval --split dev --paths vector --no-dedup`
  的 `path_returns["vector"] > 0`（当前应为 0）
- [ ] 2.3 结果 JSON 记录 embedding 网络调用次数。
  验证：同一命令连跑两次，第二次 `embedding_network_calls == 0`（缓存命中）

## 3. 邻接路径接入

- [ ] 3.1 用 gold 的逻辑键调用 `recall_by_adjacency`，并把结果并入 `rrf()`。
  验证：`--paths adjacency --no-dedup` 在 `dev` 上 `path_returns["adjacency"] > 0`
- [ ] 3.2 记录邻接召回的"gold 之外的条目数"。
  验证：新增测试断言该计数等于 `len(adjacency) - (1 if gold in adjacency else 0)`，
  且结果 JSON 里字段存在
- [ ] 3.3 三路一起进 `rrf()`，各路线性可关。
  验证：`--paths lexical,vector` 与 `--paths lexical,vector,adjacency` 的
  `path_returns` 键集合不同，且关闭的那一路不在其中

## 4. `dedup` 传参修正（设计决策 1 与 2）

- [ ] 4.1 写失败测试：断言 `dedup` 收到的第二字段等于 `item.text`、分数有方差。
  验证：`uv run --no-sync pytest tests/retrieval/test_run_retrieval.py -q -k dedup_inputs`
  先红
- [ ] 4.2 用一条 `SELECT id, source_text FROM items WHERE id IN (...)` 批量回读文本，
  把 `(id, text, rrf_score)` 传给 `dedup`。
  验证：4.1 的测试转绿；`uv run --no-sync pytest tests/retrieval/test_dedup.py -q` 13 条仍全绿
- [ ] 4.3 把去重移到重排之前（融合 → 去重 → 重排），并在代码注释里写明理由。
  验证：新增测试断言"全部判无关时输出顺序 == 输入顺序"（常数分数不再重排），
  且 `--no-dedup` 与默认配置的 `path_returns` 相同、`rank_after_rerank` 可不同

## 5. 单路回归（A5）

- [ ] 5.1 用 `--paths lexical` 重跑 `dev` / `independent`，
  写到 `results/retrieval-a5-regression-*.json`（**不覆盖** `retrieval-test-*`）。
  验证：新文件里 `"purpose": "A5 regression..."`，且 `retrieval-run-count.json`
  里 `retrieval-test-*` 的计数仍为 1
- [ ] 5.2 逐位对比归档结果的 `rank_after_fusion` 与 `rank_after_rerank`。
  验证：新增测试读归档 JSON 与回归 JSON，断言 26/26 条 `rank_after_fusion` 完全相同；
  若不同则列出差异 case，不静默通过

## 6. 路径贡献对比（A3）

- [ ] 6.1 在样例数据集上跑"三路全开"与"只开词面"两组，输出 `SEH@1` 及配对 bootstrap 区间。
  验证：`uv run --no-sync python -m evals.run_retrieval --dataset data/retrieval-v2/sample ...`
  产出一份对比 JSON，含两组点估计与区间
- [ ] 6.2 把差异写进 `docs/reports/v2-sample-validation.md`：
  有差异写差异，无差异写"新增路径在该数据上没有可观测贡献"。
  验证：报告里出现具体的两组 `SEH@1` 数字；测试断言报告含该对比段

## 7. 门禁与清单收敛

- [ ] 7.1 把 `check_v2_dataset.py` 的 L6a/L6b/L6c/L7/L8 从"查源码"升级为"真实断言"
  （读评测入口的结果 JSON）。
  验证：`uv run --no-sync python -m evals.tools.check_v2_dataset data/retrieval-v2/sample`
  的这五项转绿，总通过数从 11/17 上升
- [ ] 7.2 更新 `docs/reports/c4-retrieval.md` 第 0.1 节：缺陷 7、8 标为已修复，
  附 A3 差异数据与 A5 回归结论。
  验证：`uv run --no-sync pytest tests/retrieval/test_c4_leak_disclosure.py -q` 先红后绿
- [ ] 7.3 把对应 `locked_defect` 测试改成正向断言（缺陷 7、8 各两条），
  **不删除**其余条目。
  验证：`uv run --no-sync pytest -m locked_defect --collect-only -q` 的用例数
  从 12 降到 8；`tests/retrieval/test_locked_defect_manifest.py` 同步更新映射表并通过
- [ ] 7.4 更新 `tests/retrieval/test_v2_sample_report.py` 里对门禁数字的断言。
  验证：`uv run --no-sync pytest tests/retrieval -q` 全绿

## 8. 质量门禁

- [ ] 8.1 `uv run --no-sync pytest -q` 全绿（贴原始输出）
- [ ] 8.2 `uv run --no-sync ruff check .` 与 `uv run --no-sync mypy` 通过（贴原始输出）
- [ ] 8.3 `openspec validate wire-three-way-recall --strict` 通过（贴原始输出）

## Workflow follow-up

- 评审通过后归档本变更。
- 归档后打 tag `three-way-wired`，然后才开始铺 v2 的 15 个 subject。
