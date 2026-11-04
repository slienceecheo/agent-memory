## Why

**三处小项，都是"改过但没人检查"的形态。**

**第一条：`HANDOFF.md:3` 的更新日期一直没更新。**

```
> 更新日期：2026-10-30
```

而九轮归档都改过 HANDOFF，今天是 `2026-11-04`。

**这条单看很小，但它是这份文档唯一的新鲜度标记**：下个会话的人靠它判断
"文档有多旧"，会得到"4 天前"而实际内容是今天改的。

**为什么之前没被发现**：没有任何测试断言它。

**第二条：`ACCEPTED_FAILURES["F24"]` 的范围只写了 billing。**

实测冻结文件：

| subject | `F24` 的 `passed` | detail |
|---|---|---|
| `v2-sample-gates.json` | **True** | 随机基线 0.3000，竞争集均值 3.40 |
| `v2-billing-gates.json` | **False** | 实测 SEH@1=9/9=1.0000——满分意味着测不到区分能力 |

所以"正确的失败：billing A 轴 SEH@1 = 1.0000"这一行**只对 billing 成立**，
而 `sample` 上它是**通过**。描述没写清范围。

**第三条：`openspec archive` 失败后的 lock 没有任何记录。**

实测：一次 archive 中途失败留下 `changes/archive/.openspec-archive.lock`，
而它**只在"想再次归档"时才暴露**：

| 检查 | 失败后的表现 |
|---|---|
| `openspec list` | **仍显示活动变更**（看起来像"还没归档"） |
| `openspec validate` | **通过**（活动变更本身有效） |
| 下一次 `archive` | **报错**，提示删 lock |

**唯一的信号出现在"你想再归档"时，而那时人已经不知道该不该删 lock。**

## What Changes

**1. `HANDOFF.md` 的更新日期改为 `2026-11-04`**

**2. 新增测试：更新日期必须等于最后一次归档日期**

```
更新日期 == max(openspec/changes/archive/ 下目录名的 YYYY-MM-DD 前缀)
```

**另一条防"未来日期"**：若有人写成 `2099-01-01` 让它永远通过，那条会红。

**3. `ACCEPTED_FAILURES["F24"]` 写全两个 subject**

```
"正确的失败：**billing** A 轴 SEH@1 = 1.0000（满分=测不到区分）；
 **sample 上是通过**（SEH@1 = 0.9000）"
```

**4. `HANDOFF` 的「环境与纪律」加一行 lock 说明**

**5. 不改 `test_accepted_failures.py` 的判据**

**这一条是更正上一轮的归类错误**：上一轮我把 `test_accepted_failures`
和 `test_handoff_current` 归为一类（都"用旧判据"），但实测：

```
v2-sample-gates.json   checks=27  含 applicable=False   键=[code, detail, passed, title]
v2-billing-gates.json  checks=27  含 applicable=False   键=[code, detail, passed, title]
```

**那份文件没有 `applicable` 字段**——它由 v2 装置产出，那时只有两态。
所以 `not c["passed"]` 在那份文件上**是正确的**。

## Impact

- 代码：**无**
- 测试：新增 `test_handoff_freshness.py`（2 条）；`test_accepted_failures.py` 只改描述
- 文档：`HANDOFF.md`（日期 + lock 说明）
- 数据 / 结果文件：**无**

## 验收

| # | 判据 | 可被违反的形式 |
|---|---|---|
| 1 | 更新日期 == 最后一次归档日期 | 归档改文档不改日期 -> 红 |
| 2 | 删掉一条真失败的编码 -> 测试红，且消息指向"日期过期" | —— |
| 3 | 日期写成未来 -> 红 | 防"写个未来日期让它一直通过" |
| 4 | `ACCEPTED_FAILURES["F24"]` 同时写 billing 与 sample | 只写一边会让读者以为两边都失败 |
| 5 | **冻结文件没有 `applicable`，判据不改成三态** | 改成三态会因 `KeyError` 崩 |

**验收 5 是上一轮归类错误的更正**：那份文件是两态格式，不该用三态判据读。
