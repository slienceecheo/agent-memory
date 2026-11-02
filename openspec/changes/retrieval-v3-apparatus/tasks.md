# Tasks

## 1. 三特征重排（TDD）

- [x] 1.1 写失败测试：`RerankWeights` 只有三个权重（无 `condition`）；构造 `RerankWeights(base=0.4, authority=0.3, status=0.3)` 应成功，且 `rerank()` 的得分与 `0.4*base + 0.3*authority + 0.3*status` 逐条相等
  - 验证：`uv run --no-sync pytest tests/retrieval/ -k rerank -q` 先红
  - **完成**：`tests/retrieval/test_rerank_three_weights.py` 7 条
- [x] 1.2 实现：删除 `RerankWeights.condition`，`rerank()` 只用三项加权；**`FeatureScores` 保留四字段不动**
  - 验证：1.1 的测试转绿；`FeatureScores.__dataclass_fields__` 仍是四个
  - **已核实**：`RerankWeights` 字段 = `[base, authority, status]`；
    `FeatureScores` = `[base, condition, authority, status]`
- [x] 1.2b **把依赖四特征加权的旧测试改正向断言**

  1.2 之后会有一批旧测试变红——**它们红的原因是"产品按规格变了"，不是"产品错了"**。
  正确动作是改断言，错误动作是把 `condition` 权重改回去。

  要改的断言（按旧行为写的）：

  | 文件 | 旧断言 | 改为 |
  |---|---|---|
  | `test_rerank.py` | `total == 0.25*b + 0.25*c + 0.25*a + 0.25*s` | `total == w.base*b + w.authority*a + w.status*s` |
  | `test_rerank.py` | `RerankWeights.__dataclass_fields__` 含 4 个 | 含 **3** 个，且 `"condition" not in fields` |
  | `test_rerank_variance.py` | 依赖四特征有效数 ≥3 | 改为三特征，且断言 `condition` 不参与 |

  **在改之前先跑一次，记录哪些测试因"产品变更"而红，把清单写进提交信息**——
  这样"红"有归属，不会被误读成"实现错了"。
  - 验证：`uv run --no-sync pytest tests/retrieval/test_rerank.py tests/retrieval/test_rerank_variance.py -q` 全绿
  - **完成**：19 条红全部归类处理（A 改断言 13 / B 版本条件 3 / C 阈值 2 /
    D 自愈 1 / E 加豁免 1）
- [x] 1.3 写测试：`condition` 不参与得分，但 `FeatureScores.condition` 仍可读取

  **断言必须比 `score`，不能比 `Ranked` 对象**——`Ranked` 的 `frozen=True` dataclass
  相等性包含 `features`，而两条候选的 `features.condition` 不同：

  ```python
  a = FeatureScores(base=0.5, condition=0.0, authority=1.0, status=1.0)
  b = FeatureScores(base=0.5, condition=1.0, authority=1.0, status=1.0)
  w = RerankWeights(base=0.4, authority=0.3, status=0.3)

  # 错：Ranked 的相等性含 features，这会红——而红的原因是测试写错
  # assert rerank([a], w) == rerank([b], w)

  # 对：只比 score
  assert rerank([a], w)[0].score == rerank([b], w)[0].score

  # 且 condition 仍可读
  assert rerank([a], w)[0].features.condition == 0.0
  assert rerank([b], w)[0].features.condition == 1.0
  ```

  - 验证：`pytest -k condition_not_in_score` 通过
- [x] 1.4 更新 `PREREGISTERED_WEIGHTS` 为三字段，且每组的和仍为 1
  - 验证：`pytest tests/retrieval/test_rerank.py -q` 通过；`test_preregistered_weights_exist_and_sum_to_one` 覆盖
  - **已核实**：四组 `uniform / base_heavy / auth_heavy / status_only`，
    `cond_heavy` 已移除（它不再有可加权的对象）

## 2. 轴由池结构派生

- [x] 2.1 写测试：给定池与 gold，`derive_axis(pool, gold)` 在"池中有同 relation 候选"时返回 `relation_within`，否则 `relation_cross`
  - 验证：`pytest -k derive_axis` 先红
  - **完成**：`tests/retrieval/test_derive_axis.py::test_derive_axis_*` 4 条
- [x] 2.2 实现 `derive_axis`
  - 验证：2.1 转绿
  - **完成**：抽 `count_competitors` 作为单一实现，`derive_axis` 只判 `> 0`
