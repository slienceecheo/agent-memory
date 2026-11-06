# Tasks

> 三个 commit 的顺序不能换：①结构（零行为变化）→ ②填真 cosine → ③改权重数值 + 重测 + 报告。
> 每个 group 结束时跑全量：`uv run --no-sync pytest -q`。
>
> **实测基线（apply 开始时）**：`1755 passed, 4 skipped, 5 deselected`。
> 其中 **4 个 skip 是"含本次变更"的状态**：`tests/test_handoff.py` 有一条
> "存在进行中的变更，归档前不适用"因 `cosine-as-sort-feature` 未归档而 skip。
> **归档后会变成 3 skipped**——看到这个变化不是回归。
>
> **编号不连续是故意的**（`1.4b` / `2.6b` / `4.0a-c`）：
> 这些编号在跨轮讨论里被反复引用（`2.6b` 出现 5 次以上），
> 重排会让那些引用全部失效——而那些引用是"为什么加这一步"的唯一记录。
> `openspec` 按 checkbox 计数，不按编号。

## 0. 先复核规模（30 分钟，防止按错误清单动手）

- [x] 0.0 **拍改前快照**（必须在任何代码改动之前）：
  跑 `data/retrieval-v2/{sample,billing}` 的
  `evaluate(paths=("lexical","vector","adjacency"))`，把每条
  `case_id → (rank_after_fusion, rank_after_rerank, rerank_top1_tag, fusion_tags)`
  存到临时目录的 `snapshot_before.json`。
  验证：文件存在且 case 数 == **24**（`sample` 12 + `billing` 12，覆盖**全部** `has_gold`
  用例；不是 A 轴子集的 22）。**已实测跑过两次，两次 diff == 0**——
  所以快照本身可复现，能做门禁。若你重跑时两次不一致，先查 embedding 缓存命中，
  不要拿一个不可复现的快照当判据。

- [x] 0.1 用 AST 重算四个数并与 proposal 的 Impact 表逐项比对：
  `FeatureScores(...)` 构造点数（**17**：`evals` 2 + `tests` 15）、
  含 `"base"` 键的 `features` 字典数（**19**）、
  依赖字段名的 `assert` 数（**6**）、
  `weights_name="uniform"` 调用数（**48**）。
  验证：写一个临时脚本跑 `ast.walk`，把四个数打印出来。
  **这四个数已在 2026-11-06 实测确认**；若你重算得到不同结果，先改文档再改代码——
  否则这四行就是"没有断言守着的数字"。

- [x] 0.2 复核 3 处"要重测"的临时权重仍在原位，且总数 7 处：

  ```powershell
  Select-String -Path tests/retrieval/*.py -Pattern 'PREREGISTERED_WEIGHTS\["__' -Encoding utf8
  ```

  验证：命中 **7** 行，分别落在
  `test_fusion_dilution.py:68`（`__concl5`）、`test_lexical_provenance.py:128`（`__lexprov`）、
  `test_rerank_cannot_reorder.py:114/115`（`__base`/`__v3`）、`test_same_caliber.py:95`（`__cal`）、
  `test_v3_capability_boundary.py:79/80`（`__auth`/`__base`）。
  **已实测：该命令命中 7 行。**

  **⚠ 这 7 处全部是位置参数**：`RerankWeights(0.4, 0.3, 0.3)`。
  改字段后第三位会**静默移位**成 `cosine`——不报错、不改和、但语义变了。
  实测全仓库 `RerankWeights(...)` 的**位置参数构造只有这 7 处**（其余 20 处都是关键字），
  `FeatureScores(...)` 的位置参数构造 **0 处**。
  所以 audit 面很小，但必须显式处理（见 2.6b）。

