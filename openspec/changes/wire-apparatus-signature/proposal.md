## Why

**上一轮交付的 `apparatus_signature` 写完了，但没有任何使用点真正用它。**

AST 扫描实测：

```
定义：check_v2_dataset.py:114
调用：check_v2_dataset.py:982（唯一一处，在 _ablation_for_subjects 里）
```

两处使用它的门禁都丢弃了返回值：

```python
# F19b（正确：判据不依赖装置，不需要签名）
payload, source, _ = _ablation_for_subjects(dataset)

# F20（错误：需要签名，却用了常量）
payload, source, _ = _ablation_for_subjects(dataset)   # <- 当时写的是 _
```

而真正决定"是否不适用"的是：

```python
CURRENT_APPARATUS = "v3"
if CURRENT_APPARATUS == "v3":        # F20，恒真
if CURRENT_APPARATUS == "v3":        # F24，恒真
```

`CURRENT_APPARATUS` 是常量，所以这两个条件**永远成立**。

**后果**：v3 数据造出来后，`results/v3/*.json` 的签名是 `v3`，
但 `F20`/`F24` 仍然无条件返回"不适用"——**v3 数据上它们永远不跑。**
这正是本变更要避免的"门禁静默变不适用"，只是触发条件从"签名判错"
变成了"常量短路"。

**这与本仓库已登记的多个形态同型**：

| 形态 | 恒真原因 |
|---|---|
| `archived & active` | 归档名带日期前缀，活动名不带 |
| `assert "1.2%" in section` | 同节有两个 1.2%，分母不同 |
| **`CURRENT_APPARATUS == "v3"`** | **常量恒等于 v3** |

## What Changes

**把"当前是哪一代"与"这份文件属不属于它"分开：**

| 问题 | 由什么回答 |
|---|---|
| 当前代码是哪一代装置？ | `CURRENT_APPARATUS` 常量（**保留**） |
| 这份文件能不能回答当前装置的问题？ | `CURRENT_APPARATUS != signature` 的比较 |

```python
if CURRENT_APPARATUS != signature:
    return _not_applicable(...)   # 跨装置
# 同装置 -> 执行判据
```

| 文件签名 | 当前装置 | 结果 |
|---|---|---|
| v2 | v3 | 不适用 |
| v3 | v3 | **执行** |
| v2 | v2 | 执行 |
| unknown | v3 | 不适用（无法确认，保守） |

**`CURRENT_APPARATUS` 保留，理由成立**：产物的签名回答"这东西是谁产的"，
不能用来推"当前代码是哪一代"。但它只回答前半句——后半句必须靠比较。

## `F20` 在 v3 下的判据变了，不是"永久关闭"

**旧实现**：v3 -> 不适用。这等于放弃一条断言。

**新实现**：v3 下执行，并断言 **`drop == 0`**。

理由：`condition` 退出加权后，"消融是否改变名次"这个测量**仍然有意义**——
它应该恒为 0，而"恒为 0"本身是可断言的结论。

| 装置 | 判据 | 违反形式 |
|---|---|---|
| v2 | `drop >= 阈值` | 条件没贡献 |
| **v3** | **`drop == 0`** | **`condition` 又回到了加权里** |

实测 v3 下 `drop = 0.0000`（with/without 逐条名次相同），所以新判据当前通过。
若有人回退 BREAKING，它会红——这是旧实现（永久不适用）抓不到的。

**`F24` 保持"不适用"**：它的阈值语义确实随装置反转（v2 满分=饱和、v3 低分=退化），
而 v3 版本的新判据（如"不得低于随机基线"）需要 v3 数据才能定，不在本变更范围。

## Impact

- 代码：`evals/tools/check_v2_dataset.py`（`F20` 的两处分支、`F24` 的比较）
- 测试：`test_gate_apparatus_binding.py` 新增 2 条（签名必须被读、v3 下 drop 必须为 0）；
  `test_current_apparatus_is_v3` 改为比较"常量 vs 现实"
- 数据 / 结果文件：**无**
- **`run_all()` 数字不变**：`sample 19/27`、`billing 23/27`
  （`F20`/`F24` 仍不适用，但**理由从"v3 装置"变成"v2 产物 + 当前 v3"**）

## 验收

| # | 判据 | 可被违反的形式 |
|---|---|---|
| 1 | 同装置文件（v3 签名 + 当前 v3） | `F20` **执行**并断言 drop==0 |
| 2 | 跨装置文件（v2 签名 + 当前 v3） | `F20` 不适用 |
| 3 | v3 下 `drop != 0` | `F20` 必须**红**（BREAKING 被回退） |
| 4 | **常量必须与现实一致** | `CURRENT_APPARATUS == apparatus_signature(evaluate() 的产物)` |
| 5 | 反向证伪 | 把 `F20` 改回"只看常量"，验收 1 必须红（已证伪） |

**验收 5 是关键**：验收 1-4 都能通过而 `apparatus_signature` 仍未接进判断——
上一轮就是这样。必须有一条测试在"退回只比常量"时变红。
