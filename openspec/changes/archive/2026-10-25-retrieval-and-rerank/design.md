# Design: 三路召回与 fitness-for-use 重排

动机见 `proposal.md`，行为契约见 `specs/memory-retrieval/spec.md`。

## Context

C3 的独立场景集给出两个事实：自写 100% / 独立 50.0%；原作者标"不太确定"的
5 条系统全错。15 条错误里 9 条是"语义等价或互补，字面零重叠"。

C2 的 `items_fts` 与 `vec_items` 从未被读过。`search_text()` 按 `version DESC`
排序、只索引 `subject + relation + value`、**不含原文**。

**独立审查发现此前的 C4 设计有六个致命缺陷，全部经实测核实，因此重写。**

## Goals / Non-Goals

**Goals**

- 让检索**可被测量**：有 query、有 gold、有真实排名空间
- 三路召回与四个重排特征的贡献**可单独消融**
- 用预注册权重避免在 40 条 dev 上选出噪声

**Non-Goals**

- 不做答案生成（C5）
- 不做 ANN
- **不改 C3 写路径**：本变更不会让 C3 的 50% 上升
- 不做多跳查询：场景集里没有

## Decisions

### D1. 先补因变量，再谈召回

审查发现三份场景文件只有 `expected`（判定类别），**没有 `query`，也没有
`gold_item_id`**。没有 gold 时 SEH@K 与 SRS 根本无定义。

**做法**：新增 `evals/tools/annotate_retrieval.py`，为每条场景补两个字段：

- `query`：由 `text` 派生（保留原话语，不拼入 gold 的值）
- `gold_item_id`：指向该场景的 `existing_value` 所对应的条目；
  ADD 类（`existing_value is None`）为 `null`

**为什么 query 用 text 而不是 `subject + relation`**：后者包含查找键甚至答案，
词面召回会接近 100%，等于自证。用原话语才能测出"能否从自然表达找到记忆"。

**ADD 类单独计数**：4 条 independent、7 条 dev、3 条 test 没有 gold。
它们不计入召回指标，但数量必须报出来，否则样本量会被静默改变。

### D2. 候选池必须大于 K

审查实测：现有评测每条场景只建 1 条既有条目，排名恒为 1，SRS 恒为 1.0，
SEH@5 = "唯一那条回来了吗"。

**做法**：每条场景构建 `1 + N` 候选（N=20）。干扰项从其他场景的
`existing_value` 采样，且**逻辑键互不相同**——审查实测跨文件合并会有
17 个键重复（`project:agent-memory/package_manager` 出现 12 次），
直接建库必撞 `ux_active`。

**池大小必须 > K**，否则 `pipeline` 直接报错，而不是给出虚高的 SEH。

### D3. 词面召回要按 BM25，且必须索引原文

审查指出两处：

1. `search_text` 按 `i.version DESC` 排序，`version` 是键内序号，
   跨键无序 → RRF 拿到的是噪声
2. `_write_fts` 只索引 `subject + relation + value`，**原文不在索引里**

第 2 条更致命：C3 暴露的正是"原文与存储值零重叠"
（`"靠窗那一排"` vs `"C区第三排左数第二个工位"`），
不索引原文的话，词面召回对这个差距**结构性失明**。

**做法**：
- `MemoryItem` 增加 `text`（可空，兼容旧数据）
- `items_fts` 索引 `subject + relation + value + text`
- `search_text` 改 `ORDER BY bm25(items_fts)`

**代价**：需要迁移。旧条目 `text` 为空，仍可被结构字段召回。
迁移脚本只补 `text`，不重建 FTS（`items_fts` 是虚拟表，需重建；
脚本会 DROP 后重建并重新灌入）。

### D4. 重排只保留四个有方差的特征

审查实测：五个特征里**四个在 ACTIVE-only 候选集上是常数**。

| 原特征 | 问题 |
|---|---|
| `temporal_validity` | 所有召回路径只返回 ACTIVE，恒为 1.0 |
| `recency` | 场景文件无时间字段，harness 全部用同一个 `BASE_TIME` |
| `source_authority` | 34/40 dev、17/20 test 缺失，默认值相同 |
| `condition_match` | 只有 14/90 条有条件 |
| `relevance` | **从未定义**；若等于归一化 RRF，则"全关"与"只开 relevance"排序相同 |

**做法**：改成显式的基础项 + 三个特征：

```
final = w_base·rrf_norm + w_cond·condition_match
      + w_auth·authority_score + w_status·status_score
```

- `rrf_norm`：RRF 分数按最大值归一化到 [0,1]
- 去掉 `temporal_validity` 与 `recency`（在 ACTIVE-only 上无方差）
- 四个权重和为 1；**全关时退化为 `rrf_norm` 排序**，并跳过权重校验

**每个特征必须有测试断言取值落在 [0,1]**：审查指出未限定值域时，
`recorded_at` 这类大数会压过任何 [0,1] 的权重，权重搜索失去意义。

### D5. 条件匹配需要写入侧与查询侧共用词表

审查指出两个方向性问题：

1. **词表不匹配**：dev/test 用英文 token（`coding`、`prod`），
   independent 用中文（`法定节假日`、`客户应酬`），
   而原设计只列了中文示例 → 大多数条件 `structured=False`，
   全部拿中性 0.5，特征失效
