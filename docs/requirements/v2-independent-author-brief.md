# v2 数据集：独立编写说明（交给第二位作者）

> 你写 5 个 subject，我写 15 个，**互不看**。
> 本文档只给你 schema、一个填写示例、以及数据规则。
> **不含**我的任何数据、任何分数、任何通过率——知道了就会照着凑，独立性就没了。

## 1. 你要交什么

两份 JSONL 文件：

```
memories.jsonl   # 记忆库：一个 subject 的全部事实，含条件分支
queries.jsonl    # 查询：自然提问 + 它指向哪条记忆
```

规模：**5 个 subject**。每个 subject 的要求见第 4 节。

## 2. `memories.jsonl` 字段

| 字段 | 必填 | 说明 |
|---|---|---|
| `memory_id` | ✅ | 库内唯一，建议 `<subject>-<relation>-<序号>` |
| `subject` | ✅ | 归一后的实体，如 `project:docs-site` |
| `relation` | ✅ | 归一后的属性，如 `build_engine` |
| `condition` | ◯ | 条件分支；无条件为 `null` |
| `value` | ✅ | 记忆值 |
| `memory_text` | ✅ | **产生这条记忆的原话**，不许为空 |
| `authority` | ✅ | `user_direct` / `user_document` / `third_party` / `system_inferred` |
| `status` | ✅ | 当前只写 `ACTIVE` |
| `branch_nature` | ✅ | `natural` / `forced`（见第 5 节） |
| `valid_from` | ✅ | 带时区 ISO-8601，如 `2026-01-01T00:00:00+00:00` |

## 3. `queries.jsonl` 字段

| 字段 | 必填 | 说明 |
|---|---|---|
| `query_id` | ✅ | 唯一 |
| `subject` | ✅ | 属于哪个 subject |
| `axis` | ✅ | `A` / `C` |
| `cue_type` | ✅ | `explicit` / `implicit`（见第 5 节） |
| `query` | ✅ | **自然提问**，问句，不是记忆原文 |
| `query_condition` | ◯ | 查询携带的条件（`axis=A` 时通常要给） |
| `gold_memory_id` | ✅ | 必须存在于 `memories.jsonl` |
| `expected_value` | ✅ | 便于人工复核 |
| `author` | ✅ | 写 `independent` |

## 4. 结构要求（这几条不满足会直接判不合格）

每个 subject：

| 要求 | 数值 |
|---|---|
| relation 数 | 1–3 个 |
| **至少 2 个 relation 有 condition 分支** | 每个 3–5 个分支 |
| **每个 condition 分支都必须有一条查询指向它** | 100% |
| A 轴查询 | 每个分支一条 |
| C 轴查询 | 每个 `(subject, relation)` 一条 |
| **implicit 占 A 轴查询** | **≥ 50%** |

### 什么叫"每个分支都有查询指向它"

若某个 relation 有 3 个分支（`A` / `B` / `C`），
那必须至少有 3 条查询，分别以这三条记忆为 `gold_memory_id`。

否则池里虽然有 3 条，但只有 1 条被考过——这测不到任何东西。

## 5. 两个关键概念

### `cue_type`：查询有没有说破条件

| 值 | 形态 | 例子 |
|---|---|---|
| `explicit` | 查询里直接点名条件 | "**夜间**告警找谁？" |
| `implicit` | 条件要从情境推断，不出现条件词 | "半夜两点告警响了，该把谁叫起来看？" |

**implicit 是本数据集的核心难度**，因为它没有答案的值、也没有分支名，
唯一的区分信号就是"这句话描述了哪个情境"。

写 implicit 时的两条要求：

1. **语义必须能召回 gold**——不能写成与 `memory_text` 完全无关的话
2. **条件必须是唯一区分信号**——池里应有其他分支被召回，靠条件才能分开

### `branch_nature`：分支是天然的，还是硬编的

