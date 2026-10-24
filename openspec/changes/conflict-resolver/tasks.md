# Tasks

> TDD 顺序：每组先写会失败的测试，再写实现。
> 设计见 `design.md`；契约见 `specs/conflict-resolution/spec.md`。

## 1. 归一化

- [x] 1.1 先写测试：大小写、首尾空白、全角半角归一到同一结果；
      常见复数（`managers` → `manager`）归一；
      **未登记的表述保留原值且标记 `normalized=False`**，
      验证：`uv run pytest tests/resolver/test_normalize.py -q` 全绿
- [x] 1.2 实现 `src/memory/resolver/normalize.py`（`NormalizedKey`、
      别名表、基础归一函数），
      验证：`uv run pytest tests/resolver/test_normalize.py -q` 全绿
- [x] 1.3 先写测试：归一化后为空的主体/关系被拒绝并报错；
      归一化不合并不同主体（构造近似但不同的两个主体，断言键不同），
      验证：`uv run pytest tests/resolver/test_normalize.py -q` 全绿
- [x] 1.4 补上拒绝与隔离逻辑，
      验证：`uv run pytest tests/resolver/test_normalize.py -q` 全绿

## 2. 判定类型与规则

- [x] 2.1 先写测试：`DecisionKind` 六值齐全；`Decision` 含
      `kind / rule / key / existing_id / change_source / normalized /
      existing_value / candidate_value`，且可 JSON 序列化，
      验证：`uv run pytest tests/resolver/test_decision.py -q` 全绿
- [x] 2.2 实现 `src/memory/resolver/rules.py` 的 `Decision` 与 `DecisionKind`，
      验证：`uv run pytest tests/resolver/test_decision.py -q` 全绿
- [x] 2.3 先写测试：七条规则逐条命中（每条至少两个用例），
      验证：`uv run pytest tests/resolver/test_rules.py -q` 全绿
- [x] 2.4 实现七条有序规则，
      验证：`uv run pytest tests/resolver/test_rules.py -q` 全绿
- [x] 2.5 先写测试：**多规则同时匹配时取第一条**——构造
      "值相同 + 条件不同 + 权威更低"的输入，断言结果为 `NOOP` 而非 `BRANCH`/`CONFLICT`；
      另构造"值包含 + 权威更低"，断言为 `MERGE` 而非 `CONFLICT`，
      验证：`uv run pytest tests/resolver/test_rule_order.py -q` 全绿
- [x] 2.6 若 2.5 失败则调整顺序并说明依据；通过后保持，
      验证：`uv run pytest tests/resolver/test_rule_order.py -q` 全绿
- [x] 2.7 先写测试：兜底完备性——用 hypothesis 随机组合输入，
      断言每次都返回六类之一且不抛异常，
      验证：`uv run pytest tests/resolver/test_completeness.py -q`（200 例）全绿

## 3. 变更识别

- [x] 3.1 先写测试：正则覆盖"改成 / 现在 / 不再 / 以前…现在… / 换成 / 改用"，
      每个标记至少一条正例与一条反例（如"没有改"不应命中），
      验证：`uv run pytest tests/resolver/test_change_marker.py -q` 全绿
- [x] 3.2 实现 `src/memory/resolver/change_marker.py` 的规则部分，
      验证：`uv run pytest tests/resolver/test_change_marker.py -q` 全绿
- [x] 3.3 先写测试：规则未命中时调用模型；模型返回可解析布尔时正确返回；
      模型返回乱码时视为"无法确认"；模型抛异常时不吞掉而是标记 `failed`，
      验证：`uv run pytest tests/resolver/test_change_marker_llm.py -q` 全绿
- [x] 3.4 实现 LLM 兜底（复用 C1 的 `LLMClient` 与响应缓存），
      验证：`uv run pytest tests/resolver/test_change_marker_llm.py -q` 全绿
- [x] 3.5 先写测试：`disabled` 模式下完全不调用模型，
      未命中标记的候选一律走 `CONFLICT` 兜底，
      验证：`uv run pytest tests/resolver/test_no_llm.py -q` 全绿
- [x] 3.6 实现禁用模式与 `change_source` 的四种取值（rule/llm/disabled/failed），
      验证：`uv run pytest tests/resolver/test_no_llm.py -q` 全绿

## 4. 判定编排与存储映射

- [x] 4.1 先写测试：`decide()` 不写库（调用前后 `count()` 不变），
      验证：`uv run pytest tests/resolver/test_decide_only.py -q` 全绿
- [x] 4.2 实现 `src/memory/resolver/resolver.py` 的 `decide()`，
      验证：`uv run pytest tests/resolver/test_decide_only.py -q` 全绿
- [x] 4.3 先写测试：六类各自的 `apply()` 后库状态符合预期——
      `NOOP` 条数不变、`ADD` 新增一条、`MERGE`/`SUPERSEDE` 旧条目转 SUPERSEDED 且区间相邻、
      `CONFLICT` 既有条目仍 ACTIVE 且新条目为 CONFLICTED、
      `BRANCH` 两条均为 ACTIVE，
      验证：`uv run pytest tests/resolver/test_apply.py -q` 全绿