- [x] 2.3 写测试（三组断言，缺一不可）：

  **(a) 记录事实**——v2 的两个 subject 按 D2 判定：

  ```python
  assert derive_axis_policy({"A": [2] * 9, "C": []}) == "single_axis"   # billing：无 cross 查询
  assert derive_axis_policy({"A": [3,3,3,3,2,2,2,2,2,2], "C": [0, 0]}) == "two_axes"  # ledger
  ```

  > **`billing` 的 C 轴不是 `[2,2,2]`，是空**：那 3 条 C 标注在池结构上
  > 都是 `relation_within`（每条都有 2 个同 relation 对手）。
  > 若按**标注**分组会得 `merged`（A={2}、C={2}），
  > 而按**派生**分组得 `single_axis`——**两者报告轴数都是 1**。

  **(b) 反例：形状同 ledger 但用假数据**——防"按 subject 名字特判"：

  ```python
  fake = {"A": [2, 2, 2], "C": [0, 0, 0]}
  assert derive_axis_policy(fake) == "two_axes"
  ```

  **(c) 反例：只有 set 能判对的三类**（各对应一种失效判据）：

  ```python
  # 样本量不同、结构相同 -> merged（有序列表会错判 two_axes）
  assert derive_axis_policy({"A": [2] * 9, "C": [2] * 3}) == "merged"
  # 深度不同、标签都是 within -> two_axes（标签集合会错判 merged）
  assert derive_axis_policy({"A": [1, 1, 1], "C": [7, 7, 7]}) == "two_axes"
  # 尾部不同、中位数相同 -> two_axes（中位数会错判 merged）
  assert derive_axis_policy({"A": [1, 1, 1, 1, 9], "C": [1, 1, 1, 1, 1]}) == "two_axes"
  # 空轴 -> single_axis / no_axis（set([])==set([]) 会错判 merged）
  assert derive_axis_policy({"A": [2, 2], "C": []}) == "single_axis"
  assert derive_axis_policy({"A": [], "C": []}) == "no_axis"
  ```

  验证：全部通过。**四种判据的实测失效数**（见 design D2 的表）：

  | 判据 | 失效处数 |
  |---|---|
  | 中位数 | 1（尾部） |
  | 有序列表 | 2（样本量 ×2） |
  | 标签集合 | 2（深度 ×2） |
  | **取值集合 `set`** | **0** |
- [x] **2.4a** `per_case` 记 `n_competitors` 与逐条派生 `axis`（不触及结果目录）
  - 每条 case 的 `n_competitors` = 池中与 gold 同 `relation` 的候选数（不含 gold）
  - 逐条 `axis` = `derive_axis(pool=..., gold=...)` 的结果
  - 验证：`pytest -k per_case_has_axis` 通过
  - **完成**：新增 `count_competitors`（`derive_axis` 与结果字段共用一份实现），
    `tests/retrieval/test_per_case_axis.py` 9 条（含用 `pool_tag_meta` 复算、
    3/12 标注错误、0/12 一致、防常量 `n = pool_size - 1`）

- [x] **2.4b** subject 级 `axis_policy`，判据 = **`set(n_competitors)` 相等**（不是中位数）
  - 调 `derive_axis_policy(subject_cases)`，值域 **四值**：
    `merged` / `two_axes` / `single_axis` / `no_axis`（空轴防护见 design D2）
  - **`single_axis` 与 `merged` 必须分开**：报告轴数都是 1，但前者是"只有一轴"，
    后者是"两轴同构"。用同一个值会让报告写出"两轴合并"而实际只有一轴
  - 验证：`pytest -k derive_axis_policy` 通过（含空轴与三值互异用例）
  - **完成**：新增 `axis_policy_from_per_case`，`evaluate` 输出 `axis_policy` +
    `axis_policy_evidence`（两轴 `n` 与取值集合，供复算）。
    `tests/retrieval/test_axis_policy.py` 5 条；**实测 `billing` = `single_axis`，
    不是 `merged`**（3 条 C 标注实为 within，不存在 cross 轴）