| 值 | 说明 |
|---|---|
| `natural` | 这个 relation 在真实场景里本来就有多个条件分支（如值班人按时间段） |
| `forced` | 为了凑分支数硬编的（如给"WiFi 密码"编出"在家/在公司"） |

**尽量写 `natural`。** 若某个 relation 只有一个值，就让它是单值，
不要为了凑 3 个分支编造条件——那会让"条件匹配"看起来有效，实际只是记住了编造的词。

## 6. 两条硬规则（会机器检查）

| 规则 | 说明 |
|---|---|
| **query ≠ memory_text** | 查询不能是产生那条记忆的原话。必须是问句 |
| **query 不含 gold 的 value** | 否则等于把答案写进问题里 |

## 7. 填写示例（`project:docs-site`）

**这个示例故意用小结构**（1 个 2 分支 + 3 个单值），
只为展示字段。**你不能照抄这个形状**——你的 5 个 subject
必须满足第 4 节的"至少 2 个 relation 有 3–5 个分支"。

```json
{"memory_id": "docs-build-1", "subject": "project:docs-site", "relation": "build_engine", "condition": null, "value": "hugo", "memory_text": "文档站用 hugo 构建，别换成 jekyll 了", "authority": "user_direct", "status": "ACTIVE", "branch_nature": "natural", "valid_from": "2026-01-01T00:00:00+00:00"}
{"memory_id": "docs-branch-1", "subject": "project:docs-site", "relation": "deploy_branch", "condition": "主站", "value": "main", "memory_text": "主站从 main 分支发布", "authority": "user_direct", "status": "ACTIVE", "branch_nature": "natural", "valid_from": "2026-01-01T00:00:00+00:00"}
{"memory_id": "docs-branch-2", "subject": "project:docs-site", "relation": "deploy_branch", "condition": "预览站", "value": "gh-pages", "memory_text": "预览站走 gh-pages，每次 PR 自动更新", "authority": "user_direct", "status": "ACTIVE", "branch_nature": "natural", "valid_from": "2026-01-01T00:00:00+00:00"}
{"memory_id": "docs-theme-1", "subject": "project:docs-site", "relation": "theme_repo", "condition": null, "value": "docsy", "memory_text": "主题用的是 docsy", "authority": "user_direct", "status": "ACTIVE", "branch_nature": "natural", "valid_from": "2026-01-01T00:00:00+00:00"}
```

```json
{"query_id": "docs-q1", "subject": "project:docs-site", "axis": "C", "cue_type": "explicit", "query": "文档站用什么构建？", "gold_memory_id": "docs-build-1", "expected_value": "hugo", "author": "independent"}
{"query_id": "docs-q2", "subject": "project:docs-site", "axis": "A", "cue_type": "explicit", "query": "主站从哪个分支发布？", "query_condition": "主站", "gold_memory_id": "docs-branch-1", "expected_value": "main", "author": "independent"}
{"query_id": "docs-q3", "subject": "project:docs-site", "axis": "A", "cue_type": "implicit", "query": "提 PR 之后想先看效果，去哪儿看？", "query_condition": "预览站", "gold_memory_id": "docs-branch-2", "expected_value": "gh-pages", "author": "independent"}
```

注意 `docs-q3`：它没有出现"预览站"三个字，但语义指向预览站——
这才是 `implicit`。

## 8. 不要做的四件事

1. **不要为了凑分支数编造条件**——单值 relation 就保持单值
2. **不要为了让某个特征"有方差"而改 authority**——
   每条记忆的来源应由场景决定。若标成 `third_party` / `user_document`，
   那条的 `memory_text` 必须说明来源（如"HR 系统同步的"、"会议纪要里写的"）
3. **不要写 `query == memory_text`**——那等于把答案当问题
4. **不要在 query 里写出 gold 的 value**

## 9. 交回来之后

我会检查结构要求（第 4 节）与两条硬规则（第 6 节），
**但不改你的内容**。若某项不满足，我只告诉你哪一条不满足，你自己改。

我也不会告诉你我的数据长什么样，或任何评测分数。