- [x] 0.3 **写比对脚本，并先证明它能报出差异**（否则 2.11 就是第 1 种坏形态）：
  脚本读 `snapshot_before.json` 与 `snapshot_after.json`，逐 case 比四个字段
  （`rank_after_fusion` / `rank_after_rerank` / `rerank_top1_tag` / `fusion_tags`），
  打印四项差异数与总差异数；**键集不同也必须报出来**（不能静默跳过）。
  验证（**双向证伪，缺一不可，已实测通过**）：
  1. 用同一份文件比两次 → `diff_fusion=0 diff_rerank=0 diff_top1=0 diff_fusion_tags=0`；
  2. 手工把 after 里任一 case 的 `rank_after_rerank` 加 1 →
     **必须打印 `diff_rerank=1` 且退出码非 0**（实测 `billing:billing-a1: 2 -> 3`）。

  **为什么这一步不能省**：一个永远打印 0 的比对脚本，和
  `test_handoff_v3_method.py:1888` 是同一个形态——它会让 commit ① 的门禁静默失效，
  而全量测试仍然全绿。

## 1. commit ①-a：先写会失败的结构测试

> **本 group 只写 commit ① 的测试**。权重的数值与命名属于 commit ③
> （见 group 4 的 4.0a/4.0b）——因为改数值会改变排序，而 commit ① 的门禁是"名次逐条不变"。
> 两者的测试不能写在同一个 commit 里，否则必有一条永远红。

- [x] 1.1 写 `tests/retrieval/test_feature_set_cosine.py::test_feature_scores_has_cosine_not_status`：
  断言 `set(FeatureScores.__dataclass_fields__) == {"base", "condition", "authority", "cosine"}`
  且 `"status" not in fields`。验证：`uv run --no-sync pytest tests/retrieval/test_feature_set_cosine.py -q`，
  **预期红**，报错文本必须是 `AssertionError` 且列出实际字段名——若报的是 `ImportError`/`AttributeError`，
  说明测试本身写错，先修测试。

- [x] 1.2 写 `test_rerank_weights_has_cosine_not_status`：断言
  `set(RerankWeights.__dataclass_fields__) == {"base", "authority", "cosine"}`。
  验证：同上，预期红。

- [x] 1.3 写 `test_rerank_uses_three_features`：构造 3 条候选，`base`/`authority` 相同而 `cosine` 不同，
  断言 `rerank` 的顺序按 `cosine` 排。验证：预期红（当前 `FeatureScores` 没有 `cosine` 参数，
  会是 `TypeError`——**接受这个红，它证明测试确实在测新接口**）。

- [x] 1.4 写 `test_status_score_is_not_in_rerank`：读 `src/memory/retrieval/rerank.py` 里
  `def rerank(` 到下一个顶层 `def` 之间的文本，断言不含 `features.status` 与 `weights.status`。
  验证：预期红。

- [x] 1.4b 写 `test_rerank_weights_reject_positional_args`：
  `pytest.raises(TypeError)` 构造 `RerankWeights(0.4, 0.3, 0.3)`。
  同文件再写 `test_feature_scores_reject_positional_args`：
  `pytest.raises(TypeError)` 构造 `FeatureScores(0.5, 0.0, 1.0, 1.0)`。
  验证：预期红（当前两者都接受位置参数）。
  **已实测 kw_only 的报错形态**：`takes 1 positional argument but 4 were given`
  （`RerankWeights`）/ `but 5 were given`（`FeatureScores`）。
  所以断言可以写 `match="positional"`，且**能区分**"拒收位置参数"与"其他构造错误"。

- [x] 1.5 写 `test_defect18_numbers_match_weights`：从 `DEFECT18_WEIGHTS` 算
  `advantage = w.base * (1.000 - 0.910)`、`penalty = w.authority * (1.00 - 0.00)`，
  断言 `(advantage, penalty, penalty - advantage) == approx((0.0180, 0.2000, 0.1820), abs=1e-4)`。
  **`d_base = 1.000 - 0.910` 写死在测试里**（数据属性，不是权重属性）。
  验证：预期红（`ImportError: cannot import name 'DEFECT18_WEIGHTS'`）。

