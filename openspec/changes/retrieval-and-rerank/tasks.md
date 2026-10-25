# Tasks

> TDD 顺序。设计见 `design.md`；契约见 `specs/`。
> **第一部分（补因变量与修索引）不可省**——没有它，后两部分的任何数字都无意义。

## 1. 让存储支持原文检索

- [x] 1.1 先写测试：`MemoryItem` 接受 `text` 字段、为空时兼容、
      在 `supersede` 时不被自动清空，
      验证：`uv run pytest tests/store/test_text_field.py -q` 全绿
- [x] 1.2 实现 `MemoryItem.text`（可空）与 DDL 列，
      验证：`uv run pytest tests/store/test_text_field.py -q` 全绿
- [x] 1.3 先写测试：`items_fts` 索引包含原文——
      用只在原文里出现的词能命中该条；
      且用 `bm25()` 排序（构造两条，相关性高者排前，与 version 顺序相反），
      验证：`uv run pytest tests/store/test_fts_bm25.py -q` 全绿
- [x] 1.4 实现索引内容变更与 `ORDER BY bm25(items_fts)`，
      验证：`uv run pytest tests/store/test_fts_bm25.py -q` 全绿
- [x] 1.5 实现 `evals/tools/rebuild_fts.py`（DROP + 重建 + 灌入，含条目数校验），
      验证：重建前后条目数一致，且原文可检索

## 2. 补评测因变量

- [x] 2.1 先写测试：`annotate_retrieval` 为每条场景补 `query` 与 `gold_item_id`；
      ADD 类（`existing_value is None`）的 gold 为 `null`；
      query 取原文而非拼接查找键，
      验证：`uv run pytest tests/retrieval/test_annotate.py -q` 全绿
- [x] 2.2 实现 `evals/tools/annotate_retrieval.py`，对 dev/test/independent 三份文件运行，
      验证：三份文件 100% 有 `query`，gold 覆盖率为 `非 ADD 条数 / 总数`
- [x] 2.3 先写测试：ADD 类不计入召回指标但被单独计数；
      gold 不在池中时报"池构建失败"而非静默跳过，
      验证：`uv run pytest tests/retrieval/test_annotate.py -q` 全绿

## 3. 候选池

- [x] 3.1 先写测试：池大小 = 1 + N（默认 21）；
      干扰项逻辑键互不相同；
      gold 必在池中且位置随场景变化；
      池大小 ≤ K 时抛错，
      验证：`uv run pytest tests/retrieval/test_pool.py -q` 全绿
- [x] 3.2 实现 `src/memory/retrieval/pool.py`（干扰项排除与 gold 同 subject 的条目），
      验证：`uv run pytest tests/retrieval/test_pool.py -q` 全绿
- [x] 3.3 先写测试：池能真实装进 `SqliteStore` 而**不触发 `ActiveExists`**
      （审查实测跨文件合并会撞 17 个重复键），
      验证：`uv run pytest tests/retrieval/test_pool_store.py -q` 全绿

## 4. 查询解析与条件槽位

- [x] 4.1 先写测试：条件槽位**中英双向**归一——
      `coding` 与 `写代码` 归一到同一键；`prod` 与 `生产` 同理；
      覆盖时间/场景/环境三类，每类至少两正一反，
      验证：`uv run pytest tests/retrieval/test_condition.py -q` 全绿
- [x] 4.2 实现 `parse_condition()` 返回 `{slot: value}` 与 `structured` 标记，
      验证：`uv run pytest tests/retrieval/test_condition.py -q` 全绿
- [x] 4.3 先写测试：`condition_match` 在同槽位、不同、一方为空三种情形下
      返回 1.0 / 0.0 / 0.5；Jaccard 语义正确，
      验证：`uv run pytest tests/retrieval/test_condition.py -q` 全绿
- [x] 4.4 实现 `condition_match()`，
      验证：`uv run pytest tests/retrieval/test_condition.py -q` 全绿
