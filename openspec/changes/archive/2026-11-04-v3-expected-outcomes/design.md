## 决策 1：归因分三档，不是两档

被建议的分类是"前两条结构必然，第三条由数据决定"。实测后改成：

| 门禁 | 依赖什么 | 归因 |
|---|---|---|
| `F19b` | **数据**（召回是否成功） | `data` |
| `F20` | **装置**（condition 是否加权） | `apparatus` |
| `F24` | **数据难度**（派生 within 的 SEH@1） | `data` |

**为什么 `F19b` 不是 `apparatus`**：它确实读 v3 产物，但**召回不依赖排序装置**。
`condition` 退出加权只影响重排，不影响三路召回返回什么。
所以它的红与装置无关，只说明某些 gold 真的没被召回。

**这个错误的代价**：如果 `F19b` 被归成 `apparatus`，造完数据看到它红，
人会去查排序代码——而真正该改的是数据。

## 决策 2：归因表与发现方式表分开

```python
# test_result_side_gates.py —— 发现方式
FIXED_PATH_GATES      = {"L6a", "L6b", "L6c", "L8"}
DISCOVERED_GATES      = {"F19b", "F20", "F24"}

# test_v3_expected_outcomes.py —— 归因
RED_ATTRIBUTION = {"F19b": "data", "F20": "apparatus", "F24": "data"}
```

两张表的**集合必须相同**（`test_red_attribution_covers_exactly_the_v3_aware_gates`
断言这一点），但它们**验的是不同的事**：

| 表 | 判什么 | 改错时红在哪 |
|---|---|---|
| 发现方式 | 哪些门禁看得到 v3 | `test_v3_aware_gates_are_exactly_three` |
| 归因 | 红了各自意味着什么 | `test_only_f20_is_attributed_to_apparatus` |

**为什么不合并成一张表**：合并后"新增一条看到 v3 的门禁"会同时改动两件事，
而断言只能覆盖其一。分开后两处各自会红。

**集合相同的断言仍然需要**：否则新增门禁时只更新发现方式表，
归因表静默缺失——那正是"两张表漂移"的形态。

## 决策 3："结构必然"必须有一个反例证明它不是恒真

`F20` 在 v3 下期望 drop == 0。这句话有三种可能的实现：

| 实现 | drop=0.5 时的行为 | 是否合格 |
|---|---|---|
| 只看签名是 v3 就通过 | **通过** | ❌ 恒真断言 |
| 读 drop 字段，要求 abs < 1e-9 | 红 | ✅ |
| 重跑两次评测比较 ranks | 红（但太重） | ✅ 但不需要 |

现在实现是第二种。`test_f20_catches_contradictory_drop` 锁住它：

```python
payload = _v3_ablation(drop=0.5)   # v3 签名 + 矛盾 drop
check = check_f20_condition_contributes(ds)
assert not check.passed            # 必须红
assert "0.5000" in check.detail
```

**没有这条断言的话**，有人把 `ok = abs(drop) < 1e-9` 改成 `ok = (signature == CURRENT_APPARATUS)`
也能让所有测试通过——因为正常产物里 drop 本来就是 0。

## 决策 4：归因要写进 detail

`F20` 在 v3 下掉幅不为 0 时的 detail：

```python
f"v3 下掉幅 {drop:+.4f} 不为 0——"
"说明 condition 又参与了加权（BREAKING 被回退）"
```

这条文案被 `test_f20_red_means_apparatus_regression` 断言（读源码文本）。

**为什么断言源码文本而不是行为**：这条断言的对象就是"文案指向哪里"。
行为已由 `test_f20_catches_contradictory_drop` 覆盖，两者不重复。

**局限**：读源码文本的断言比较脆（改措辞会红）。
但它防的是"归因指向变模糊"——比如把"condition 又参与了加权"改成
"掉幅不为 0"，那时人会去查数据。

## 关于 `F24` 的两个方向

`F24` 在 v3 下的判据是 `baseline < ratio < 0.9999`：

| 方向 | 含义 | detail 关键词 |
|---|---|---|
| `ratio <= baseline` | 排序比随机差 | "基线" |
| `ratio >= ceiling` | 数据太容易 | "太容易" |

**两个方向的红归因相同**（都是数据），但**处置不同**：
前者要查排序是否真的生效，后者要加难度。所以 detail 必须区分。

## Risks / Trade-offs

| 风险 | 缓解 |
|---|---|
| 归因表与发现方式表漂移 | `test_red_attribution_covers_exactly_the_v3_aware_gates` 断言集合相等 |
| 源码文案断言太脆 | 它只断言关键词，不断言整句 |
| `F19b` 的"依赖数据"结论可能随数据变化 | 断言的是"破坏 rank 会红"这个机制，不是具体数据 |

## 不做的事

- **不造 v3 数据**
- **不改任何门禁的判据**
- **不重跑评测**（`F20` 的"必然"论证基于 `ablate()` 的代码结构，不是新跑的实验）