- [x] 1.6 写 `test_defect18_carrier_is_independent_of_preregistered`：**行为断言**——
  暂时把 `PREREGISTERED_WEIGHTS` 的每一项都替换成 `RerankWeights(1.0, 0.0, 0.0)`，
  重算 `DEFECT18_WEIGHTS` 的三项算术，断言仍是 `0.0180 / 0.2000 / 0.1820`，
  然后 `try/finally` 恢复原表。
  **不要写 `DEFECT18_WEIGHTS != PREREGISTERED_WEIGHTS["mixed"]`**：两者当前同值
  （`0.2/0.2/0.6`），那个断言在**正确实现上也会红**。
  验证：预期红（`ImportError: cannot import name 'DEFECT18_WEIGHTS'`）。

## 2. commit ①-b：改产品代码让 group 1 变绿

- [x] 2.1 `src/memory/retrieval/rerank.py`：`FeatureScores` 删 `status` 加 `cosine`；
  `RerankWeights` 同；**两个 dataclass 都加 `kw_only=True`**；
  `rerank()` 加权式改成 `weights.base*base + weights.authority*authority + weights.cosine*cosine`；
  `_validate` 的字段名列表改成 `("base", "condition", "authority", "cosine")`。
  验证：1.1/1.2/1.3/1.4/1.4b 转绿。
  **注意**：加 `kw_only=True` 后，7 处测试会立刻 `TypeError`——这是**预期**，
  由 2.6b 逐个修。不要为了让全量变绿而回退 `kw_only`。

- [x] 2.2 同文件：`RerankWeights` 换完字段后，`PREREGISTERED_WEIGHTS` 的**数值一字不改**，
  只把第三个位置从 `status` 换成 `cosine`：`uniform` 0.4/0.3/0.3、`base_heavy` 0.8/0.1/0.1、
  `auth_heavy` 0.2/0.7/0.1。
  **`status_only` 必须删掉，不能改成 `cosine=0.7`**：它的名字指向一个已不存在的特征，
  留着就是"名不副实的名字"——正是本次要禁止的形态。
  删它不影响测试：`test_report_consistency.py:58` 的 `"status_only"` 只是**文件名片段**
  （拼 `results/retrieval-independent-status_only-...json`），不查 `PREREGISTERED_WEIGHTS`。
  `disabled_weights()` 返回 `RerankWeights(base=1.0, authority=0.0, cosine=0.0)`。
  **新增 `DEFECT18_WEIGHTS = RerankWeights(0.2, 0.2, 0.6)`**（它可以现在就取终值——
  它不参与生产排序，只做缺陷算术）。
  验证：1.5/1.6 转绿；`uv run --no-sync pytest tests/retrieval/test_rerank.py tests/retrieval/test_report_consistency.py -q` 全绿。

  **为什么这里不改数值**：`uniform` 从 0.4/0.3/0.3 变成 0.2/0.2/0.6 会改变排序，
  而 2.11 的门禁要求"名次逐条不变"。两者不能同时成立。

- [x] 2.3 同文件 docstring：把 `status` 加进"已删除的两个特征"表（变成三个），
  并写明"前提：三条召回路径只返回 ACTIVE"。验证：`grep -c "status" src/memory/retrieval/rerank.py`
  输出的每一处都必须是"已删除"/"不再参与"，不能有活的加权引用。

  **验证命令要能判真假**：`Select-String -Path src/memory/retrieval/rerank.py -Pattern "status"`
  只允许命中 docstring 与 `_STATUS_SCORE`/`status_score`（后者保留作测量工具）。

- [x] 2.4 `evals/run_retrieval.py:763,772`：`features_by_tag` 与 `FeatureScores(...)` 都改成
  `base`/`authority`/`cosine`，其中 `cosine=0.0`（本 commit 先占位）。
  验证：`uv run --no-sync pytest tests/retrieval/test_per_case_features.py -q` ——
  **预期红**（它断言 `base/authority/status`），这个红在 2.5 里修。

- [x] 2.5 把 `tests/retrieval/test_per_case_features.py` 的键集合断言改成
  `{"base", "authority", "cosine"}`；`test_condition_is_not_inside_features` 追加断言
  `"status" not in features`。验证：该文件全绿。