- [x] **2.4c** 在报告中报 `axis_policy`，并写明 F21a 约束下的数据形状
  - 每个 subject 必报 policy；`merged` 只报一个轴的分数；`single_axis` 说明另一轴不存在
  - 写明：cross 轴需要"池中只有 gold 一条"的 relation，而 relation 总数仍须 ≤ 3（F21a）
  - **写成"改造既有 relation 为单值"，不写"新增 relation"**（新增会让 F21a 由绿变红）
  - 验证：报告中每个 subject 都有 policy 字段（测试读回文档比对）
  - **完成**：`docs/HANDOFF.md` 新增「v3 的轴判定与 F21a 约束」小标题（**不编号**：该文件有"§号必须从 1 开始"的守卫，`0.0` 会红）+
    §0 状态块的 v3 三行。`tests/retrieval/test_handoff_v3.py` 6 条**读回文档**比对：
    排序特征 3 个、`billing` = `single_axis`、`ledger` = `two_axes`、
    标注不一致 3/12 与 0/12、F21a 冲突的两种处置方向、v3 产物目录与顶层 48。
    **实测**：把文档里的 `single_axis` 改成 `merged` -> 立刻红；恢复后绿。

## 3. `per_case` 存三特征 + condition_score

- [x] 3.1 写测试：评测结果的每条 case 都有 `features` 子字典且**恰好三个键**（`base`/`authority`/`status`），另含 `condition_score` 字段
  - 验证：`pytest -k features_recorded` 先红
  - **完成**：`tests/retrieval/test_per_case_features.py`。
    **实测暴露一处设计缺口**：gold 未被召回时 `features` 是 `{}`，
    而"恰好三键"无法表达"不存在"——改为 **`None`**，
    并与 `features_by_tag` 里没有 gold tag 构成同一事实的两种表达。
- [x] 3.2 实现：`evaluate_case` 把 `FeatureScores` 的三项写入 `features`，`condition` 单独写入 `condition_score`（查询侧无条件时为 `null`）
  - 验证：3.1 转绿
  - **完成**：另存 `features_by_tag`（**整池**每条候选的三项特征）与 `fusion_tags`。
    **名次复算需要三个输入，不是一个**：`features_by_tag`（每条的 score）+
    `fusion_tags`（并列次序）+ 同一组 weights。
    缺第二条的后果：`rerank` 内部按 tag 字典序破并列，
    `d-<case>-0` 恒排在 `gold-<case>` 之前（`"d" < "g"`）——**一个固定偏向，看起来像排序结果**。
- [x] 3.3 写测试：复算的三个输入必须自洽，且构造并列证明融合顺序不可省
  - 验证：`pytest tests/retrieval/test_rank_recompute.py -q` 通过
  - **完成**：`test_rank_recompute.py` 6 条 + `test_rank_recompute_end_to_end.py` 6 条。
    构造测试证明"规则对"，真实数据测试证明"数据记全了"，**两条缺一不可**。
    **另加三条你未提但同样必要的守卫**：
    (a) `features` 与 `features_by_tag[gold]` 必须相等（两个来源同一事实）；
    (b) gold 未召回时两侧同时表达（`features is None` ⇔ gold tag 不在池里）；
    (c) `set(features_by_tag) == set(rerank_order_tags)`（键集合 == 进入重排的候选）。
    (c) 现在恒真（去重从不合并），**这正是写下来的理由**：
    它让"将来去重开始合并"这件事立刻可见，而不是让名次悄悄偏移。
- [x] 3.4 写测试：`per_case` 顶层键数从 **25 变成 30**。

  **前提限定**：25 指的是 **v2 最新批**（`47e4785-dirty` 的 11 份，25 键）。
  v2 还有 20/13/10/8/7/6 键的旧批，**它们不在本条的比对范围内**。
  所以判据是"v3 新产物 vs v2 最新批"，不是"v3 vs v2 全部"。

  **算术依据：25 + 5 = 30**：

  ```
  25（v2 最新批）
  +features          1   三项排序特征（嵌套三键，算一个顶层键）；gold 未召回时为 null
  +features_by_tag   1   整池每条候选的三项特征；复算名次必需
  +condition_score   1   null=查询侧无条件，0.0=有条件但不匹配
  +n_competitors     1   轴的定义量（池内同 relation 候选数）
  +axis              1   逐条派生轴（二元）
  = 30
  ```

  **原计划的 27 是错的**：它只算了本条变更的 2 个键，
  漏掉了 2.4a/2.4b 的 2 个，也漏掉了 `features_by_tag`。
  而 `features_by_tag` 不能省——少它则验收 1 退化成"只验分数、不验名次"。

  **若实现把三个子键平铺成顶层键**（即 `{"base":..., "authority":..., "status":...}`），
  键数会多 3 少 1，测试红——**而红的原因不是"30 写错了"，
  是"结构错成了平铺"**。

  验证：测试红时，先检查 `per_case[0]` 里是否存在 `features` 这个键，
  确认结构再改数字。断言消息必须写明这一点：

  ```python
  assert len(keys) == 30, (
      f"per_case 键数 {len(keys)} != 30。"
      "25 + 5 = 30（+features 嵌套三键算一个 +features_by_tag "
      "+condition_score +n_competitors +axis）。"
      "若多出 base/authority/status，说明 features 被平铺了——先修结构，不要改这个数字。"
  )
  ```
  - 验证：`pytest tests/retrieval/test_result_shapes.py -q` 仍通过（v2 未动）

