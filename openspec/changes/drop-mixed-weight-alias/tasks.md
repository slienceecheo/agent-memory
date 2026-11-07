# Tasks

> 一个 commit 可完成。改动面很小（3 处真代码 + 1 处 docstring + 2 处文档表格），
> 但**顺序不能换**：先写红断言，再删键。
>
> **基线**：`1784 passed, 3 skipped`（`cosine-as-sort-feature` 归档后）。

## 1. 先写会失败的断言

- [x] 1.1 在 `tests/retrieval/test_preregistered_naming.py` 新增
  `test_weight_names_do_not_collide_with_axis_values`：

  ```python
  def test_weight_names_do_not_collide_with_axis_values() -> None:
      """权重配置名不得与数据集轴值同名。"""
      from evals.datasets.retrieval_v2 import Axis
      from memory.retrieval.rerank import PREREGISTERED_WEIGHTS

      overlap = set(PREREGISTERED_WEIGHTS) & {a.value for a in Axis}
      assert not overlap, f"权重名与轴值撞车：{sorted(overlap)}"
  ```

  验证：`uv run --no-sync pytest tests/retrieval/test_preregistered_naming.py -q`，
  **预期红**，报错文本必须是 `权重名与轴值撞车：['mixed']`。
  若报的是 `ImportError`，先查 `Axis` 的导入路径。

  **为什么写在测试里而不是 `rerank.py`**：`Axis` 属评测层，`rerank.py` 属产品层，
  产品不得依赖评测层（见 design D4）。

- [x] 1.2 把 `test_preregistered_names_describe_questions` 的名字集合改成
  `{"uniform", "cosine_only"}`，并在 docstring 里写明"`mixed` 已删除，理由见下"。
  验证：预期红（当前集合含 `mixed`）。

- [x] 1.3 在 `test_anchor_does_not_follow_the_default` 里断言
  `DEFECT18_WEIGHTS is not PREREGISTERED_WEIGHTS["uniform"]`，
  且两者的三元组相同。

  **验证：现在绿**（`DEFECT18` 本来就是独立对象）——这条锁的是已有正确形态，
  不是修一个新 bug。

  **docstring 必须写明它守的是什么**，否则下一个人会问"两个相等的常量为什么要
  `is not`"。要写的不是"防止同值"，而是：

  > 这两行字面量看起来重复，很容易被"优化"成
  > `DEFECT18_WEIGHTS = _DEFAULT_WEIGHTS`。那样写语法正确、值也相同，
  > 但"改默认时锚点不动"这个性质会静默消失。
  > 本条断言的是**对象身份**，不是数值——数值本来就该相等。

  **它的价值不在现在红不红，而在阻止一次看起来合理的重构。**

  **但必须写明这条断言依赖一个前提**（否则它会在前提消失后永远为真）：

  > 本条依赖 `_DEFAULT_WEIGHTS` 是**模块级单例**。
  > 若将来改成"函数返回新实例"（如 `disabled_weights()` 那样），
  > 每次构造都会产生不同对象，`is not` 恒为真而判据失去意义。
  > 那时应改用行为断言：清空预注册表后 `DEFECT18_WEIGHTS` 仍可用
  > （见 `test_feature_set_cosine.py::test_defect18_carrier_is_independent_of_preregistered`）。

  **为什么保留它而不是只留行为断言**：行为断言守"缺陷算术不随预注册表变"，
  而 `is not` 守"有人图省事把它写成别名"——后者是一次具体重构的防线，
  而那种重构看起来合理（两行重复的字面量）。两层保护不重复。

  **必须能双向证伪**：把 `DEFECT18_WEIGHTS = RerankWeights(...)` 改成
  `= _DEFAULT_WEIGHTS`，它必须红。

## 2. 删别名

