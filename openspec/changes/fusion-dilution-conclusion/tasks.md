# Tasks

## 0. 为什么要有这个变更

**先写这条结论，因为它是 v3 数据造出来后的归因前提。**

若不知道"三路融合本身就让 top-1 低于 lexical 单路"，
v3 低分无法归因：

| 原因 | 处置 |
|---|---|
| 装置（三个特征无语义信号） | 装置变更 |
| **融合稀释**（vector 长尾挤出 lexical 头部） | 检索层变更 |

## 1. 修正分母口径

- [x] 1.1 发现"0.8333 (5/6) vs 0.3000 (3/10)"**分母不同，不能相减**
  - 这是"两个 1.2%"的同一形态
  - 前者只算已召回，后者算全部

- [x] 1.2 改为配对比较（两者都召回的 case）

  | subject | 配对 n | lexical | 三路 | 差 |
  |---|---|---|---|---|
  | `sample` | 6 | **5/6 = 0.8333** | **3/6 = 0.5000** | **+0.3333** |
  | `billing` | 9 | **8/9 = 0.8889** | **1/9 = 0.1111** | **+0.7778** |

- [x] 1.3 三个分母全部记录

  | 分母 | sample lex | sample 三路 | billing lex | billing 三路 |
  |---|---|---|---|---|
  | 全部派生 within | 5/10 | 3/10 | 8/12 | 1/12 |
  | 已召回 | 5/6 | 3/10 | 8/9 | 1/12 |
  | **配对** | **5/6** | **3/6** | **8/9** | **1/9** |

## 2. 报告新增 §6（结论 5）

- [x] 2.1 §6.1 配对比较（含"为什么不能直接相减"）
- [x] 2.2 §6.2 三个分母分开报
- [x] 2.3 §6.3 原因：`lexical=41 / vector=462 / adjacency=13`
- [x] 2.4 §6.4 独立证据：`three-way-recall.md` 的 `0.9091 → 0.8182 → 0.6667`
- [x] 2.5 §6.5 限定：召回变好、精度变差
- [x] 2.6 §6.6 复算命令
- [x] 2.7 原 §6/7/8 顺延为 §7/8/9；§1 的"四条"改"五条"

## 3. 新增 `tests/retrieval/test_fusion_dilution.py`（6 条）

- [x] 3.1 `test_paired_comparison_matches_report`（计数 == 报告）
- [x] 3.2 `test_fusion_dilution_direction_holds`（lexical 严格更高）
- [x] 3.3 `test_multi_path_improves_recall`（**配对限定：三路召回更好**）
- [x] 3.4 `test_all_three_denominators_are_reported`
- [x] 3.5 `test_report_states_the_three_denominators`
- [x] 3.6 `test_report_marks_fusion_dilution_not_multi_path_harm`

- [x] 3.7 **修正文档断言的判据**
  - 第一版用 `"配对" in section` -> 抽掉表格行后**仍然通过**
  - 原因：`"配对"` 在 §6 里出现 8 次
  - 改成解析表格首列，匹配完整单元格

## 4. 双向证伪（6 个方向全部符合预期）

| # | 构造 | 期望 | 实测 |
|---|---|---|---|
| A | `EXPECTED` 的 `lexical_hit` 5 -> 4 | 红 | 红（"配对比较与报告不符"） |
| A2 | 恢复 | 绿 | 绿 |
| B | 方向反转（lexical < 三路） | 红 | 红（"不高于三路——结论 5 不成立"） |
| B2 | 三路召回 == lexical 召回 | 红 | 红（"后半句不再成立"） |
| C | 抽掉表格里「配对」那一行 | 红 | 红（"缺少分母行「配对（都召回）」"） |
| D | 抽掉"不是多路召回有害" | 红 | 红（"缺少限定"） |

**B2 是关键的反向验证**：若三路召回没有更好，
"提高召回但降低精度"这个完整表述就只剩后半句。

## 5. 关于"加第四特征（cosine）"：不做

- [x] 5.1 核实 cosine 分在产物里的状态

  ```
  a3-lexical-vector-adjacency.json   features_by_tag 为空
  v2-billing-lexical-vector-adjacency.json   features_by_tag 为空
  含 cos/similar 的字段：无
  ```

  **任何产物都没有 cosine 分**，`pool_vectors` 是计数，`pool_vector_denorms` 是范数。
  所以"cosine 是最强特征"这类数字**无法从冻结产物复算**。

- [x] 5.2 结论：**不做**
  - 上限被 lexical 单路锁住（0.83 / 0.89）
  - cosine 只能追平，不能超越
  - 且它是装置变更，需要单独变更

## 6. 验收

- [x] 6.1 `openspec validate fusion-dilution-conclusion --strict` 通过
- [ ] 6.2 **归档前**跑 `openspec validate --all --strict`
- [ ] 6.3 全量测试通过
- [ ] 6.4 归档

## 7. 不在本变更范围

- **不改融合算法**：改了之后这条基线就没了
- **不加第四特征**：见 §5
- **不造 v3 数据**
- **不新增 results 文件**（顶层保持 48 个）
