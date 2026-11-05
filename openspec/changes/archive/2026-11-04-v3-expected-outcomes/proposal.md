## Why

**v3 数据造出来后，有 3 条门禁会验它，而它们红的含义不同——这个区分必须先写下来。**

如果只写"预期通过"，造完数据看到红色就分不清是装置坏了还是数据不好：

| 门禁 | 红的含义 | 该去查什么 |
|---|---|---|
| `F19b` | **数据问题**：某条 implicit 的 gold 真的没被召回 | 召回路径 / 查询措辞 |
| `F20` | **装置问题**：condition 又回到加权里了 | 排序代码（BREAKING 被回退） |
| `F24` | **数据难度问题**：太难或太简单 | 数据本身 |

## 一个被实测推翻的假设

被建议的分类是"前两条是结构必然，第三条由数据决定"。实测发现**这个二分是错的**：

### `F19b` 不是结构必然

构造：v3 签名（两轴逐条 rank 相同）+ 把 `ledger-q3` 的 `rank` 设为 `None`。

```
F19b: applicable=True passed=False
      1 条 implicit 从未被召回：['ledger-q3']
```

`F19b` 判的是"召回是否真的成功"，而**召回不依赖排序装置**——
这正是它被归为"照跑"的理由，也**恰恰是它不可能是结构必然的理由**。
它的通过与否完全由数据决定。

### `F20` 是结构必然，但有前提

```
构造 A：v3 签名 + drop=0     -> passed=True   "掉幅 +0.0000"
构造 B：v3 签名 + drop=0.5   -> passed=False  "掉幅 +0.5000 不为 0"
```

它的"必然"来自 `ablate()` 在 v3 下两次跑出相同 ranks，
**不是**来自"签名是 v3 所以判据自动通过"。手写一个矛盾的 `drop` 会被抓住。

**这个区别重要**：如果把"结构必然"理解成"签名对了就自动通过"，
那 `F20` 就退化成恒真断言——而它现在不是。

## What Changes

**1. 新增 `tests/retrieval/test_v3_expected_outcomes.py`（8 条断言）**

三档归因被写成可执行的事实：

```python
RED_ATTRIBUTION = {
    "F19b": "data",       # 召回失败
    "F20":  "apparatus",  # condition 又参与加权
    "F24":  "data",       # 难度不合适
}
```

**2. 每条归因都有行为级证据**

| 断言 | 用什么证明 |
|---|---|
| `test_f19b_is_data_dependent_not_structural` | 破坏一条 rank -> 必须红 |
| `test_f19b_does_not_judge_apparatus` | v2 产物也要照跑（applicable） |
| `test_f20_v3_zero_drop_is_structural` | v3 签名 + drop=0 -> 通过 |
| `test_f20_catches_contradictory_drop` | v3 签名 + drop=0.5 -> **红** |
| `test_f20_red_means_apparatus_regression` | 源码文案必须指向"condition 又参与了加权" |
| `test_f24_red_means_data_difficulty` | 源码文案必须含"太容易"/"基线" |
| `test_red_attribution_covers_exactly_the_v3_aware_gates` | 归因表 == AST 派生能看到 v3 的门禁 |
| `test_only_f20_is_attributed_to_apparatus` | 只有 F20 归因到装置 |

**3. 归因表与"谁能看到 v3"是两张表**

| 断言 | 判什么 |
|---|---|
| `test_v3_aware_gates_are_exactly_three`（已有） | **发现方式**：哪些门禁看得到 v3 |
| `test_red_attribution_covers_exactly_the_v3_aware_gates`（新增） | **归因**：它们红了各自意味着什么 |

两条都依赖同一个集合，但验的是不同的事。分开写之后，改一处不会让另一处静默失效。

## Impact

- 代码：**无**
- 测试：新增 `test_v3_expected_outcomes.py`
- 文档：本 proposal 本身就是"预期结果表"的说明
- 数据 / 结果文件：**无**

## 验收

| # | 判据 | 可被违反的形式 |
|---|---|---|
| 1 | v3 签名 + 某条 implicit 的 rank=None | `F19b` **必须红**且点名那条 |
| 2 | v2 签名产物 | `F19b` **必须 applicable**（照跑） |
| 3 | v3 签名 + drop=0 | `F20` **必须通过**，detail 含 `+0.0000` |
| 4 | v3 签名 + drop=0.5 | `F20` **必须红**，detail 含 `0.5000` |
| 5 | 把 `F19b` 归因改成 `apparatus` | 断言**必须红** |
| 6 | 归因表漏掉 `F24` | 断言**必须红** |
| 7 | `F19b` 改成恒通过 | 断言**必须红** |
| 8 | `F20` 改成只看签名 | 断言**必须红** |

**验收 3 与 4 是一对**：前者说"结构必然"，后者说"必然不等于恒真"。
只写 3 会让人以为 `F20` 不读 drop；只写 4 会让人以为 `F20` 在 v3 下永远红。
