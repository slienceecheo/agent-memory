# C3 报告：冲突判定状态机

> 生成日期：2026-10-25
> 场景集：60 条（dev 40 / test 20），六类均衡
> 模型：DeepSeek V4.1 Flash（本地网关，强制 SSE，响应缓存）
> 状态：**56/60 已人工确认，4 条 CONFLICT 修正后待重新确认**

## 标签确认状态（验收前置条件）

```
$ uv run python -m evals.tools.label --split dev summary
dev.jsonl: 40 条，已确认 37 条

$ uv run python -m evals.tools.label --split test summary
test.jsonl: 20 条，已确认 19 条
```

待确认的 4 条全部是 CONFLICT 类，原因见下一节。

**D6（macro-F1 ≥ 0.85）目前仍不成立**：CONFLICT 类只剩 5 条已确认样本，
不足以支撑该类的 F1 结论。下面的数字全部是"在机器提议标签上的参考值"。

## 修正：4 条 CONFLICT 配对不成立

标注过程中发现 9 条 CONFLICT 里有 4 条**不满足 CONFLICT 的前提**
（同一属性、同一对象、同一取值槽位上的两个竞争值）：

| id | 原配对 | 问题 | 修正后 |
|---|---|---|---|
| `dev-conf-01` | 喜欢花生酱 / 对花生过敏 | 偏好 vs 医学限制，维度不同 | 能吃花生 / 对花生过敏 |
| `dev-conf-02` | 能接受海鲜 / 对海鲜过敏 | "能接受"语义模糊，不构成互斥 | 不能吃海鲜 / 能吃海鲜 |
| `dev-conf-05` | 阿里云 / k8s | 云厂商 vs 编排平台，可同时成立 | 阿里云 / AWS |
| `test-conf-01` | 不吃牛肉 / 对乳制品过敏 | 同类不同对象，可并存 | 不吃牛肉 / 吃牛肉 |

**根因**：生成 CONFLICT 时用的是"把 candidate 的 authority 调低"这个语法操作，
没有检查两个值在语义上是否互斥。`lower_authority` 规则会忠实地把它们判成
CONFLICT，所以**这个错误不会让任何测试失败**。

**采取修正而非删除**：删除后 dev 只剩 3 条、test 剩 2 条 CONFLICT，
每类 2~3 条的 F1 方差会大到没有意义。

一个值得记录的事实：**这 4 条正是标注时被跳过的条目**。dev 轮的目的就是
校准标准，它在起作用。

## 0. 先说结论：这次的 100% 不能用来证明什么

| split | 模式 | accuracy | macro-F1 |
|---|---|---|---|
| test | 全量（规则 + 模型） | 1.0000 | 1.0000 |
| test | `--no-llm`（纯规则） | 1.0000 | 1.0000 |
| dev | 全量 | 1.0000 | 1.0000 |
| dev | `--no-llm` | 1.0000 | 1.0000 |

四种组合全部满分，且**模型与纯规则的差异为 0**。这几乎肯定意味着评估本身有问题，
而不是系统真的完美。下面逐条说明为什么，以及真正可用的信号是什么。

## 1. 为什么 100% 不可信

### 1.1 场景与规则出自同一个人

60 条场景是我写的，七条规则也是我按这些场景设计的。这是**循环论证**：
规则在"我想到的场景"上必然表现良好，但它在新场景上的泛化能力完全没有被测量。

这不是可以通过"再多写几条场景"解决的问题——只要场景和规则出自同一轮思考，
满分就只是自证。

### 1.2 模型被调用 17 次，但一次都没改变结果

实测 `test` 集：

| 来源 | 条数 |
|---|---|
| 规则命中 | 3 |
| 模型判定 | 17 |
| 禁用 | 0 |
| 判定失败 | 0 |

模型确实被调用了 17 次（因为 17 条文本不含正则能识别的变更标记），
但**这些场景的判定类别并不依赖"是否新状态"**：

- `BRANCH` 由条件差异决定
- `CONFLICT` 由权威更低决定
- `MERGE` 由值包含关系决定

只有 `SUPERSEDE` 依赖 `is_new_state`，而 test 集里唯一的 SUPERSEDE 场景
（`test-sup-04 "值班人现在是孙八"`）恰好被规则命中了。

**所以"模型与纯规则差异为 0"是场景设计的产物，不是模型没价值的证据。**

### 1.3 样本量太小，macro-F1 的方差很大

test 集每类只有 3~4 条。单个样本改变就能让某类 F1 抖动 25 个百分点，
进而让 macro-F1 抖动 4 个百分点。这个量级的样本**无法支撑任何显著性声明**。

## 2. 真正可用的信号

### 2.1 归一化覆盖率：19/20 → 20/20

第一轮跑出 `normalized_false = 1/20`，定位到 `dietary_restriction`
（饮食禁忌）这个关系没有登记在别名表里。已补入。

这个指标比 macro-F1 有用得多：它衡量**词表对真实输入的覆盖程度**，
且不依赖谁来写标签。

### 2.2 规则覆盖率：3/20

test 集里只有 3 条文本能被正则识别变更标记，17 条需要模型。

这说明**正则的作用域远比预期窄**。真实用户的表达大多不含"改成/现在"这类显式标记，
所以模型兜底是必需的，不是可选的。这个数字在任何标签方案下都成立。

