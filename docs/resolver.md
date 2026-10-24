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
真双人标注必须用**两份副本**：

```bash
Copy-Item "data\conflict-set\test.jsonl" "data\conflict-set\test.alice.jsonl"
Copy-Item "data\conflict-set\test.jsonl" "data\conflict-set\test.bob.jsonl"

# 两人各自盲标，互不看对方
uv run python -m evals.tools.label --file data\conflict-set\test.alice.jsonl review --labeler alice
uv run python -m evals.tools.label --file data\conflict-set\test.bob.jsonl review --labeler bob

# 算 κ 并列出不一致条目
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