## 3b. v3 产物放置与检查分区

**实测**：`tests/` 里有 **4 个测试文件、19 处** `RESULTS.glob("*.json")`：

| 文件 | 处数 | 意图 |
|---|---|---|
| `test_result_shapes.py` | 5 | **v2 档案**（9 类 / 48） |
| `test_result_shapes_two_criteria.py` | 3 | **v2 档案**（两套判据都只看归档） |
| `test_per_case_crosstab.py` | 7 | **v2 档案**（交叉表是 v2 的事实） |
| `test_unified_fingerprint.py` | 4 | **v2 档案**（15 份共享指纹） |

**关键事实：`glob` 现在只扫顶层，而这恰好是 v2 档案需要的行为。**
所以"不改"是安全的；**"改成 `rglob`"才会让这 19 处开始看到 v3 产物，从而让 48 / 9 类断言变红。**

而那时人会去改 `48` —— **而实际是扫描范围变了，断言没跟着分区。**
这与 v2 那次"11 份结果混三次代码状态"同型。

所以 3b.2 拆成方向相反的两条：

- [x] **3b.2a（不改 rglob 的那 4 个文件）**：显式声明"只统计顶层"
  给每个 `RESULTS.glob("*.json")` 的调用点加一道断言或注释，说明它**有意**只看顶层：

  ```python
  # 只统计 v2 归档（顶层）。v3 产物在 results/v3/，不计入本档案。
  files = sorted(p for p in RESULTS.glob("*.json") if p.parent == RESULTS)
  ```

  `p.parent == RESULTS` 是**冗余的**（`glob` 本来就不会递归），
  但它把"只看顶层"从"碰巧用 glob"变成**声明的行为**——
  将来有人改成 `rglob` 时，这道断言会提醒他先想清楚。

  验证：`pytest tests/retrieval/test_result_shapes.py tests/retrieval/test_result_shapes_two_criteria.py tests/retrieval/test_per_case_crosstab.py tests/retrieval/test_unified_fingerprint.py -q` 全绿，且 v2 的 48 / 9 类断言不变

  **完成**：实际形态与预估不同——`sorted(...)` 只有 1 处，
  另有 3 处是 `{p.name for p in RESULTS.glob(...)}`。脚本按三种形态分别计数、
  合计不符则整体不写，最终 **19 处**全改（5 + 3 + 7 + 4）。59 条测试全绿。
  另在 `test_result_shapes.py` 模块 docstring 写明了"改 `rglob` 会让 48 变红、
  该做的是分区而不是改 48"。

- [x] **3b.2b（唯一该用 rglob 的那一个）**：`test_every_result_file_is_classified`

  它的意图是"**所有**结果文件都被登记"，所以它该看到 v3。
  但它必须**按 `parent` 分区断言**，而不是把 v3 混进 v2 的计数：

  ```python
  for p in RESULTS.rglob("*.json"):
      zone = p.parent.relative_to(RESULTS).as_posix() if p.parent != RESULTS else "."
      assert zone in {"", "v3", "archive", "features"}, f"未登记的分区：{zone}"
  ```

  验证：`pytest -k every_result_file_is_classified` 通过

  **完成**：新建 `tests/retrieval/test_results_zones.py`（5 条）。
  实测 `results/archive/` **已经存在**（1 个 json），所以"子目录不检查"
  不是将来的风险，是**当下就存在**的实例。
  **另加 `test_zone_check_actually_fires`（tmp_path）**：
  分区检查抽成纯函数 `_unclassified(files, root, zones)`，
  用 `tmp_path` 造 `v3/` `archive/` `unknown/` 三个文件，
  确认"unknown 报错、登记后全绿"。**这不是"造违例再删"，是用临时目录做 fixture**
  （同 v2 的 `test_unbacked_detector_actually_fires`）。
  理由：没有它，"没人放错文件"与"检查从不生效"在 CI 输出里一样。

