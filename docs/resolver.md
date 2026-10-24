# 冲突判定：六类状态机

## 六类定义

| 类 | 含义 | 旧值是否仍成立 | 存储动作 |
|---|---|---|---|
| `NOOP` | 完全重复的陈述 | 是 | 无写入，只记事件 |
| `ADD` | 该键此前没有有效值 | — | 插入，ACTIVE |
| `MERGE` | 旧值仍成立，但信息不完整 | **是** | 原子取代 + `reason=补充` |
| `SUPERSEDE` | 旧值失效，被新值取代 | 否 | 原子取代 |
| `CONFLICT` | 矛盾但无法裁决 | 既有值仍 ACTIVE | 新值以 CONFLICTED 落库 |
| `BRANCH` | 条件不同，两者并存 | 是（不同场景） | 插入，条件不同故不冲突 |

`MERGE` 与 `SUPERSEDE` 在存储层效果相同（旧条目关闭、新条目 ACTIVE），
差别在**语义与审计原因**。合并会让 `valid_to` 的含义变模糊，
而分开记录 `reason` 才能让时间线讲清楚"这是补充还是改主意"。

## 七条规则与顺序

```
1. 同键无 ACTIVE                    → ADD
2. 同条件 + 值相同 + 权威相同        → NOOP
3. 条件不同                          → BRANCH
4. 新值包含旧值（旧值仍真）           → MERGE
5. 权威更低                          → CONFLICT
6. 权威不低 + 确认是新状态            → SUPERSEDE
7. 其余                              → CONFLICT（兜底）
```

### 顺序为什么不能变

四条关键约束，每条都有测试锁定（`tests/resolver/test_rule_order.py`）：

| 若顺序被改 | 后果 |
|---|---|
| 4 排在 2 之前 | `"pnpm"` 包含于 `"pnpm"`，每次重复确认都产生新版本 |
| 5 排在 3 之前 | "开会喜欢早上"与"写代码喜欢深夜"被判成矛盾 |
| 5 排在 4 之前 | 系统推断的补充信息（权威低）被丢弃 |
| 6 排在 5 之前 | **工单备注会覆盖用户自述的过敏史** |

最后一条是安全相关的。变异测试验证过：删掉规则 5，`test_lower_authority_beats_supersede` 立即失败。

## 模型只在一处参与

`"是否陈述新状态"` 是唯一需要语义理解的判断：

- `"我们这个仓库现在改用 npm 了"` → 新状态
- `"我们用 npm"` → 可能只是重复

判断顺序：先走正则（覆盖"改成/现在/不再/以前…现在…"等），未命中才调模型。

**为什么不做成模型主导**：如果模型参与主要判定，就无法回答"不用模型会差多少"。
限制在一个二分类上，消融实验才有意义。

### 四种来源可统计

| source | 含义 |
|---|---|
| `rule` | 正则命中 |
| `llm` | 模型判定 |
| `disabled` | 显式禁用模型（消融模式） |
| `failed` | 模型返回不可解析或调用失败 |

`failed` 时走 `CONFLICT` 兜底——**宁可标冲突，也不猜测覆盖**。

## CONFLICT 的构造纪律（一次真实踩坑）

`NOOP` / `MERGE` / `SUPERSEDE` / `BRANCH` 处理的是**同一条事实的演进**，
值天然耦合（pnpm → npm、早上 ↔ 深夜），想写错都难。

**只有 `CONFLICT` 需要凭空构造一个矛盾**，而这里最容易滑倒。

### 判定前提

> 同一属性、同一对象、同一取值槽位上的两个竞争值。

检验方法：把两条并列读一遍，**能否同时为真？** 能 → 不是 CONFLICT。

### 三类典型错误

| 错误 | 例子 | 为什么不是冲突 |
|---|---|---|
| **维度不同** | 「部署在 k8s」 vs 「部署在阿里云」 | 阿里云上跑 k8s 完全成立 |
| **对象不同** | 「对乳制品过敏」 vs 「不吃牛肉」 | 两个不同的饮食限制，可以并存 |
| **表述歧义** | 「能接受海鲜」 vs 「对海鲜过敏」 | 「能接受」可读作口味偏好，不构成互斥 |