- [x] 4.5 用真实数据统计：三份场景文件的条件字符串里，
      `structured=True` 的比例是多少，并把数字记进报告，
      验证：`uv run python -m evals.tools.report_condition_coverage` 输出比例

## 5. 三路召回

- [x] 5.1 先写测试：词面召回按 BM25 降序、只返回 ACTIVE、
      能用原文命中的词召回，
      验证：`uv run pytest tests/retrieval/test_lexical.py -q` 全绿
- [x] 5.2 实现 `lexical.py`，
      验证：`uv run pytest tests/retrieval/test_lexical.py -q` 全绿
- [x] 5.3 先写测试：向量召回按余弦降序、跳过无向量条目、
      维度从 `meta` 读取并与候选校验（不符则报错而非静默跳过），
      验证：`uv run pytest tests/retrieval/test_vector.py -q` 全绿
- [x] 5.4 实现 `vector.py`（numpy 暴力余弦），
      验证：`uv run pytest tests/retrieval/test_vector.py -q` 全绿
- [x] 5.5 先写测试：条件兄弟邻接返回同键**不同 condition** 的条目、
      不含查询自身命中那条、跨主体不串味，
      验证：`uv run pytest tests/retrieval/test_adjacency.py -q` 全绿
- [x] 5.6 实现 `adjacency.py`（只做条件兄弟，不做跨关系），
      验证：`uv run pytest tests/retrieval/test_adjacency.py -q` 全绿
- [ ] 5.7 先写测试：单路可关、全关返回空、各路长度截断到同一上限，
      验证：`uv run pytest tests/retrieval/test_pipeline.py -q` 全绿

## 6. RRF 融合

- [x] 6.1 先写测试：多路前列优于单路前列（列表长度 < k+2 时）、
      单路退化为该路排名、k 修改导致顺序变化（用两列表 fixture）、
      量纲无关（BM25 大分数 + 余弦小分数不改变结果），
      验证：`uv run pytest tests/retrieval/test_fusion.py -q` 全绿
- [x] 6.2 实现 `fusion.py`，
      验证：`uv run pytest tests/retrieval/test_fusion.py -q` 全绿

## 7. 四特征重排

- [x] 7.1 先写测试：四个特征各自计算且**取值落在 [0,1]**（越界报错）、
      `rrf_norm` 归一化到最大值 1.0、
      条件缺失时返回 0.5、
      状态惩罚对 ACTIVE / SUPERSEDED / CONFLICTED 递减，
      验证：`uv run pytest tests/retrieval/test_rerank.py -q` 全绿
- [x] 7.2 实现四个特征函数，
      验证：`uv run pytest tests/retrieval/test_rerank.py -q` 全绿
- [x] 7.3 先写测试：权重和必须为 1（否则拒绝）；
      全关时退化为 `rrf_norm` 排序**且不触发权重校验**；
      单特征主导时排序符合该特征，
      验证：`uv run pytest tests/retrieval/test_rerank.py -q` 全绿
- [x] 7.4 实现加权求和与权重校验（全关走独立分支），
      验证：`uv run pytest tests/retrieval/test_rerank.py -q` 全绿
- [x] 7.5 先写测试：**每个特征在真实候选池上必须有权重外方差**——
      若某特征对所有候选返回同一值，测试失败并指出该特征退化，
      验证：`uv run pytest tests/retrieval/test_rerank_variance.py -q` 全绿

## 8. 语义等价与去重

- [ ] 8.1 先写测试：三分类解析（等义/互补/无关）；
      乱码归为"无关"且失败计数递增；
      复用 C1 缓存后第二次零请求，
      验证：`uv run pytest tests/retrieval/test_equivalence.py -q` 全绿
- [ ] 8.2 实现 `equivalence.py`，
      验证：`uv run pytest tests/retrieval/test_equivalence.py -q` 全绿
- [ ] 8.3 先写测试：去重阶段把 top-K 内判为"等义"的候选合并，
      保留融合分更高者；**去重前后候选数变化可观测**；
      关闭等义判断时去重不生效，
      验证：`uv run pytest tests/retrieval/test_dedup.py -q` 全绿