- [x] 4.4 实现 `apply()` 的六类映射，
      验证：`uv run pytest tests/resolver/test_apply.py -q` 全绿
- [x] 4.5 先写测试：`MERGE` 与 `SUPERSEDE` 在时间线上的 `reason` 不同
      （"补充" vs "取代"），且都能与既有条目关联，
      验证：`uv run pytest tests/resolver/test_merge_vs_supersede.py -q` 全绿
- [x] 4.6 实现两种 reason 的区分，
      验证：`uv run pytest tests/resolver/test_merge_vs_supersede.py -q` 全绿
- [x] 4.7 先写测试：存储失败时不留半成品、错误信息含判定类型，
      验证：`uv run pytest tests/resolver/test_apply_failure.py -q` 全绿
- [x] 4.8 实现失败路径，
      验证：`uv run pytest tests/resolver/test_apply_failure.py -q` 全绿

## 5. 场景集

- [x] 5.1 编写 60 条场景（`data/conflict-set/dev.jsonl` 40 条 +
      `test.jsonl` 20 条），六类各 10 条，中文为主、英文各 2 条对照；
      每条含 `id / text / existing / candidate / expected / label_status="proposed"`，
      验证：`uv run python -m evals.tools.label list --status proposed` 列出 60 条
- [x] 5.2 先写测试：加载器校验 schema（缺字段、非法 expected、
      六类分布不均衡时报警），
      验证：`uv run pytest tests/resolver/test_conflict_set.py -q` 全绿
- [x] 5.3 实现 `evals/datasets/conflict_set.py`，
      验证：`uv run pytest tests/resolver/test_conflict_set.py -q` 全绿
- [x] 5.4 先写测试：`label.py confirm` 改变标签状态并记录确认者与时间；
      `list` 能按状态筛选；非法标签被拒绝，
      验证：`uv run pytest tests/resolver/test_label_tool.py -q` 全绿
- [x] 5.5 实现 `evals/tools/label.py`（`list` / `confirm` / `kappa`），
      验证：`uv run pytest tests/resolver/test_label_tool.py -q` 全绿

## 6. 判定指标

- [x] 6.1 先写测试：混淆矩阵行列语义正确（行=期望，列=预测）、
      六类齐全、单类无样本时不计入 macro-F1 分母，
      验证：`uv run pytest tests/resolver/test_classification_metrics.py -q` 全绿
- [x] 6.2 实现 `evals/metrics/classification.py`（混淆矩阵 + macro-F1），
      验证：`uv run pytest tests/resolver/test_classification_metrics.py -q` 全绿
- [x] 6.3 先写测试：macro-F1 在"某类全错、其余全对"时明显低于总体准确率；
      逐类区间含样本数；同种子可复现，
      验证：`uv run pytest tests/resolver/test_classification_metrics.py -q` 全绿
- [x] 6.4 补上逐类 bootstrap 区间与样本数标注，
      验证：`uv run pytest tests/resolver/test_classification_metrics.py -q` 全绿
- [x] 6.5 先写测试：Cohen's κ 计算正确（完全一致=1、完全相反<0、随机水平≈0），
      验证：`uv run pytest tests/resolver/test_kappa.py -q` 全绿
- [x] 6.6 实现 κ 计算与不一致条目列出，
      验证：`uv run pytest tests/resolver/test_kappa.py -q` 全绿

## 7. 评测入口与消融

- [x] 7.1 先写测试：`evals/run.py` 支持 `--bench conflict-set --split test`
      并在标签为 `proposed` 时拒绝作为验收依据（打印醒目警告），
      验证：`uv run pytest tests/resolver/test_run_entry.py -q` 全绿
- [x] 7.2 实现评测入口，
      验证：`uv run pytest tests/resolver/test_run_entry.py -q` 全绿
- [x] 7.3 跑全量模式与 `--no-llm` 消融，产出
      `docs/reports/c3-resolver.md`（混淆矩阵、macro-F1、逐类区间、
      两模式差异、`change_source` 分布、`normalized=false` 比例），
      验证：报告中的数字与结果 JSON 一致（加一条一致性测试）
- [x] 7.4 编写 `docs/resolver.md`：六类定义、规则优先级与顺序依据、
      MERGE/SUPERSEDE 的区别、模型兜底的边界、标签状态的含义，
      验证：文档中的命令按原样可执行

## 8. 门禁与交付

- [x] 8.1 全量门禁：`uv run pytest -q`、`uv run ruff check`、`uv run mypy src`、
      `openspec validate conflict-resolver --strict`，
      验证：四条命令均以 0 退出并贴出原始输出
- [x] 8.2 在报告顶部写明**标签尚未人工确认**（若届时仍未确认），
      并给出待确认条目数量与确认命令，
      验证：报告首段包含该声明

## Workflow follow-up

- 标签人工确认后重跑并更新报告，再归档该变更。