第三种最隐蔽：`relation` 字段都写着 `dietary_restriction`，看起来合法，
但同一 relation 下**不同对象**的两条事实是并存的，不是互斥的。

### 为什么会犯这个错

生成场景时用的是「把 candidate 的 authority 调低」这个**语法层面**的操作，
没有检查那对值在**语义**上是否真的互斥。规则 `lower_authority` 会忠实地把它们
判成 `CONFLICT`——所以这个错误**不会让任何测试失败**。

`tests/resolver/test_report_consistency.py` 抓不到它，因为「两个值是否互斥」
需要语义理解。这只能靠标注纪律，不能靠测试。

### 本次修正记录

60 条场景里有 4 条 CONFLICT 配对不成立（9 条 CONFLICT 里占 44%）：

| id | 原配对 | 修正后 |
|---|---|---|
| `dev-conf-01` | 喜欢花生酱 / 对花生过敏 | 能吃花生 / 对花生过敏 |
| `dev-conf-02` | 能接受海鲜 / 对海鲜过敏 | 不能吃海鲜 / 能吃海鲜 |
| `dev-conf-05` | 阿里云 / k8s | 阿里云 / AWS |
| `test-conf-01` | 不吃牛肉 / 对乳制品过敏 | 不吃牛肉 / 吃牛肉 |

**采取「修」而不是「删」**：删掉后 dev 只剩 3 条 CONFLICT、test 剩 2 条，
每类 2~3 条的 F1 方差会大到没有意义。

值得注意的是：这 4 条正是**标注时被跳过**的条目。dev 轮的目的就是校准标准，
它在起作用。这也解释了第二标注者的价值——他能看到的不是「代码对不对」，
而是「题目本身成不成立」。

## 归一化宁可不猜

别名表是手写小词表。未登记的表述保留原值并标记 `normalized=False`。

归一过度的代价比归一不足大得多：

- 归一不足 → 同一概念变两条事实。表现为"记忆里有两份"，可见、可修。
- 归一过度 → 不同概念合并。表现为"记忆里错了一份"，很难从结果发现。

**刻意不登记的**：`"这个仓库"`、`"本项目"` 这类指代词。
它们在不同对话里指不同仓库，映射成同一个规范名会把所有项目合并成一条。

## 评估当前不可信

`docs/reports/c3-resolver.md` 记录了完整结论，核心是：

60 条场景与七条规则出自同一个人，因此 100% 的分数是**循环论证**。
报告里同时给出了三个与标签无关的真实信号：

- 归一化覆盖率（补词表后 20/20）
- 规则覆盖率（test 集 3/20，说明模型兜底必需）
- 判定分布无系统性偏向

补充两点标注侧的事实：

- 三个标注者（主标注 / alice / bob）20 条零分歧，κ = 1.000。
  但这只能算**同源复核**，不是独立双标注——真正独立的标注者应当产生非零分歧。
- 标注过程中发现过 3 条硬错误（`existing_value` 为空却标成 NOOP）。
  κ 抓不到这类问题，因此有独立的逻辑自洽检查（见下）。

### 标注的逻辑自洽检查

`check_logical_consistency()` 检查单条标注是否**违反定义**
（不是"两人是否一致"）。两类硬错误：

| 错误 | 为什么错 |
|---|---|
| `existing_value` 为空却标成 NOOP / MERGE / SUPERSEDE / BRANCH | 这四类都以"存在既有值"为前提 |
| candidate 与 existing 相同却标成 SUPERSEDE | 完全相同应判 NOOP |

**κ 抓不到这些**：κ 只衡量两人是否一致，不衡量单条是否合法。
两个人可以一致地都标错。

## 场景集与标注

### 交互式标注（推荐）

```bash
# 默认盲标：不显示提案标签，避免被带偏
uv run python -m evals.tools.label --split test review --labeler 你的名字
```

逐条显示：

```
[test-sup-01]
  新陈述：现在改用 yarn 了
  候选值：yarn
  既有值：pnpm
  权威：user_direct
  1=NOOP 2=ADD 3=MERGE 4=SUPERSEDE 5=CONFLICT 6=BRANCH  s=跳过 b=回退 q=退出
```