2. **方向反了**：BRANCH 场景需要看到的是**另一个条件**的兄弟条目，
   而 `condition_match` 奖励**同条件**的候选，会把 gold 排到最后

**做法**：
- 词表**中英双向**：`{"coding": ..., "写代码": ...}` 归一到同一组规范键
- 写入侧也做归一（存 `condition_slots`），不只是查询侧
- `condition_match` 只在**非 BRANCH** 查询上作为加分项；
  BRANCH 场景的 gold 判定改为"兄弟条目是否在候选中"（由 `adjacency` 负责）

**E6 的 gold 要按用途分别定义**，不能笼统说"正确的那条"。

### D6. 语义等价必须有消费者

审查指出：原设计实现了 `equivalence.py` 但**没有任何地方调用它**，
所以它不可能改变任何被测量的结果。E5 只是在 9 条手写对上测分类器。

**做法**：把它作为**去重阶段**接入，且有独立开关：

```
召回 → 融合 → [等义去重] → 重排 → 截断
```

去重规则：把 top-K 内的候选两两比对，若判为"等义"则只保留融合分更高的那条。
**可观测的产出**：去重前后的候选数变化（E8）。

**代价**：每对一次调用。只对 top-K 做（K=5 → 最多 10 对），且全量缓存。

### D7. 三分类而不是二分类

`等义 / 互补 / 无关`。理由：C3 的 9 条错误里 6 条是 MERGE（互补）、
3 条是 NOOP（等义）。二分类会把它们混在一起，无法回答"各修好几条"。

**E7 必须分类别报告**：审查实测，一个恒输出"互补"的分类器能拿到 6/9，
恰好等于原阈值。所以要求 MERGE 类 ≥5/6 **且** NOOP 类 ≥2/3，分别报告。

### D8. 预注册权重而不是网格搜索

审查实测：5 个特征、步长 0.1、和为 1 有 1001 组；在 40 条 dev 上取 argmax
必然选噪声。且指标是离散的，大量权重向量诱导相同排序，argmax 是个大的并列集。

**做法**：预注册 5 组，全部在三个集上报告：

| 名称 | 含义 |
|---|---|
| `uniform` | 四项均等（0.25 各） |
| `base_heavy` | 融合分主导（0.7 / 0.1 / 0.1 / 0.1） |
| `cond_heavy` | 条件主导（0.2 / 0.6 / 0.1 / 0.1） |
| `auth_heavy` | 权威主导（0.2 / 0.1 / 0.6 / 0.1） |
| `status_only` | 只用状态惩罚（0.2 / 0.1 / 0.1 / 0.6） |

**报告最小可检测效应**：test 集 20 条、二元 SEH@5 时，
单比例 95% CI 半宽约 22pp；配对差异需要约 6 个方向一致的 discordant pair。
**小于这个量级的差异一律不宣称**。

### D9. 归因只统计检索失败，三类而非四类

审查指出原四类会重叠且有一类恒空：

- "未召回"与"冲突未识别"都会在 gold 缺失 + 存在冲突兄弟时触发
- "下游错误"在本变更里恒为空（本变更不产答案）

**做法**：只统计检索失败，三类且有序：

```
1. 池构建失败   gold 不在候选池
2. 排序过低     gold 在池中但融合后排名 > K
3. 重排丢弃     gold 在融合后前 K，但被重排挤出前 K
```

**必须保留未截断的融合列表**，否则第 2 类不可观测。
C3 的判定错误**不复用**到这四类里——它们是写路径的问题。

### D10. 邻接只做条件兄弟，不做跨关系

审查指出：原设计"同主体下其他关系"这条路径**永远召不回 gold**
（gold 就是查询命中那条自身，被显式排除），且场景集里没有多跳查询。

**做法**：邻接只做"同逻辑键、不同 condition"的兄弟。
这是 BRANCH 场景的 gold 唯一可能被召回的路径。
跨关系扩展记为 `disabled` 并从默认融合中移除。

## Risks / Trade-offs

| 风险 | 应对 |
|---|---|
| 给 90 条场景补 query/gold 有主观性 | query 直接取 `text`（原文），不做改写；gold 由 `existing_value` 的写入顺序唯一确定 |
| 迁移 FTS 需 DROP 重建 | 脚本先备份 `items`，重建后校验条目数与可检索性 |
| 干扰项来自其他场景，可能语义相关 | 采样时排除与 gold 同 subject 的条目；报告干扰项池大小 |
| 语义等价调用量大 | 只对 top-K 的 10 对做；报告调用次数与缓存命中率 |
| 20 条 test 的统计效力低 | 报告最小可检测效应；不宣称小于该量级的差异 |
| 删掉 temporal/recency 后显得特征少 | 这是**诚实**：在 ACTIVE-only 上它们没有方差，留着只会制造假象 |

## Migration Plan

1. `annotate_retrieval.py` 为三份场景补 `query` / `gold_item_id`
2. `MemoryItem.text` 加字段（可空）
3. `items_fts` DROP 并重建，索引进 `text`
4. `backfill_text.py` 为旧条目补 `text`（从场景文件反查）
5. 校验：条目数不变、词面检索能命中原文

回滚：`items_fts` 重建是无损的（可从 `items` 重新灌入）；
`text` 字段可空，删列不影响既有查询。

## Open Questions

- 语义等价要不要 few-shot？**先用零样本**，若 E7 未达标再加。
  用数据决定，不靠直觉。