- [x] 2.6 机械替换 **15 处测试** + **2 处 evals** 的 `FeatureScores(...)` 构造
  （`diagnose_c4_leak.py` 与 `run_retrieval.py` 已在 2.4 处理，这里只数测试的 15 处）：
  `status=X` → `cosine=0.0`（测试构造里若 `status` 是变量，改成 `cosine=0.0` 并加一行注释
  说明"历史 status 值恒为 1.0，不进排序"）。
  验证：`Select-String -Path tests/retrieval/*.py -Pattern 'status='`
  ——命中数必须只剩非 `FeatureScores` 用途（`status=Status.ACTIVE` 之类）。

- [x] 2.6b **修 7 处 TypeError**（`kw_only=True` 已由 2.1 加上，它们现在必然抛错）：
  逐个把 `RerankWeights(0.4, 0.3, 0.3)` 改成
  `RerankWeights(base=0.4, authority=0.3, cosine=0.0)`。
  另有 2 处是 `(1.0, 0.0, 0.0)`（`__base`）与 `(0.0, 1.0, 0.0)`（`__auth`），
  第三位本来就该是 0.0。

  **这一步不是审计，是编译器指路的机械修复**：7 处位置（已实测）
  `test_fusion_dilution.py:68`、`test_lexical_provenance.py:128`、
  `test_rerank_cannot_reorder.py:114/115`、`test_same_caliber.py:95`、
  `test_v3_capability_boundary.py:79/80`。
  新增一处位置参数会立刻 `TypeError: takes 1 positional argument but 4 were given`，
  **漏不掉**——这是 `kw_only=True` 与"人工审计 7 处"的本质区别。

  验证：`uv run --no-sync pytest tests/retrieval/ -q` 全绿；
  且 `Select-String -Path tests/retrieval/*.py -Pattern 'RerankWeights\(\d'` **0 命中**。

  **证伪**：随便新增一行 `RerankWeights(0.4, 0.3, 0.3)` 到一个测试里 → 该测试必须红
  （TypeError），而不是静默通过。**这个红证明结构性保护生效，不是要修的 bug。**

- [x] 2.7 机械替换 **19 处** `features` / `features_by_tag` 字典字面量：
  `"status": 1.0` → `"cosine": 0.0`。**两个例外**：
  - `test_per_case_features.py:278` 是故意缺键的负例，它缺的是 `authority`，断言 `match="authority"` 不变；
  - 5 处 `{"base": 1.0}` 单键的**签名探测**（`test_gate_apparatus_binding.py` 的 4 处、
    `test_v3_capability_boundary.py:86`）不含 `status`，不动。
  验证：`uv run --no-sync pytest tests/retrieval/test_rank_recompute.py tests/retrieval/test_rank_recompute_end_to_end.py tests/retrieval/test_v3_capability_boundary.py tests/retrieval/test_gate_apparatus_binding.py -q` 全绿。

- [x] 2.8 改 **6 处**字段名断言（proposal 的 Impact 表逐个点名）：
  `test_per_case_features.py:73`、`test_rerank.py:123`（随该测试删除而消失）、
  `test_rerank.py:186`、`test_handoff_v3.py:76`、
  `test_rerank_three_weights.py:32`、`test_rerank_three_weights.py:43`。
  `test_rerank_variance.py:104` 的 `observed == 4` **保持不变**
  （`FeatureScores` 仍是 4 字段：`base`/`condition`/`authority`/`cosine`）。
  验证：`uv run --no-sync pytest tests/retrieval/test_rerank.py tests/retrieval/test_rerank_variance.py tests/retrieval/test_rerank_three_weights.py tests/retrieval/test_handoff_v3.py -q` 全绿。

- [x] 2.9 把 2 处缺陷测试改读 `DEFECT18_WEIGHTS`：
  `test_defect18_authority.py:124`、`test_defects_20_21.py:117`。
  验证：`uv run --no-sync pytest tests/retrieval/test_defect18_authority.py tests/retrieval/test_defects_20_21.py -q` 全绿。