- [x] 2.1 `src/memory/retrieval/rerank.py`：删除 `"mixed": _DEFAULT_WEIGHTS` 条目
  及其注释（第 112-114 行）。

  **但这不是"删键 + 删注释"，而是"重写默认值的理由"。**
  `rerank.py:98-99` 是"默认值为什么是 0.2/0.2/0.6"的**唯一解释**，
  而它把支点放在 `mixed` 上：

  ```
  #: **0.2/0.2/0.6 不是"随手调的数字"**：它等于 `mixed`，即"给无信号项留余量"的配置。
  #: 选它作默认的理由与选 `mixed` 作稳健性对照相同——比 `cosine_only` 保守。
  ```

  删掉 `mixed` 后这两行会指向一个不存在的键。**必须换成能独立成立的解释**：

  > 默认权重的数值。
  >
  > **0.2/0.2/0.6 不是"随手调的数字"**：它与缺陷 19 的载体
  > `DEFECT18_WEIGHTS` 同值，而那个数值来自一个**可复算的比值**：
  > 罚分推翻 base 优势的条件是 `authority / base > 0.09`
  > （`pen > adv` ⇔ `auth × 1.0 > base × d_base`，`d_base = 1 − 0.910`）。
  > 此处比值 `0.2 / 0.2 = 1.0`，**余量 11.1 倍**。
  >
  > 判据就是 `test_defect18_authority` 的三个算术断言
  > （0.0180 / 0.2000 / 0.1820）。
  >
  > **这不是"唯一正确的值"**：比值 0.75 也成立（余量 8.3 倍，
  > 旧配置 `0.4/0.3` 就是）。**余量只取决于 `authority/base` 的比值，
  > 与绝对值无关**——所以改权重时该守的是比值下限 `0.09`，不是某个具体数。

  **⚠ 停在这里的中间态**：此刻 `1.1`（轴值交集）已绿，而
  `test_preregistered_names_describe_questions`（断言三个名字）**仍红**——
  那是 2.2 要修的，不是 2.1 改坏。**跑全量会看到正好 1 条红，这是预期的。**

  **停下时要贴三样**：

  1. `rerank.py` 新注释全文（3–6 行）；
  2. `uv run --no-sync pytest tests/retrieval/test_preregistered_naming.py -q`
     输出最后 10 行；
  3. `Select-String -Path src/memory/retrieval/rerank.py -Pattern "mixed"` 的结果
     （预期 **0 命中**，验证 design 风险表那条判据）。

  **第 2 样的判据要验"实际值"，不是"文本里有那句话"**：

  | 不合格的判据 | 为什么不够 |
  |---|---|
  | 报错文本含"预注册名字是" | 只证明断言跑了，不证明它报了正确的差异 |
  | 输出含 `1 failed` | 只证明有失败，不证明失败在预期的那条 |

  **合格判据**：输出必须同时满足

  - `1 failed`
  - 实际值那一侧是 `['uniform', 'cosine_only']`（**不含 `mixed`**）
  - "应为"那一侧仍是 `uniform/mixed/cosine_only`（那是 test 里还没改的期望）

  第三点很重要：它证明红的是 **1.2 要改的那条测试**，
  而不是别的测试也跟着红了。

- [x] 2.2 `tests/retrieval/test_preregistered_naming.py` 三处：
  1. 删 `test_mixed_and_default_are_the_same_value_but_distinct_keys`
     （命题"两个键但同值"已不成立，且它守的性质本来就没实现）；
  2. 改 `test_weight_names_do_not_collide_with_axis_values` 之外那条
     模块级 docstring（第 13 行）里"`mixed`：给无信号项留余量会损失多少"这一行；
  3. 改 `test_default_weights_are_the_preregistered_values` 的 docstring
     （第 30-31 行）——它写着"选它作默认的理由与选 `mixed` 作稳健性对照相同"，
     而 `mixed` 将不存在。

  **后两处不会让测试红**（docstring 不参与断言），但会让文档说谎。
  本项目在别处抓过这个形态：断言绿而注释描述了一个已不存在的东西。

  验证：该文件全绿；且 `Select-String -Path tests/retrieval/test_preregistered_naming.py -Pattern "mixed"`
  **0 命中**。

- [x] 2.3 `tests/retrieval/test_feature_set_cosine.py` 里
  "不能写 `DEFECT18_WEIGHTS != PREREGISTERED_WEIGHTS["mixed"]`" 这句 docstring
  提到 `mixed`，改成引用 `uniform`（那个键仍然存在）。

  验证：`uv run --no-sync pytest tests/retrieval/test_feature_set_cosine.py -q` 全绿。

## 3. 文档同步

- [x] 3.1 `docs/reports/v2-what-it-measures.md`：命名表（约 :1056）删掉
  `| (0.2,0.2,0.6) | **mixed** | 不等权但有退路 |` 那一行。

  **同一节还有一句要改**：

  ```
  **本节不做这个改动**——它需要单独变更。
  ```

  本次变更**就是那个单独变更**。留着这句会让读者以为改名还没做。

  验证（两条都必须跑）：
  1. `Select-String -Path docs/reports/v2-what-it-measures.md -Pattern "mixed"`
     的命中里**不再有"权重/命名表"的语境**（`Axis` 相关的 `mixed` 保留不动）；
  2. `Select-String -Path docs/reports/v2-what-it-measures.md -Pattern "本节不做这个改动"`
     **0 命中**。

  **为什么第 2 条必须单独验证**：那句话在写下时是真的（"这件事还没做"），
  本次变更完成后它变成假的，而**没有任何断言能发现这种"文档时态"失效**。
  它与"HANDOFF 日期没更新"同类，但更难发现——日期有公式，这种陈述没有。
  所以只能靠一次显式的零命中检查。

