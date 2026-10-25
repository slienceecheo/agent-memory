# 数据集 v2 样例：`project:ledger`

> 生成时间：2026-10-26（协议已冻结于 tag `dataset-v2-protocol`）
> 目的：在铺开到 15 个 subject 之前，用**一个最难的 subject** 验证 schema 可行。
> 复算：`uv run --no-sync python -m evals.tools.sample_pool_check`

## 交付物 1：memories（12 条）

| memory_id | relation | condition | branch_nature | 有 embedding |
|---|---|---|---|---|
| `ledger-oncall-1` | oncall_owner | 工作日白天 | natural | ✅ |
| `ledger-oncall-2` | oncall_owner | 夜间 | natural | ✅ |
| `ledger-oncall-3` | oncall_owner | 周末 | natural | ✅ |
| `ledger-oncall-4` | oncall_owner | 法定节假日 | natural | ✅ |
| `ledger-deploy-1` | deploy_target | 生产环境 | natural | ✅ |
| `ledger-deploy-2` | deploy_target | 本地开发 | natural | ✅ |
| `ledger-deploy-3` | deploy_target | 赶进度 | natural | ✅ |
| `ledger-style-1` | code_style | 重构 | natural | ✅ |
| `ledger-style-2` | code_style | 新功能 | natural | ✅ |
| `ledger-style-3` | code_style | 小项目 | natural | ✅ |
| `ledger-pkg-1` | package_manager | — | natural | ✅ |
| `ledger-test-1` | test_command | — | natural | ✅ |

**结构**：4 条 oncall 分支、3 条 deploy、3 条 code_style、2 条天然单值。

**`branch_nature` 全部是 `natural`（0% forced）**，满足协议 §3.4 的 ≤20% 门禁。
这不是凑出来的：值班人、部署目标、代码风格在真实项目里本来就有多分支，
而包管理器、测试命令只有一个。

### 一个刻意的取舍

`package_manager` 与 `test_command` **不编造条件分支**。
给"Wi-Fi 密码"编出"在家/在公司/在客户现场"是假数据，
会让 `condition_match` 看起来有效，实际只是记住了词表。

## 交付物 2：queries（12 条，标明 cue_type）

| query_id | axis | cue_type | 查询 | query_condition | gold |
|---|---|---|---|---|---|
| `q-oncall-night` | A | explicit | 夜间告警应该找谁？ | 夜间 | `ledger-oncall-2` |
| `q-oncall-weekend` | A | explicit | 周末出问题找谁？ | 周末 | `ledger-oncall-3` |
| `q-deploy-prod` | A | explicit | 生产环境部署到哪？ | 生产环境 | `ledger-deploy-1` |
| `q-style-refactor` | A | explicit | 重构的时候用什么风格？ | 重构 | `ledger-style-1` |
| `q-deploy-local` | A | explicit | 本地开发用哪个部署目标？ | 本地开发 | `ledger-deploy-2` |
| `q-style-feature` | A | explicit | 新功能的代码风格是什么？ | 新功能 | `ledger-style-2` |
| **`q-oncall-implicit-1`** | A | **implicit** | 半夜两点告警响了，该把谁叫起来看？ | 夜间 | `ledger-oncall-2` |
| **`q-oncall-implicit-2`** | A | **implicit** | 国庆期间系统挂了找谁？ | 法定节假日 | `ledger-oncall-4` |
| **`q-deploy-implicit`** | A | **implicit** | 这周要赶上线，直接发哪儿？ | 赶进度 | `ledger-deploy-3` |
| **`q-style-implicit`** | A | **implicit** | 代码太乱了，先整体拾掇一遍，用哪个工具？ | 重构 | `ledger-style-1` |
| `q-c-pkg` | C | explicit | 这个项目用什么包管理器？ | — | `ledger-pkg-1` |
| `q-c-test` | C | explicit | 测试跑什么命令？ | — | `ledger-test-1` |

**cue_type 分布：explicit 8 / implicit 4 = 33%。**

⚠️ **低于协议 §3.4 要求的 40%（F13）**，铺开时必须补到 ≥40%。
样例阶段记录在此，不修改——因为改样例就是在看着结果调数据。

### implicit 为什么是这一版的关键

如果 query 全部写成"开会的时候我几点到"，`condition_match` 直接命中，
测的是中英词表，不是检索。

`"半夜两点告警响了，该把谁叫起来看？"` 里的"夜间"要靠推断，
且**不含任何已登记的条件同义词**（L9）——这才是真实难度。

## 交付物 3：池大小与随机基线

```
池大小（同 subject 全部记忆）: 12
全池随机 SEH@5（期望）: 0.4225
全池随机 SEH@1（期望）: 0.0883
理论随机值 K/N:        0.417
```

实测与理论吻合（偏差 0.006），说明指标实现正确。

### 按轴拆分——这里暴露了一个必须记下的问题

| 轴 | 查询数 | 竞争集大小 | 随机 SEH@5 | 随机 SEH@1 |
|---|---|---|---|---|
| A | 10 | 3..4 | **1.000** ⚠️ | 0.289 |
| C | 2 | 12 | 0.405 | 0.098 |

**A 轴的 SEH@5 恒等于 1.000，因为分支数（3–4）小于 K（5）。**

这与 C4 缺陷 3 是同一个形态，只是换到了 A 轴：**SEH@5 在 A 轴上不是满分，是空操作。**

所以：

- **A 轴必须用 `SEH@1` 评估**（随机基线 0.289，有真实区分空间）
- **C 轴用 `SEH@5`**（随机基线 0.405）
- 混在一起报 `SEH@5` 会让 A 轴的饱和拉高整体数字，制造假象

这条要写进协议 §7：**不同轴用不同主指标，不许合并成一个数字。**

## 三样之外的一个自检

随机基线用"200 次中是否过半命中"来判定时，A 轴得到 0.000；
改用"期望命中率"后得到 0.289。

**前者是测量方法的错误**——用阈值判定会把 0.289 压成 0。
这与 C4 缺陷 2 同源：指标看起来正常，实际测的不是它声称的东西。

已修正为期望命中率，并加了"实测 vs 理论值偏差 > 0.05 即失败"的断言。

## 结论

| 检查 | 状态 |
|---|---|
| A 轴能进池、竞争集 ≥ 2 | ✅ 3–4 条 |
| L1（query ≠ gold.memory_text） | ✅ 12/12 |
| L6b（池内每条有 embedding） | ✅ 12/12 |
| 显式/隐含条件都有 | ✅ 8 / 4 |
| `branch_nature` 全 natural | ✅ 0% forced |
| 池不饱和（全池 SEH@5 < 1.0） | ✅ 0.4225 |
| **implicit 占比 ≥ 40%** | ❌ **33%** |

**七项里六项通过。implicit 占比不足是唯一未达标项**，
铺开时补到 ≥40% 即可，不需要改 schema。

## 铺开前需要确认的三件事

1. **A 轴指标改用 `SEH@1`** —— 这是协议修改，需要拍板
2. **implicit 提到 ≥40%** —— 铺开时执行
3. **C 轴查询从 2 条增加到至少 5 条** —— 当前样本里 C 轴太少

前两条影响协议，第三条只影响数据。
