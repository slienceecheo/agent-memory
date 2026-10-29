# v2 数据集：独立编写说明（交给第二位作者）

> 你写 5 个 subject，我写 15 个，**互不看**。
> 本文档只给你 schema、规模要求、填写示例，以及数据规则。
> **不含**我的任何数据、任何分数、任何通过率——知道了就会照着凑，独立性就没了。

## 0. 先看这一节：规模要求

**下面的示例是"字段示例"，规模远小于要求。** 先看规模，再看示例，
否则你会照着示例的尺寸写，而那是 4 条记忆 / 3 条查询的迷你数据集。

每个 subject 的合格形状（三条硬要求）：

| 项 | 要求 | 说明 |
|---|---|---|
| relation 数 | **2–3 个** | 少于 2 个无法产生跨 relation 的 C 轴竞争 |
| 每个多分支 relation 的分支数 | **3–5 个** | 这是 A 轴的全部难度来源 |
| **A 轴查询** | **= 各多分支的分支数之和**，且 **≥ 6 条** | 每个分支一条查询 |
| **C 轴查询** | **= relation 总数**（2–3 条） | 每个 relation 一条 |
| **implicit 占 A 轴** | **≥ 50%，且至少 5 条** | 见第 5 节 |

以最常见的形状（2 个多分支 × 3 分支 + 1 个单值）为例：

```
记忆：3 + 3 + 1 = 7 条
A 轴：6 条（每个分支一条）
C 轴：3 条（每个 relation 一条）
合计：9 条查询
```

**5 个 subject 合计约 35 条记忆、45 条查询。** 这是你的交付量。

> A 轴查询之所以要求 ≥6：`implicit ≥5` 且 `implicit ≤ A` 只能推出 `A ≥5`，
> 而 A=5 时 implicit 占满、explicit=0，而两条 `cue_type` 都必须有——
> 所以 A=5 本来就不合法，最小是 6。

## 1. 你要交什么

两份 JSONL 文件：

```
memories.jsonl   # 记忆库：一个 subject 的全部事实，含条件分支
queries.jsonl    # 查询：自然提问 + 它指向哪条记忆
```

规模：**5 个 subject**。每个 subject 按第 0 节。

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

## 4. 覆盖规则（会机器检查）

| 规则 | 具体含义 |
|---|---|
| **A 轴：每个分支一条** | 多分支 relation 的**每个** `condition` 分支，都必须是某条 A 轴查询的 gold |
| **C 轴：每个 relation 一条** | 每个 relation（含单值）都至少有一条 C 轴查询指向它 |
| **单值 relation 不做 A 轴** | 它只有一个值，A 轴竞争集只有 1 条，测不到东西。但它在 C 轴上**必须**被覆盖 |

注意两条的粒度不同：A 轴数"分支"，C 轴数"relation"。
同一个 relation 的 4 个分支在 C 轴上只占一个"属性位置"，写 4 条 C 轴不增加信息。

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

## 7. 填写示例

### 7.1 正例：最小合法 subject（7 条记忆 / 9 条查询）

**这个例子的规模符合第 0 节的下限**（2 个多分支 × 3 分支 + 1 个单值）。
它是 `project:docs-site`，一个与你我都不同的 domain。

```json
{"memory_id": "docs-deploy-1", "subject": "project:docs-site", "relation": "deploy_branch", "condition": "主站", "value": "main", "memory_text": "主站从 main 分支发布", "authority": "user_direct", "status": "ACTIVE", "branch_nature": "natural", "valid_from": "2026-01-01T00:00:00+00:00"}
{"memory_id": "docs-deploy-2", "subject": "project:docs-site", "relation": "deploy_branch", "condition": "预览站", "value": "gh-pages", "memory_text": "预览站走 gh-pages，每次 PR 自动更新", "authority": "user_direct", "status": "ACTIVE", "branch_nature": "natural", "valid_from": "2026-01-01T00:00:00+00:00"}
{"memory_id": "docs-deploy-3", "subject": "project:docs-site", "relation": "deploy_branch", "condition": "文档归档", "value": "release-assets", "memory_text": "旧版本文档发布到 release-assets，不再走分支", "authority": "user_document", "status": "ACTIVE", "branch_nature": "natural", "valid_from": "2026-01-01T00:00:00+00:00"}
{"memory_id": "docs-build-1", "subject": "project:docs-site", "relation": "build_engine", "condition": "本地", "value": "hugo serve", "memory_text": "本地起站用 hugo serve，改完自动刷新", "authority": "user_direct", "status": "ACTIVE", "branch_nature": "natural", "valid_from": "2026-01-01T00:00:00+00:00"}
{"memory_id": "docs-build-2", "subject": "project:docs-site", "relation": "build_engine", "condition": "CI", "value": "hugo --minify", "memory_text": "CI 里跑 hugo --minify，产物要压过再上传", "authority": "user_direct", "status": "ACTIVE", "branch_nature": "natural", "valid_from": "2026-01-01T00:00:00+00:00"}
{"memory_id": "docs-build-3", "subject": "project:docs-site", "relation": "build_engine", "condition": "离线包", "value": "hugo --offline", "memory_text": "给客户做离线包时加 --offline，别去拉外链字体", "authority": "user_document", "status": "ACTIVE", "branch_nature": "natural", "valid_from": "2026-01-01T00:00:00+00:00"}
{"memory_id": "docs-theme-1", "subject": "project:docs-site", "relation": "theme_repo", "condition": null, "value": "docsy", "memory_text": "主题用的是 docsy，别再换", "authority": "user_direct", "status": "ACTIVE", "branch_nature": "natural", "valid_from": "2026-01-01T00:00:00+00:00"}
```

