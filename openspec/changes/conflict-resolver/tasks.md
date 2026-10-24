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

## 9. 标注工具补强（C3 收尾，标签确认的前置条件）

> 起因：交付标注教程时发现两个缺陷——60 条手敲 `confirm` 命令不现实；
> 且 `kappa` 无法支持真正的双人标注（一条场景只有一个 `labeler` 字段，
> 两人标同一份文件会互相覆盖）。

- [x] 9.1 先写测试：交互式标注默认**不显示提案标签**（盲标），
      显示提案会让标注者跟着走，标签失去独立性；
      另有一条对照组断言 `--show-expected` 时确实显示，
      验证：`uv run pytest tests/resolver/test_label_review.py -q` 全绿
- [x] 9.2 实现 `ReviewSession` 与 `review()`：输入/输出通过参数注入，
      使整个流程可在测试中驱动而无需真实 stdin
      （`inputs` / `output` 两个参数），
      验证：`uv run pytest tests/resolver/test_label_review.py -q` 全绿
- [x] 9.3 先写测试：标完一条立即落盘（中途退出不丢进度）、
      `s` 跳过、`b` 回退到 `proposed`、`q` 退出并汇总、
      非法输入重新提问而不是退出、已确认条目自动跳过，
      验证：`uv run pytest tests/resolver/test_label_review.py -q` 全绿
- [x] 9.4 先写测试：κ 必须是**多类别**口径；
      从两份文件读取时用 `expected` 而不是 `labeler`
      （后者在同义反复），并列出不一致条目与漏标条目，
      验证：`uv run pytest tests/resolver/test_kappa_files.py -q` 全绿
- [x] 9.5 实现 `kappa_from_files`（返回 κ、共同条目数、不一致列表、
      仅单侧标注列表、判定文本），
      验证：`uv run pytest tests/resolver/test_kappa_files.py -q` 全绿
- [x] 9.6 给命令行加 `--file`（用于双人副本）与 `review` 子命令、
      `kappa --a-file/--b-file`，
      验证：`uv run python -m evals.tools.label --help` 与
      `... review --help` 均正常输出四类命令
- [x] 9.7 端到端冒烟：在临时副本上跑完 20 条交互标注，
      再造一份有一处差异的副本算 κ，
      验证：κ 输出且精确定位到那一条不一致；清理临时文件后真实数据仍为 0 条确认
- [x] 9.8 更新 `docs/resolver.md` 的标注章节（交互式用法、盲标理由、
      回退语义、双人副本流程、κ 阈值表），
      验证：文档中的命令按原样可执行

## 10. 场景集修正（标注时发现的真实错误）

> 起因：人工标注时跳过 4 条，核对后确认它们的配对不满足 CONFLICT 的前提
> （同一属性、同一对象、同一取值槽位上的两个竞争值）。

- [x] 10.1 定位并分析 4 条无效 CONFLICT 配对：
      `dev-conf-01`（偏好 vs 医学限制）、`dev-conf-02`（"能接受"语义模糊）、
      `dev-conf-05`（云厂商 vs 编排平台）、`test-conf-01`（同类不同对象），
      验证：报告中逐条列出原配对、问题类型与修正后的配对
- [x] 10.2 修正 4 条场景内容（**修而不删**——删掉后每类只剩 2~3 条，
      F1 方差会大到没有意义），
      验证：`uv run python -m evals.tools.build_conflict_set` 后
      4 条的新配对在语义上确实互斥
- [x] 10.3 先写测试：标签迁移脚本只迁移 `confirmed` 条目的
      `expected / labeler / confirmed_at` 三个字段，
      内容字段以新文件为准（防止把修好的内容覆盖回去），
      且报告旧文件里已不存在的 id，
      验证：`uv run pytest tests/resolver/test_preserve_labels.py -q` 全绿
- [x] 10.4 实现 `evals/tools/preserve_labels.py` 并执行：
      37 条 dev + 19 条 test 的已确认标签成功迁移，4 条修正项保持 `proposed`，
      验证：`label summary` 显示 dev 37/40、test 19/20
- [x] 10.5 先写测试：CONFLICT 配对跑一遍规则后必须判成 CONFLICT，
      不得被判成 MERGE（**不能用"两个值互不为子串"来断言**——
      中文否定词会让短串成为长串的子串），
      验证：`uv run pytest tests/resolver/test_report_consistency.py -q` 全绿
- [x] 10.6 修复测试暴露的真缺陷：`"吃牛肉"` 是 `"不吃牛肉"` 的子串，
      规则 4 把语义反转判成了 MERGE。改为检测值的**开头**是否带否定词，
      两侧否定状态不同则绝不判 MERGE，
      验证：`uv run pytest tests/resolver/test_rules.py -q` 全绿（含 5 条否定变体）
- [x] 10.7 记录并修复第一次修复引入的回归：用"前 8 字符包含否定词"会让
      `"张三 周三不在"` 被误判成否定，dev 准确率掉到 97.5%；
      改为只检查开头后恢复 100%，并补回归测试，
      验证：`test_rule4_mid_value_negation_does_not_block_merge` 通过