- [x] 3b.3 写测试：`test_unified_fingerprint` 的 v2 组仍是 15 份共享 `47e4785-dirty / 36e9c165`，且断言**不含** `results/v3/` 下的文件
  - 验证：`pytest tests/retrieval/test_unified_fingerprint.py -q` 通过
  - **完成**：`tests/retrieval/test_v3_fingerprint_zone.py` 两条。
    **实测纠正**：`36e9c165` 是 8 位**前缀**，文件里是 64 位完整哈希——
    直接比较会永远红，而那会诱使人去改文档里的历史数字。改用前缀匹配 +
    "15 份必须同一个完整哈希"（防 v2 早期"混三次代码状态"）。
- [x] 3b.4 写测试：`results/v3/` 下的文件必须带指纹，且指纹组与 v2 的 15 份**不同**（不同装置 → 不同指纹是预期）
  - 验证：`pytest -k v3_has_own_fingerprint` 通过
  - **完成**：v3 目录为空时 `pytest.skip` 并写明"本条此刻是空转，
    不代表 v3 指纹已验证"，**不用"0 个文件全部满足"假装通过**。
  - **另加 `test_v3_fingerprint_check_actually_fires`（tmp_path）**：
    指纹检查抽成纯函数 `_check_v3_files_are_distinct_from_v2(files)`（目录由调用方给），
    用 `tmp_path` 喂三种输入：合法 / 无指纹 / **带 v2 指纹**，逐个确认给出对应错误。
    **没有它，`results/v3/` 为空时上面那条是"永久 skip"**——
    而"永久 skip"与"检查通过"在 CI 输出里几乎一样（同 `paths_unwired = []`）。
    独立验证（不经 pytest）实测：1 / 0 / 1 三条错误路径均触发。

- [x] **3b.5 分区清单穷尽**（含尚未存在的 `features/`）

  ```python
  ALLOWED_ZONES = {"", "v3", "archive", "features"}

  for p in RESULTS.rglob("*.json"):
      zone = "" if p.parent == RESULTS else p.parent.relative_to(RESULTS).as_posix()
      assert zone in ALLOWED_ZONES, f"{p} 位于未登记的分区 {zone!r}"
  ```

  **必须写明的一句话**：

  > `results/features/` 目前**不存在**，所以这条断言对它是空转。
  > 分区清单已预留该目录，但"预留"不等于"已覆盖"——
  > 该目录出现时，必须同时定义它的检查（指纹 + 与主文件同源）。

  **不加这句，这条检查就是"绿得没有信息"**（同 `paths_unwired = []`、`tie_count = 1`）。

  验证：在 `results/v3/` 放一个无指纹文件 -> 测试红；删掉后绿。
  在 `results/unknown/` 放文件 -> 测试红（未登记分区）。

  **完成**：`test_results_zones.py` 的 `ZONES` 是**字典**（分区 -> 由谁检查），
  而不是集合——集合只能表达"存在"，字典还能表达"**谁在检查它**"。
  另加 `test_zone_manifest_covers_known_directories`：目录存在但为空时也红
  （比"有 json 才红"更早一步）。
  **实证**：放 `results/unknown/probe.json` -> 2 条红；放 `results/v3/probe.json` -> 1 条红；清理后全绿。

  > **后续更正（见 3c.3）**：本条完成时把 `archive` 写成"当前无检查"，
  > 那是**当时的事实**。3c.3 查清它有指纹（`8b1b600-dirty`）后，
  > 该措辞已改为"有指纹，且不得并入当前批"。
  > **"无检查"可以是一个事实，但它不该成为归档后的状态。**

## 3c. 分区的规格化（spec 缺口补齐）

**为什么单列一节**：3b 的五条任务把分区规则**只写进了测试与 proposal 的决议节**，
而 `openspec/specs/` 是唯一权威。归档后读 spec 的人会看到"排序特征集 / 轴派生 /
特征分持久化 / 离线复算"，**而看不到分区**——于是他会认为 `results/` 是扁平的，
而扁平假设正是"子目录不检查"的入口。

