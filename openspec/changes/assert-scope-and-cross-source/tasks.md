# Tasks

## 0. 为什么要有这个变更

**两条 A 类断言不限定范围，会互相顶替。**

HANDOFF 里 `| **合计** | **N** |` 出现三次（MUST 表 214 / Scenario 表 287 / 要求数 55），
而两条断言都扫全文——**现在通过只因为 287 ≠ 214**。

**实测缺陷**（Scenario 真值 220 / 文档 219，MUST 真值 220 / 文档 220）：

```
test_scenario_count_is_real -> **通过**
```

**Scenario 表写错了，但断言因为 MUST 表的 220 而通过。**

## 1. 两条合计断言加 scope

- [x] 1.1 `test_scenario_count_is_real`
  - scope：`text.split("真正该看的数字：")[1].split("\n### ")[0]`
  - 验证：`pytest -k scenario_count_is_real`

- [x] 1.2 `test_must_coverage_numbers_are_real`
  - scope：`text.split("### 0.6 自动检查的边界")[1].split("### 0.7")[0]`
  - 验证：`pytest -k must_coverage_numbers_are_real`

- [x] 1.3 证伪（**必须构造数字相等的场景**）
  - Scenario 真值 220 / 文档 219；MUST 真值 220 / 文档 220
  - 修之前：**通过**（顶替）
  - 修之后：**红**（"**Scenario 那一节**的合计不是这个数"）
  - **已做**，两个方向都确认

  **注意前两次证伪失败的原因**（记下来防再踩）：
  1. 只把 Scenario 表改成 214，没让真值相等 -> 全文找不到 287 -> 必然红，**不是顶替**
  2. patch 了 `compute()` 但**文档的 MUST 表没同步改 220** -> 全文没有 220 -> 必然红

  **证伪"两个值互相顶替"必须让两个值真的相等**，而不只是让一个写错。

## 2. 交叉断言：`has_fn` 与 `MANUAL_SYMBOL_EXISTS_ROWS`

- [x] 2.1 新增 `test_three_layer_symbol_exists_matches_four_way`
  - 判据：`four_way.has_fn.n == three_layer.symbol_exists.numerator`
  - **两者定义是同一个量**（有函数名的行 = exists 能覆盖的行），
    但来源不同（扫描 vs 手写常量）
  - 验证：`pytest -k three_layer_symbol_exists_matches_four_way`

- [x] 2.2 证伪：让 `has_fn = 2`（模拟"spec 新增实现 foo，常量没改"）
  - 必须红，消息写"四类表算出 2 条「有函数名」，而三层表的常量写 1"
  - **已做**，按预期红

## 3. `test_recount_script_matches_reality` 去打印污染

- [x] 3.1 判据从 `main() == 0` 改为 `compute()` 返回非空
  - 加内部一致性：四类之和 == 总数
  - 验证：`pytest ...::test_recount_script_matches_reality -q -s`
  - **已做**：`-s` 下**无任何 stdout 输出**

## 4. 验收

- [x] 4.1 `openspec validate assert-scope-and-cross-source --strict` 通过
- [ ] 4.2 **归档前**跑 `openspec validate --all --strict`
- [ ] 4.3 全量测试通过
- [ ] 4.4 归档

## 5. 不在本变更范围

- **不合并 `has_fn` 与 `MANUAL_SYMBOL_EXISTS_ROWS`**：
  前者是扫描算出，后者是人工结论（"`substring_exact_match` 那一条 exists 有意义"）。
  数值现在相同但定义不同，合并会让"人工判断"伪装成"算出来的"
- **不做 v3 数据**