### 2.3 判定分布的合理性

两种模式给出的类别分布都与期望分布一致（NOOP 3、ADD 3、MERGE 3、
SUPERSEDE 4、BRANCH 4、CONFLICT 3）。这说明**规则没有系统性偏向某一类**，
也没有靠"全判 ADD"这类退化解刷分。

## 3. 修掉的真实缺陷（这些与标签无关）

实现过程中发现并修复了**五个**会导致系统错误的问题：

| 缺陷 | 后果 | 修复 |
|---|---|---|
| `CONFLICTED` 条目与既有 ACTIVE 必然时间重叠 | 冲突候选根本无法落库 | 重叠触发器排除 CONFLICTED（它按定义就是同一时段的竞争说法） |
| `_find_existing` 只按精确 condition 查找 | 带条件的候选看不到同键其他分支，误判为 ADD | 增加 `active_all()`，按"同条件 → 无条件 → 任意条件"三级回退 |
| `resolve_conflict` 用胜者的 valid_from 关闭败者 | 胜者原本是 CONFLICTED 时会产生零长度区间 | 关闭时刻取两者起点的较大值，并把胜者起点推进到关闭之后 |
| 评测复用同一个库 | 场景互相污染，第二条 ADD 撞上第一条的 ACTIVE | 每条场景独立临时库 |
| **否定词被误判成"补充"** | `"吃牛肉"` 是 `"不吃牛肉"` 的子串，规则 4 把语义反转判成 MERGE | 检测值的**开头**是否带否定词；两侧否定状态不同则绝不判 MERGE |

### 第五个缺陷的修复过程本身值得记录

第一次修复用了"前 8 个字符里包含否定词"，结果引入了新回归：
`"张三 周三不在"` 中"不"在中间，被误判成否定，把 MERGE 错判成 SUPERSEDE，
dev 准确率从 100% 掉到 97.5%。

**是评测把这个回归抓出来的**，不是代码审查。修正为只检查开头后恢复 100%。
这个坑现在有专门的回归测试（`test_rule4_mid_value_negation_does_not_block_merge`）。


## 4. 要得出可信结论，需要做什么

按重要性排序：

1. ~~**人工确认 60 条标签**~~ **已完成 56/60**。
   剩余的 4 条是刚修正的 CONFLICT 配对，需要重新确认：
   ```
   uv run python -m evals.tools.label --split dev review --labeler <name>
   uv run python -m evals.tools.label --split test review --labeler <name>
   ```
   交互式模式默认盲标，只显示尚未确认的条目。
2. **引入第二标注者并计算 κ**（未开始）。
   一个人确认的标签仍有主观性；κ 能暴露"两个人的判定口径是否一致"。
   ```bash
   Copy-Item "data\conflict-set\test.jsonl" "data\conflict-set\test.alice.jsonl"
   uv run python -m evals.tools.label --file data\conflict-set\test.alice.jsonl review --labeler alice
   uv run python -m evals.tools.label kappa --a-file ...alice.jsonl --b-file ...bob.jsonl
   ```
3. **扩充场景集的来源**（未开始）。当前 60 条全部出自我一人。
   应该从真实对话日志里采样，或者请第二个人独立写一批场景。
   本次 CONFLICT 的 4 条错误正是"自写自测"的典型代价。
4. **让模型成为决定性因素**（未开始）。构造一批"文本不含变更标记、且判定结果
   确实取决于是否新状态"的场景，才能测出 `--no-llm` 的真实差距。

## 5. 已锁定的实现契约（与标签无关，可独立信任）

这些性质不依赖谁写标签，是实现本身的正确性保证：

| 性质 | 测试文件 |
|---|---|
| 规则顺序不可静默改变 | `test_rule_order.py`（9 条，含变异验证） |
| 判定集合完备（任意输入都有出口） | `test_completeness.py`（hypothesis 200 例） |
| 低权威陈述永不取代高权威事实 | `test_completeness.py`（安全性质） |
| 六类判定各自驱动正确的存储迁移 | `test_apply.py` |
| 归一化不合并不同主体 | `test_normalize.py` |
| 稀有类失败会拉低 macro-F1 | `test_classification_metrics.py` |
| 无样本类别不计入分母 | `test_classification_metrics.py` |
| κ 完全相反时为负而非 0，且为多类别口径 | `test_kappa.py` |
| 否定词翻转不判为补充 | `test_rules.py`（5 条变体） |
| 值中间的否定词不阻断合并 | `test_rules.py`（回归） |
| CONFLICT 配对不会被规则判成 MERGE | `test_report_consistency.py` |
| 交互式标注默认盲标 | `test_label_review.py` |
| 双人 κ 用 expected 而非 labeler | `test_kappa_files.py` |
| 修场景内容不丢已确认标签 | `test_preserve_labels.py` |

## 6. 原始结果

- `results/conflict-test-full.json`
- `results/conflict-test-no-llm.json`
- `results/conflict-dev-full.json`
- `results/conflict-dev-no-llm.json`

## 7. 一句话总结

**实现是对的，评估还不能作数。**

六类判定、规则顺序、状态映射、归一化边界都有测试锁定，四个真实缺陷已修复。
但 100% 的分数来自"场景与规则同源"，不构成任何能力证明。
要让它变成可信的结论，需要人工确认标签 + 第二标注者 + 独立来源的场景。