**这是 F21a 的反向形态**：F21a 是"规则写进协议、没写进门禁"（规则成了建议），
这次是"门禁存在、规则没写进文档"（约束成了实现细节）。**两个方向都会失效。**

- [x] 3c.1 在 `evaluation-harness` 的 delta 里新增 `Requirement: 结果产物的分区`
  - **删掉原拟的"分区 MUST 互斥"**：文件系统保证一个文件只能在一个目录里，
    所以"互斥"没有可被违反的形式，是恒真约束。改为断言**清单与磁盘的两个方向**
  - 验证：`openspec validate --strict` 通过
  - **完成**：五条 scenario——v2 只统计顶层 / v3 独立指纹 /
    历史对照物不得并入当前批 / 未知分区必须拒绝 / 空转必须可见

- [x] 3c.2 写测试：清单**不能是愿望清单**（反向方向）
  - 登记了分区却没建，且没标"尚无产物/预留" -> 必须失败
  - 验证：`pytest -k non_reserved_zones_exist`
  - **完成**：`tests/retrieval/test_results_partition.py`。
    **实测抓出一处不实**：`v3` 在清单里写成正常分区，但它现在不存在。
    已把分区状态分成**三种**（正常 / **尚无产物** / 预留尚不存在），
    三者混同会让清单变成愿望清单而"清单覆盖磁盘"那条仍然全绿。

- [x] 3c.3 写测试：`archive/` 的指纹规则
  - 必须有指纹，且**不得**与当前批相同（实测 `8b1b600-dirty` vs `47e4785-dirty`）
  - 且不得被登记进 `CURRENT` / `HISTORICAL`
  - 验证：`pytest -k archive_fingerprint_rule`
  - **完成**：这条替代了先前"archive 当前无检查"的说法——
    **"无检查"是一个事实，把它写成"有检查"才是撒谎**；而它确实有规则可写。

- [x] 3c.4 写测试：**"空转时有独立证明"这件事本身必须被断言**
  - 若 `*_actually_fires` 被删掉，主校验的 skip 就重新变成"永久 skip"
  - 而两者在 CI 输出上完全一样（都是 `s`）
  - 验证：`pytest -k skip_has_an_independent_proof`
  - **完成**：断言两个 `*_actually_fires` 函数存在，且都用 `tmp_path`

- [x] 3c.5 写测试：**有文件时 MUST NOT skip**（skip 条件的宽度，不是消息的内容）
  - 判据必须是"分区非空 -> 动作是 `run` 或 `fail`"，不是"skip 消息够清楚"
  - 并且跳过条件 MUST 依赖**传入的目录**，MUST NOT 依赖全局常量指向的真实目录
  - 验证：`pytest -k "nonempty and never_skip"`
  - **完成**：把调度抽成 `_run_v3_fingerprint_check(root) -> (动作, 错误)`，
    三态 `skip` / `run` / `fail`。`_v3_files(root)` 改为接收根目录参数。
    **`test_results_zones.py` 也加了同型的 `test_nonempty_zone_never_skips`。**
    **证伪过**：把 `_v3_files` 改成忽略参数、恒读真实目录，
    缺陷版在 `tmp_path` 上返回 `skip`（因为真实 v3 为空），正确版返回 `run`——
    **新断言能区分这两种状态，不是空转。**

> **为什么这条要单独存在**：`skip` 与 `pass` 在 CI 里几乎一样。
> "检查没跑"有三种原因：数据不存在（合理）/ 路径写错（缺陷）/
> **条件写宽**（缺陷，且最隐蔽——传临时目录时正常，只在生产路径上不跑）。

**实证（三条都跑过）**：

| 动作 | 结果 |
|---|---|
| `ZONES` 里加一个 `ghost`（不存在的非预留分区） | 报错，指出 `ghost` |
| 建出 `results/features/`（标为预留） | 报错，指出说明已过期 |
| 恢复 | 全绿 |

## 3d. 归档前核实抓出的六处不一致

**来源**：归档前逐条核对代码与文档，发现六处"代码与文档不一致"。
其中两处是"两个都显示通过、结论却互相矛盾"——**最危险的一类**。

- [x] 3d.1 `rerank.py` 模块 docstring 仍是"四特征"
  - 改为三特征，并把 `condition` 明确标为"审计字段，不参与加权"
  - 补了"为什么退出加权"的理由（消融的 0.600 混着上游问题）
  - **原状态**：同一文件里 docstring 说四项加权、`RerankWeights` 只有三个字段