- [x] 2.10 更新 `test_handoff_v3_method.py::test_rerank_defect_tests_read_the_product_weights`：
  - `assert "PREREGISTERED_WEIGHTS" in src` → 改成断言引用 `DEFECT18_WEIGHTS`；
  - **删掉 `assert "w.condition" in p21`（第 1888 行），不要改成 AST 判据。**

  **为什么删而不是修**：它想守的"缺陷 21 的加成必须用 `w.condition`"在
  `condition` 退出加权后**已不是需要守的事实**——它守的是一条已废弃的规则。
  而它想守的东西已经被两处覆盖：
  - `test_defects_20_21.py:121` `assert not hasattr(w, "condition")` 守"字段不存在"；
  - `:132-134` 断言"改变 condition 不改变得分"，守"condition 不影响排序"。

  **已实测**：直接删掉第 1888 行，跑全量 `pytest tests/ -q` →
  **1755 passed, 4 skipped, 5 deselected**，无一红。
  所以它确实是冗余的，而且是"断言对象是 docstring"的永远绿形态。
  删后用 HANDOFF 记一句"它曾守一个不存在的字段"，比留一条更复杂的 AST 断言诚实。

  验证：该测试绿 + 全量绿。
  **证伪**：删之前先确认它当前是绿的（已确认）；删之后若红，说明我的判断错了，
  那时才需要重新引入判据。

- [x] 2.11a **快照比对（commit ① 的验收）**：跑 0.3 那个**已通过双向证伪**的比对脚本，
  比较 `snapshot_before.json` 与 commit ① 完成后新拍的 `snapshot_after.json`。
  验证：脚本打印 `diff_fusion=0 diff_rerank=0 diff_top1=0 diff_fusion_tags=0`。

  **为什么这条能成立**：改前 `0.3 × status(=1.0)` 是全池常数，改后 `0.3 × cosine(=0.0)`
  也是全池常数。加常数不改变任何一对候选的先后或并列结构。

- [x] 2.11b **四项中任何一项非 0 时的处置：回到 2.1 查为什么行为变了，
  MUST NOT 改快照、改门禁、或放宽阈值。**

  这条防的正是本项目反复出现的形态：**门禁红了之后去改门禁，而不是改实现**。
  具体的错误做法与正确做法：

  | 错误做法 | 为什么错 |
  |---|---|
  | 重拍 `snapshot_before.json`，再比一次 | 把"改前"改成"改后之后"，差异当然归零 |
  | 放宽成"差异 ≤ N" | 把"零行为变化"降级成"差不多没变" |
  | 改 `fusion_tags` 的比较方式（比如排序后比） | `fusion_tags` 的顺序本身就是被验的对象之一 |
  | 跳过 `rank_after_rerank`，只比融合 | 删 `status` 影响的正是重排，跳过它等于不验 |

  正确做法：先查 `tests/retrieval/test_effective_feature_count.py` 确认 `status`
  在池内确实恒为 1.0；若不是，那说明"删 status 零行为变化"这个前提本身不成立，
  应停下来重新评估变更，而不是继续。

## 3. commit ②：向量召回带出真 cosine

- [x] 3.1 写 `tests/retrieval/test_vector_scored.py::test_scored_variant_matches_plain_order`：
  同一个 store、同一个查询向量，`recall_by_vector_scored` 返回的 `item` 顺序 ==
  `recall_by_vector` 的顺序。验证：预期红（`ImportError`）。

- [x] 3.2 写 `test_scored_values_are_the_cosine`：手工算
  `dot / (norm × candidate_norm)`，断言与返回的分数逐位相等（`==`，不是 `approx`）。
  验证：预期红。

- [x] 3.3 `src/memory/retrieval/vector.py`：新增 `recall_by_vector_scored`（把现有循环的
  `scored` 列表直接返回 `(store.get(item_id), score)`）；`recall_by_vector` 改成
  `[item for item, _ in recall_by_vector_scored(...)]`。验证：3.1/3.2 转绿，且
  `uv run --no-sync pytest tests/retrieval/test_recall.py tests/retrieval/test_pipeline.py tests/retrieval/test_l6c_paths_return_data.py tests/retrieval/test_recall_active_only.py -q` 全绿。