```json
{"query_id": "docs-a1", "subject": "project:docs-site", "axis": "A", "cue_type": "explicit", "query": "主站从哪个分支发布？", "query_condition": "主站", "gold_memory_id": "docs-deploy-1", "expected_value": "main", "author": "independent"}
{"query_id": "docs-a2", "subject": "project:docs-site", "axis": "A", "cue_type": "implicit", "query": "提 PR 之后想先看效果，去哪儿看？", "query_condition": "预览站", "gold_memory_id": "docs-deploy-2", "expected_value": "gh-pages", "author": "independent"}
{"query_id": "docs-a3", "subject": "project:docs-site", "axis": "A", "cue_type": "implicit", "query": "想翻两年前的旧文档，还找得到吗？", "query_condition": "文档归档", "gold_memory_id": "docs-deploy-3", "expected_value": "release-assets", "author": "independent"}
{"query_id": "docs-a4", "subject": "project:docs-site", "axis": "A", "cue_type": "explicit", "query": "本地预览怎么起？", "query_condition": "本地", "gold_memory_id": "docs-build-1", "expected_value": "hugo serve", "author": "independent"}
{"query_id": "docs-a5", "subject": "project:docs-site", "axis": "A", "cue_type": "implicit", "query": "流水线里打包用哪个命令？", "query_condition": "CI", "gold_memory_id": "docs-build-2", "expected_value": "hugo --minify", "author": "independent"}
{"query_id": "docs-a6", "subject": "project:docs-site", "axis": "A", "cue_type": "implicit", "query": "要给客户一份不联网也能看的东西，怎么打？", "query_condition": "离线包", "gold_memory_id": "docs-build-3", "expected_value": "hugo --offline", "author": "independent"}
{"query_id": "docs-c1", "subject": "project:docs-site", "axis": "C", "cue_type": "explicit", "query": "发布分支是怎么安排的？", "gold_memory_id": "docs-deploy-1", "expected_value": "main", "author": "independent"}
{"query_id": "docs-c2", "subject": "project:docs-site", "axis": "C", "cue_type": "explicit", "query": "构建命令是什么？", "gold_memory_id": "docs-build-1", "expected_value": "hugo serve", "author": "independent"}
{"query_id": "docs-c3", "subject": "project:docs-site", "axis": "C", "cue_type": "explicit", "query": "这个站用的什么主题？", "gold_memory_id": "docs-theme-1", "expected_value": "docsy", "author": "independent"}
```

数一下：

```
memories: 7    relations: deploy_branch(3) / build_engine(3) / theme_repo(1) = 3 个 relation
A 轴: 6 条（3 + 3，每个分支一条），其中 implicit 4 条 = 67%
C 轴: 3 条（每个 relation 一条）
合计: 9 条查询
```

注意 `docs-a2` / `docs-a3` / `docs-a5` / `docs-a6`：它们**没有出现条件词**，
但语义指向某个分支——这才是 `implicit`。

### 7.2 反例：这些写法不合格

| 反例 | 违反什么 | 表现 |
|---|---|---|
| 3 个 relation 全是单值 | A 轴查询 = 0 | A 轴什么都不测 |
| 2 个多分支 × 3 分支，但 C 轴只写 1 条 | C 轴漏 1 个 relation | 那个 relation 在 C 轴上从未被考 |
| 4 个 relation | relation 数超上限 3 | 每个 subject 的 C 轴名额被摊薄 |
| 3 个分支只写 1 条 A 轴查询 | 2 个分支从未成为 gold | 池里有 3 条，只有 1 条被考 |
| A 轴 5 条、implicit 5 条 | explicit = 0 | 两条 `cue_type` 都必须有 |

**最后一条要特别注意**：`implicit ≥ 5` 不是"越多越好"，
它和"explicit 至少 1 条"同时成立，所以 A 轴最少 6 条。

## 8. 不要做的四件事

1. **不要为了凑分支数编造条件**——单值 relation 就保持单值
2. **不要为了让某个特征"有方差"而改 authority**——
   每条记忆的来源应由场景决定。若标成 `third_party` / `user_document`，
   那条的 `memory_text` 必须说明来源（如"HR 系统同步的"、"会议纪要里写的"）
3. **不要写 `query == memory_text`**——那等于把答案当问题
4. **不要在 query 里写出 gold 的 value**

## 9. 交回来之后

我会检查第 0 节的规模要求、第 4 节的覆盖规则、第 6 节的两条硬规则，
**但不改你的内容**。若某项不满足，我只告诉你哪一条不满足，你自己改。

我也不会告诉你我的数据长什么样，或任何评测分数。