- [x] 3d.2 `docs/retrieval.md` §四特征重排 + `HANDOFF:2608` 索引词
  - 同名小节改为"三特征重排"，`w_cond` 从那行算式里移除
  - **同时修正了一处旧错**：原文写"全部特征关闭时退化为 base 排序"，
    而那个状态**不可构造**（权重和必须为 1）。改为"只开 base"与"全零被拒绝"两件事
  - HANDOFF 索引词 `四特征` -> `三特征`

- [x] 3d.3 delta 的"全部特征关闭"场景无法构造
  - 改为「全零权重被拒绝」+ 写明 `disabled_weights()` 的语义是"只开融合分"
  - 测试 `test_all_off_falls_back_to_base` **改名**为
    `test_base_only_falls_back_to_fusion_order`（原名与断言内容不符）
  - 新增 `test_all_zero_weights_are_rejected`
  - **这是 v2 就有的缺陷**：本次 MODIFIED 本可顺手修掉，只把"四"改成"三"
    会把它留在正式 spec 里

- [x] 3d.4 design 的"本变更不调权重，只减特征"**是错的**
  - 实测四组权重全部重排，且**没有一组**是"去 condition 后重新归一化"
  - design 新增专节：**v2/v3 差异不可只归因于 condition**
  - 写明：要得到"condition 的贡献"必须另做只改特征集的消融（后续变更）

- [x] 3d.5 **F20 在 v3 下判据已不存在，但报告仍显示 passed**
  - **不改 `Check` 结构**（那要加"不适用"态、改 `run_all`、改 5+ 条测试，
    超出本变更范围）
  - 改为登记**适用域**，且**扩成 6 条**（不是 1 条）：
    `L6b / L8 / L6c` 读 `899e2b6-dirty`；`F19b / F20 / F24` 读 `47e4785-dirty`；
    当前代码 `0fbc3d2-dirty`
  - 新建 `tests/retrieval/test_result_side_gates.py` 三条断言：
    (a) 6 条门禁读的文件**都不等于**当前指纹（有人重跑时会红）
    (b) 必须是 6 条，且每个 code 在源码里真实存在
    (c) **v3 下 condition 消融对名次影响为 0**（用真实重跑，不读 v2 文件）
  - **只登记 F20 会给读者"只有一个门禁有这问题"的错误印象**；
    F24 更危险——它可能**反向变绿**（A 轴不饱和恰恰可能是排序没生效）

- [x] 3d.6 HANDOFF 的"21/27、24/27"要加混合口径限定
  - 写明：27 条里 **21 条跑在当前装置上，6 条读历史产物**
  - 否则读者会以为 27 条都跑在当前装置上

**实测纠错（我原本要写的一条断言，被数据否掉）**：

我原打算写"v3 重跑名次 == v2 冻结名次（sample 12/12、billing 10/12，
差异 `{billing-a1, billing-c1}`）"。实测**不成立**：

| subject | 实测一致 | 差异 | 你给的说法 |
|---|---|---|---|
| `sample` | **11/12** | `ledger-q2`（v2=1, v3=2） | 12/12 |
| `billing` | **11/12** | `billing-a6`（v2=1, v3=2） | 10/12，`{a1, c1}` |

**所以我不写那条断言**——它会锁住一个错误前提。改为写"v3 下 condition
消融影响为 0"（可复现、且直接对应 F20 的掉幅问题）。

## 4. 离线复算

**4.1 / 4.2 的目的是错的，已改写。** 原设计是
`recompute_ranks(per_case, weights)` **只读 `features`**——而 `features`
只是 **gold 自己**的三项，名次是相对于**整池**的。只读它复算不出"gold 为什么排第 3"，
验收 1 会退化成"只验分数、不验名次"。

所以复算函数改为 `recompute_order(candidates, weights, fusion_tags)`，
输入是**三个**：`features_by_tag`（每条的 score）+ `fusion_tags`（并列次序）+ 权重。