- [x] 3.2a `docs/HANDOFF.md:133` 的
  "`PREREGISTERED_WEIGHTS` 三组" 改成 "两组"。

  **这一行已经漂移过两次**（实测 git 历史）：

  | 提交 | 该行 | 现实 | 是否被断言守着 |
  |---|---|---|---|
  | `e8ca4f7~1`（加 cosine 前） | 四组 | uniform/base_heavy/auth_heavy/status_only | ❌ |
  | `e8ca4f7`（加 cosine 后，我改的） | 三组 | uniform/mixed/cosine_only | ❌ |
  | **本次之后** | 应两两 | uniform/cosine_only | ❌ |

  我在 `e8ca4f7` 改这行时，就是在**手动同步一个没有断言守着的数字**——
  若那次漏改，没人会发现。所以这一步不是"顺手改一个数"。

- [x] 3.2b **补上守着它的断言**（否则还会有第三次漂移）：

  在 `tests/retrieval/test_handoff_v3.py` 新增：

  ```python
  def test_handoff_preregistered_count_matches_reality() -> None:
      """HANDOFF 里写的预注册组数必须等于 PREREGISTERED_WEIGHTS 的长度。

      这一行曾漂移两次（四组 -> 三组 -> 两组），而两次都没有断言守着。
      判据从 `len(PREREGISTERED_WEIGHTS)` 算，不从文档反推。
      """
      text = _text()
      from memory.retrieval.rerank import PREREGISTERED_WEIGHTS

      n = len(PREREGISTERED_WEIGHTS)
      assert f"`PREREGISTERED_WEIGHTS` {n} 组" in text, (
          f"HANDOFF 没写 '`PREREGISTERED_WEIGHTS` {n} 组'，"
          f"而实际有 {n} 组：{sorted(PREREGISTERED_WEIGHTS)}"
      )
  ```

  验证：该测试绿。**双向证伪**：
  1. 把 HANDOFF 那行的数字改错（如写成 3）→ 必须红；
  2. 改回 → 绿。

  **为什么判据是"精确匹配 `N 组`"而不是"含 '组' 字"**：
  后者会在数字错时仍然通过（本项目已登记过的形态）。

## 4. 全量与验收（apply 阶段）

- [x] 4.1 `uv run --no-sync pytest tests/ -q`：预期
  **1784 passed, 3 skipped**（新增 1 条断言 + 删 1 条测试，净 0；以实跑为准）。
  `results/*.json` 顶层仍 **48**。

- [x] 4.2 `uv run --no-sync ruff check src evals tests` 与 `uv run --no-sync mypy` 全过。

- [x] 4.3 `openspec validate drop-mixed-weight-alias --strict` 输出
  `Change 'drop-mixed-weight-alias' is valid`。

- [x] 4.4 **双向证伪（必做）**：
  1. 把 `"mixed": _DEFAULT_WEIGHTS` 加回去 → 1.1 必须红；
  2. 把 `DEFECT18_WEIGHTS` 改成 `= _DEFAULT_WEIGHTS` → 1.3 必须红；
  3. 两处都改回 → 全绿。

  若任一步"改坏了还绿"，停下查判据，不要继续归档。

## 5. 归档后回填（不在 apply 阶段）

> **为什么这一步不在 4.1 之前**：`recount_specs.py` 只扫
> `openspec/specs/`，不扫 `openspec/changes/`（实测：6 个 vs 45 个 `spec.md`）。
> 所以 apply 期间改 delta **不会**改变 462/399/106 这三个数——
> 它们只在 `openspec archive` 把 delta 合进主 spec 之后才变。
>
> 反过来，若在 4.1 之前跑回填，`compute()` 给的是旧数，回填本身没有意义。

- [ ] 5.1 归档后跑 `uv run --no-sync python -m evals.tools.recount_specs`，
  按输出回填 HANDOFF §0.6（MUST 行表 + 统计时点 + 四类细分）与 §0.7
  （Scenario 表 + 统计时点）与「要求数」表。

  **三个表要一起改**：`test_per_capability_counts_match_compute` 逐行比对，
  只改一张会让另外两张红。

- [ ] 5.2 确认 `test_must_coverage_numbers_are_real` 与
  `test_per_capability_counts_match_compute` 转绿。

  **为什么它们会在归档后红**：它们读 `compute()` 再比对 HANDOFF；
  归档让 `compute()` 的分子变大，而 HANDOFF 还是旧数。

- [ ] 5.3 HANDOFF 的「更新日期」改成最新归档目录的日期
  （`test_handoff_freshness` 守着这一条）。

## Workflow follow-up

- 归档前贴出 `openspec validate --strict` 与全量 pytest 的原始输出。
- 归档后检查 git status，执行 group 5 的回填，再单独 commit。
- 确认 `results/*.json` 顶层仍为 48。