- [x] 3.4 `evals/run_retrieval.py` 接线：`vector` 路径改用 `recall_by_vector_scored`，
  把 `tag → cosine` 存进一个 dict；构造 `FeatureScores` 时 `cosine=cos_by_tag.get(tag, 0.0)`；
  `features_by_tag[tag]["cosine"]` 同源。验证：
  `uv run --no-sync pytest tests/retrieval/test_per_case_features.py -q` 全绿。

- [x] 3.5 写 `test_features_cosine_equals_recall_score`：跑一次
  `evaluate(paths=("lexical","vector","adjacency"))`，**另起一次** `recall_by_vector_scored`
  调用取分数，逐 tag 比对 `features_by_tag[tag]["cosine"] == max(0.0, score)`
  （逐位相等）。验证：
  `uv run --no-sync pytest tests/retrieval/test_features_cosine_equals_recall_score.py -q` 绿。
  **证伪（必须双向）**：
  1. 把 `run_retrieval` 里的 `cosine=cos_by_tag.get(tag, 0.0)` 改回 `0.0`，这条必须红；
  2. 把比对式改成 `max(0.0, score) + 0.001`，这条也必须红（证明比对的是真值不是形状）。
  若两种改动都仍绿，说明比对是自比（恒真），重写。

- [x] 3.6 写 `test_cosine_feature_is_truncated_to_unit_interval`：`raw = -0.3` 与 `raw = -0.9`
  都映射到 `0.0`；`raw = 0.5` 映射到 `0.5`（不是 `0.75`）。验证：预期红。

- [x] 3.7 在 `run_retrieval.py` 里实现截断 `max(0.0, raw_cos)`。
  验证：3.6 转绿。

- [x] 3.8 写 `test_cosine_gap_and_band_are_written`：断言每条已召回 gold 的 case 都含
  `cosine_gap`（float，可负）与 `cosine_band`（`stable`/`noise`/`negative` 三值之一）。
  验证：预期红（缺键）。

- [x] 3.9 实现 `cosine_gap = gold_cos - max(其余候选的 cos)` 与三态映射（阈值 0.01），
  写进 `per_case`。验证：3.8 转绿。

- [x] 3.10 写 `test_cosine_band_three_states_are_all_used`：在 v2 两个 subject 上，
  `stable` 与 `negative` 必须都出现，`noise` 可以为 0（实测就是 0）。
  **必须有断言证明"0 不是漏算"**：断言 `positive_gaps_and_negative_count == n`。
  验证：绿。

- [x] 3.11 更新 `test_per_case_features.py::test_per_case_key_count_is_30` →
  `..._is_32`：`+cosine_gap` 与 `+cosine_band` 两项。验证：绿。

- [x] 3.12 全量跑一次：`uv run --no-sync pytest -q`。预期全绿。
  **若 `test_cosine_band.py` 的 5700 次扰动变红**，先确认 embedding 缓存命中
  （`max|diff|` 应为 0），不要调阈值。

## 4. commit ③：权重数值、重测与报告双套数字

- [ ] 4.0a 写 `tests/retrieval/test_preregistered_naming.py::test_preregistered_names_describe_questions`：
  断言名字集合恰好是 `{"uniform", "mixed", "cosine_only"}`。
  验证：`uv run --no-sync pytest tests/retrieval/test_preregistered_naming.py -q`，预期红。

- [ ] 4.0b 写同文件 `test_default_weights_are_the_preregistered_values`：断言
  `PREREGISTERED_WEIGHTS["uniform"]` 的三元组 == `(0.2, 0.2, 0.6)`。
  验证：同上，预期红。

- [ ] 4.0c 改 `PREREGISTERED_WEIGHTS` 为终值：`_DEFAULT = RerankWeights(0.2, 0.2, 0.6)`，
  喂给 `uniform` 与 `mixed` 两个键；`cosine_only = RerankWeights(0.0, 0.0, 1.0)`。
  删 `base_heavy` / `auth_heavy` / `status_only`。
  验证：4.0a/4.0b 转绿；`test_preregistered_weights_exist_and_sum_to_one` 与
  `test_preregistered_count_is_five` 仍绿（后者断言 `len <= 5`，3 组通过）。