- [x] 4.1 写测试（构造）：人为造并列，两种裁决给出**相反**名次
  - 验证：`pytest tests/retrieval/test_rank_recompute.py -q` 先红
  - **完成**：`test_tie_rank_depends_on_fusion_order`。
    **构造必须同时固定两个条件，缺一则失去区分力**：

    | 条件 | 作用 |
    |---|---|
    | 两条分数完全相同 | 并列成立 |
    | 融合位置**反向于 tag 字典序** | 两种裁决才会给出相反名次 |

    **第二条件容易被漏掉。** 实测 `billing-c2`（v2 唯一真正并列的 case）
    就不满足它：`fused_position` 说 d 在前，tag 字典序也说 d 在前，**同向**。
    所以它**不能验证裁决规则**——"数据里有并列"不等于"这个并列能验证机制"。
    测试里显式断言了这两个条件（`fused.index("gold") < fused.index("d-1")`
    且 `"gold" > "d-1"`），换用例时会立刻红。
- [x] 4.2 实现 `recompute_order`（不复用 `recompute_ranks` 的名字——名字会误导）
  - 验证：4.1 转绿
  - **完成**：`fusion_tags=None` 时退回 tag 字典序，**那个返回值是错的**，
    保留它只为演示"缺输入会静默给出另一个名次"
- [x] 4.3 写测试（端到端）：用 `per_case` 的 `features_by_tag` + `fusion_tags` + 权重复算，
  与记录的 `rerank_order_tags` 及 `rank_after_rerank` 逐条相同，差异数为 0
  - 验证：`pytest tests/retrieval/test_rank_recompute_end_to_end.py -q` 通过
  - **完成**：6 条（sample/billing × lexical/adjacency + 多路池 + gold 名次）。
    **加了两条强度约束**，否则是空转：
    (a) 池 > 1 的 case ≥ 5（单条候选时任何实现都"复算一致"）；
    (b) 多路池里池 ≥ 5 的 case ≥ 5。实测单路 lexical 池最大只有 4 条。
- [x] 4.4 写测试：只改权重（不改 features）时，复算结果必须变化，且变化只由权重决定
  - 验证：同一份 `per_case` 用两组权重各算一次，断言两次结果不同且各自可重复
  - **完成**：由 `test_axis_policy.py::test_axis_policy_is_a_function_of_values_not_counts`
    与 `test_rank_recompute_end_to_end.py` 覆盖（权重作为唯一变量传入 `recompute_order`）。

## 5. 验收

- [x] 5.1 `openspec validate retrieval-v3-apparatus --strict` 通过
  - **已跑**：`Change 'retrieval-v3-apparatus' is valid`
- [x] 5.2 `uv run --no-sync ruff check .` 与 `uv run --no-sync mypy` 均 clean
  - **已跑**：`All checks passed!` / `Success: no issues found`
- [x] 5.3 全量测试通过，且失败数为 0
  - 验证：`uv run --no-sync pytest -q`，记录 passed/skipped 数
  - **已跑**：`1545 passed, 4 skipped, 5 deselected`
    （skip 含 `test_handoff.py` 的"存在进行中的变更，归档前不适用"，
    与 v3 目录为空时的两条指纹 skip——三者都在跳过消息里写明了原因）
- [x] 5.4 更新 `docs/HANDOFF.md` §0：把"有效特征数 A=3 / C=2"改为"排序特征=3，`condition` 为审计字段"，并记录 `billing` 两轴同构的事实
  - 验证：`pytest tests/retrieval/test_handoff_current.py -q` 通过
  - **完成**：§0 写明"排序特征 = 3（base/authority/status），condition 退出加权"；
    该小节记录 `billing` = `single_axis`（**不是 merged**，因为它不存在 cross 轴）。
    验证：`tests/retrieval/test_handoff_current.py` 与 `test_handoff_v3.py` 均通过。

## 6. 未决：轴是否合并

- [x] 6.1 按 2.3 的实测结果，在 proposal 里补一句结论：C 轴是否与"relation_within"合并
  - 验证：proposal 的“关键实测”一节与 2.3 的测试断言一致
  - **完成**：结论是 `ledger` = `two_axes`、`billing` = **`single_axis`**
    （不是 `merged`——`billing` 根本不存在 cross 轴）。
- [x] 6.2 若合并，v3 的数据集只需一种查询；若不合并，必须在 spec 里给出新的区分量
  - 验证：`openspec validate --strict` 在修改后仍通过
  - **完成**：按 subject 分别处置。spec 的"轴的定义必须可判定"已写明四值 policy、
    空轴规则，以及"cross 查询存在 <=> 存在池中只有 gold 一条的 relation"。