输入 `1`–`6` 或类别名即可，回车确认。`s` 跳过、`b` 回退上一条、`q` 退出。

三条设计要点：

- **默认盲标**：不显示 `expected`。一旦显示，标注者会跟着提案走，
  标签失去独立性，κ 与 macro-F1 都变成自证。想看提案加 `--show-expected`。
- **即时落盘**：标完一条立刻写文件，中途退出不丢进度。
- **回退即撤销**：按 `b` 会把上一条改回 `proposed`，而不是留着一个错标签。

### 其他命令

```bash
# 查看待确认条目（会显示提案标签，正式标注时不要用）
uv run python -m evals.tools.label --split test list --status proposed

# 单条确认
uv run python -m evals.tools.label --split test confirm \
    --id test-sup-01 --label SUPERSEDE --labeler alice

# 分布与进度
uv run python -m evals.tools.label --split test summary
```

### 双人标注与 κ

一条场景只有一个 `labeler` 字段，两人标同一份文件会互相覆盖。
真双人标注必须用**副本**，且副本的标签必须先重置：

```bash
# 一条命令完成"复制 + 重置为全 proposed"
uv run python -m evals.tools.label --split test new-annotator --name bob

# 然后 bob 独立盲标（默认模式，此时全部都是 proposed，所以会问全部 20 条）
uv run python -m evals.tools.label --file data\conflict-set\test.bob.jsonl review --labeler bob
```

**为什么不能直接 `Copy-Item`**：副本会继承主文件的 `confirmed` 状态，
而 `review` 默认只问未确认条目。第二标注者打开后只会被问到剩下那一两条，
κ 的样本量退化成没有意义。

`new-annotator` 会重置 `label_status` / `labeler` / `confirmed_at`
三个字段，内容原样保留。

### 独立复核模式（`--all`）

如果副本已经存在且带有别人的标注，用 `--all` 强制逐条重标：

```bash
uv run python -m evals.tools.label --file data\conflict-set\test.bob.jsonl `
    review --labeler bob --all
```

**安全约束**：`--all` 会覆盖已有标注，所以只允许用在副本文件上
（文件名形如 `test.bob.jsonl`）。误对主文件 `test.jsonl` 使用会被拒绝
（退出码 2）。确实要重标主文件必须显式加 `--force`。

两种模式的差别：

| 模式 | 问什么 | 用途 |
|---|---|---|
| 默认 | 只问 `proposed` | 自己接着上次标 |
| `--all` | 问全部并覆盖 | 第二标注者独立复核 |

### 计算 κ

```bash
uv run python -m evals.tools.label kappa `
    --a-file data\conflict-set\test.alice.jsonl `
    --b-file data\conflict-set\test.bob.jsonl
```

输出：

```
共同条目 20 条，Cohen's κ = 0.940
判定：高度一致，可直接采用
不一致条目：
  test-conf-03: SUPERSEDE vs MERGE
```

κ 的判定阈值：

| κ | 判定 | 该怎么办 |
|---|---|---|
| ≥ 0.8 | 高度一致 | 直接采用 |
| 0.7–0.8 | 可接受 | 报告里说明 |
| 0.6–0.7 | 偏弱 | 逐条讨论不一致项后重标 |
| < 0.6 | 一致性不足 | 停下，先对齐六类定义 |

**κ 必须是多类别口径**（6×6 列联表），不能折成"是否一致"二分类：
二分类会丢掉"错成了哪一类"的信息，并把多数类的一致率算得过高。

`proposed` 的标签不能作为验收依据：`run_conflict` 会拒绝运行（退出码 2），
除非显式加 `--allow-proposed`，此时结果会标注"仅供参考"。

## 指标为什么用 macro-F1

六类里稀有类只占 10%，全判错时总体准确率仍能到 90%，完全掩盖问题。
macro-F1 让每类等权。

无样本的类别**从分母排除**，而不是记 0 分——记 0 分会让"这次没考"
变成"这次考砸了"。

样本数必须随分数一起报：单样本类的 F1=1 毫无统计意义。

## 验证

```bash
uv run pytest tests/resolver -q          # 判定、规则、指标、场景集
uv run pytest tests/resolver/test_rule_order.py -q   # 顺序锁定
```