- [ ] 4.1 `tests/retrieval/test_fusion_dilution.py:68`：把 `__concl5` 换成新装置
  `RerankWeights(0.2, 0.2, 0.6)`（即 `cosine_only` 或 `mixed`，二选一并写进 docstring）。
  验证：`uv run --no-sync pytest tests/retrieval/test_fusion_dilution.py -q`，**预期红**
  （`EXPECTED` 的 `triple_hit` 与 `n` 会变）。

- [ ] 4.2 把实测的新数字填进 `test_fusion_dilution.py` 的 `EXPECTED`，并**保留旧数字**为
  `EXPECTED_V3_THREE_FEATURES`，加一条断言"两套的 `paired n` 相同"（同池才可比）。
  验证：该文件全绿。

- [ ] 4.3 同法处理 `tests/retrieval/test_same_caliber.py:95` 的 `__cal`，
  保留旧的 `+0.2167 / −0.0278` 作历史。验证：该文件全绿。

- [ ] 4.4 `tests/retrieval/test_rerank_cannot_reorder.py`：删掉 `__v3`，按 design D6
  改成从产物内联复现三项装置公式（`0.4*base + 0.3*authority + 0.3*1.0`），
  并在测试开头断言"池内 `status_score` 全为 1.0"这个前提。
  验证：`test_rerank_never_improves_top1` 绿，且 `billing` 仍是 1/12。
  **证伪**：把前提断言里的 `1.0` 改成 `0.5`，测试必须红（否则前提没被真的检查）。

- [ ] 4.5 报告 `docs/reports/v2-what-it-measures.md`：§6.5.1 与 §6.5.2 的表头加
  `装置：uniform-v3-three-features（0.4/0.3/0.3）`。验证：`grep -n "uniform-v3-three-features"`
  至少命中 2 处（两张表各一）。

- [ ] 4.6 同报告新增 `### 6.14 结论 5b`：表头写 `装置：uniform-v3-cosine（0.2/0.2/0.6）`，
  数字栏填"上界估计（手工重排，未经 `run_retrieval`）"，并给出实测后要替换的占位标记。
  验证：`grep -n "6.14"` 命中；该节内含"上界估计"四字。

- [ ] 4.7 写 `test_report_numbers_carry_apparatus_label`：解析 §6.5.1 的表头行，
  断言含 `uniform-v3-three-features`；解析 §6.14 表头，断言含 `uniform-v3-cosine`；
  断言两个标签**不相等**（比较单元格值，不比"关键词是否出现"）。
  验证：绿。**证伪**：把 §6.14 表头改成与 §6.5.1 相同，必须红。

- [ ] 4.8 `docs/HANDOFF.md`：更新装置描述（"排序特征 = 3（base / authority / cosine）"），
  以及 §0.8 里 `uniform.status = 0.25` 的前提表——加一行"该前提属于三项装置，已失效"。
  验证：`uv run --no-sync pytest tests/retrieval/test_handoff_v3_method.py -q`。
  **注意**：`test_section_0_8_records_the_joint_infimum_is_zero` 断言
  `"w_status=1.00 -> 0" in section`——那句是历史算术，**不要改它**，只在同一节加"已失效"标记。

- [ ] 4.9 全量跑一次：`uv run --no-sync pytest -q`。预期全绿，`results/*.json` 顶层仍 48 个
  （`uv run --no-sync python evals/tools/recount_specs.py` 不涉及，但
  `tests/retrieval/test_result_partitions.py` 会查目录）。

- [ ] 4.10 跑 `openspec validate cosine-as-sort-feature --strict`，必须输出
  `Change 'cosine-as-sort-feature' is valid`。

## Workflow follow-up

- 归档前贴出 `openspec validate cosine-as-sort-feature --strict` 与
  `uv run --no-sync pytest -q` 的原始输出。
- 归档后检查 git status，回填 HANDOFF §0.6/§0.7 统计与日期，再单独 commit。
- 确认 `results/*.json` 顶层仍为 48（本次不新增结果文件）。