- [x] 10.8 把 CONFLICT 的构造纪律写进 `docs/resolver.md`
      （判定前提、三类典型错误、为什么测试抓不到、本次修正记录），
      验证：报告中同时出现"互斥"与 `dev-conf-01`
- [x] 10.9 更新报告：标签进度改为 56/60、新增修正章节、
      待办列表勾掉第 1 项，
      验证：一致性测试的进度断言通过
- [x] 10.10 清理临时标注副本并加入 `.gitignore`，
      验证：`data/conflict-set/` 只剩 `dev.jsonl` 与 `test.jsonl`

## 11. 独立复核模式（第二标注者的可用性缺陷）

> 起因：`review` 只挑 `proposed` 条目。副本从已标注文件复制而来会继承
> `confirmed` 状态，第二标注者只被问到剩下那一两条，κ 退化成 n=1。

- [x] 11.1 先写测试：`include_confirmed=True` 时问全部条目并覆盖原标注者；
      默认模式仍只问 `proposed`（补充标注的行为不能被破坏），
      验证：`uv run pytest tests/resolver/test_review_all.py -q` 全绿
- [x] 11.2 实现 `ReviewSession(include_confirmed=...)` 与 `review(...)` 的透传，
      验证：`uv run pytest tests/resolver/test_review_all.py -q` 全绿
- [x] 11.3 先写测试：`--all` 必须拒绝作用于主标注文件（`test.jsonl`），
      只允许副本（`test.bob.jsonl` 这类），`--force` 可显式绕过，
      验证：主文件被拒时抛 `ValueError` 且消息含"副本"
- [x] 11.4 实现 `_looks_like_copy()` 文件名判断与 `force` 开关，
      验证：`echo x | uv run python -m evals.tools.label --split test review
      --labeler bob --all` 退出码 2
- [x] 11.5 先写测试：`new-annotator` 一条命令完成"复制 + 重置"，
      重置 `label_status`/`labeler`/`confirmed_at` 但保留内容；
      副本已存在时拒绝覆盖，`--force` 可覆盖，
      验证：`uv run pytest tests/resolver/test_review_all.py -q` 全绿
- [x] 11.6 实现 `create_annotator_copy()` 与 `new-annotator` 子命令，
      验证：对 test 跑一次后副本为 20 条全 `proposed`
- [x] 11.7 端到端验证：主文件用 `--all` 被拒（退出码 2）、
      副本用 `--all` 可逐条重标 20 条、主文件的 37/19 条确认未被污染，
      验证：跑完后 `summary` 显示 dev 37/40、test 19/20
- [x] 11.8 更新 `docs/resolver.md`：说明为什么不能直接 `Copy-Item`、
      两种模式的区别、`--all` 的安全约束，
      验证：文档中的命令按原样可执行

## 12. 标注完成后的核查（第二标注者的真实数据）

> 起因：用户完成 60/60 主标注 + alice/bob 两份副本后要求核查。

- [x] 12.1 核查四份标注文件的状态：
      dev 40/40、test 20/20、alice 20/20、bob 20/20 全部 `confirmed`，
      且 `labeler` 分别是 xly / alice / bob，
      验证：`label --split dev summary` 与 `--file ... summary` 输出一致
- [x] 12.2 核查"人工是否改判提案"：60 条全部沿用提案标签（0 条改判），
      验证：与 `build_conflict_set.py` 的原始定义逐条比对
- [x] 12.3 发现 bob 在 `test-add-01/02/03` 上把 `existing_value=None`
      的场景标成 NOOP——按定义不成立（NOOP 表示与既有值完全相同）。
      κ 抓不到这类错误，因为 κ 只衡量两人是否一致，
      验证：新增的逻辑自洽检查报出这 3 条
- [x] 12.4 先写测试：`check_logical_consistency()` 覆盖两类硬错误——
      `existing_value` 为空却标四类之一、candidate 与 existing 相同却标 SUPERSEDE；
      并对全部四份标注文件断言自洽，
      验证：`uv run pytest tests/resolver/test_label_consistency.py -q` 全绿
- [x] 12.5 实现检查器，修正 bob 的 3 条为 ADD，
      验证：自洽检查对四份文件全部通过
- [x] 12.6 重算三对 κ：主 vs alice、主 vs bob、alice vs bob 均为 1.000，
      并把"同源复核 ≠ 独立双标注"的保留意见写进报告，
      验证：`test_report_states_the_independence_caveat` 通过
- [x] 12.7 在纯 `confirmed` 子集上重跑四组评测（dev/test × 全量/纯规则），
      验证：`run_conflict` 不再需要 `--allow-proposed`，退出码 0
- [x] 12.8 更新报告：标签状态改为 60/60、新增 κ 章节与解读、
      待办列表勾掉前两项、新增"逻辑自洽检查"小节，
      验证：`test_label_confirmation_progress_matches_report` 与
      `test_kappa_between_annotators` 均通过

## Workflow follow-up

- 标签人工确认后重跑并更新报告，再归档该变更。