- [ ] 8.4 实现去重阶段接入 pipeline，
      验证：`uv run pytest tests/retrieval/test_dedup.py -q` 全绿
- [ ] 8.5 用 C3 独立集的 9 对真实样本做**分类别**评估：
      MERGE 类 ≥5/6 **且** NOOP 类 ≥2/3，各自报告；
      该测试 MUST 使用缓存的 fixture、**不带 network 标记**（保证进默认门禁），
      验证：`uv run pytest tests/retrieval/test_equivalence_real.py -q` 通过

## 9. 指标与归因

- [x] 9.1 先写测试：SEH@K、SRS = 1/rank（rank 1/2/5 → 1.0/0.5/0.2）、
      未召回 SRS = 0、K ≥ 池大小时抛错、
      连续值 SRS 的配对 bootstrap 可用，
      验证：`uv run pytest tests/retrieval/test_metrics.py -q` 全绿
- [x] 9.2 实现 `evals/metrics/retrieval.py`（含连续值配对区间），
      验证：`uv run pytest tests/retrieval/test_metrics.py -q` 全绿
- [x] 9.3 先写测试：三类归因互斥且完备（池外 / 排序过低 / 重排丢弃）；
      用假 LLM 断言归因**零模型调用**；
      保留未截断融合列表使"排序过低"可观测，
      验证：`uv run pytest tests/retrieval/test_attribution.py -q` 全绿
- [x] 9.4 实现 `attribution.py`，
      验证：`uv run pytest tests/retrieval/test_attribution.py -q` 全绿

## 10. 评测与消融

- [ ] 10.1 先写测试：入口支持 `--split`、`--disable-path`、
      `--disable-feature`、`--disable-dedup`、`--weights <name>`；
      预注册 5 组权重都能加载；非法权重和报错，
      验证：`uv run pytest tests/retrieval/test_run.py -q` 全绿
- [ ] 10.2 实现 `evals/run_retrieval.py` 与预注册权重组，
      验证：`uv run pytest tests/retrieval/test_run.py -q` 全绿
- [ ] 10.3 先写测试：结果 JSON 记录运行 id 与**运行次数**，
      重复运行同一配置会累加计数（使"test 只跑一次"可验证），
      验证：`uv run pytest tests/retrieval/test_run.py -q` 全绿
- [ ] 10.4 跑路径消融（三路各关 + 全关）与特征消融（四特征各关 + 全关），
      产出 `results/retrieval-ablation.json`，
      验证：每组配置的样本数与 gold 数一致
- [ ] 10.5 跑预注册 5 组权重 × 三个集，产出 `results/retrieval-weights.json`，
      并计算最小可检测效应写进报告，
      验证：三集 × 5 组共 15 行，无缺失
- [ ] 10.6 生成 `docs/reports/c4-retrieval.md`：主表（三集 × 5 组权重）、
      路径消融、特征消融、条件覆盖率、等义调用次数与命中数、
      三类归因分布、最小可检测效应，
      验证：报告数字与 JSON 一致（加一致性测试）

## 11. 文档与门禁

- [ ] 11.1 编写 `docs/retrieval.md`：三路召回定义、RRF 为何不用加权、
      四特征定义与值域约定、条件槽位的中英映射与覆盖率、
      等义判断的边界（**不改写路径**）、
      暴力余弦的规模上限（10^6 条时重构）、
      SRS 的唯一定义（1/rank），
      验证：文档中命令按原样可执行
- [ ] 11.2 全量门禁：`uv run pytest -q`、`uv run ruff check`、`uv run mypy src`、
      `openspec validate retrieval-and-rerank --strict`，
      验证：四条命令均以 0 退出并贴出原始输出
- [ ] 11.3 在报告顶部声明：**本变更不改写路径，C3 的 50.0% 不变**；
      检索改善不得被表述为判定能力提升，
      验证：报告首段包含该声明

## Workflow follow-up

- 审稿通过后归档该变更。
