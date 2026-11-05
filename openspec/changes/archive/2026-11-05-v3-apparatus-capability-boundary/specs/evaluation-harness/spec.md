## ADDED Requirements

### Requirement: v3 排序特征的能力边界必须可复算

v3 的三个排序特征（`base` / `authority` / `status`）各自"能提供什么信号"
MUST 被写成可执行的断言，MUST NOT 只写在报告或注释里。

**实测边界**（v2 数据，v3 装置）：

| 特征 | 性质 | 判据 |
|---|---|---|
| `status` | 恒为常数 | 池内方差 == 0 |
| `base` | 等于融合顺序 | `rrf_norm` 严格单调 |
| `authority` | 分层过滤器 | 同层逆序 == 0 |

#### Scenario: status 在候选池内必须有方差，否则必须登记它恒为常数

- **WHEN** 检查 `status` 特征
- **THEN** MUST 断言"池内方差 == 0"这个事实，或断言它有方差
- **AND** 声明"恒为常数"时 MUST 同时指出它占的权重是空的

**实测**：

```
记忆库的 status 取值：sample {'ACTIVE'}  billing {'ACTIVE'}
候选池内 status 有方差：0/10、0/12
uniform 里 status 权重 0.3 -> 净效为空
```

**为什么不直接删掉这个权重**：删权重是装置变更（HARKing 风险），
登记"它现在是空的"是事实陈述。两者不同。

#### Scenario: base 必须被证明等价于融合顺序

- **WHEN** 用 `base` 作为排序特征
- **THEN** MUST 断言 `rrf_norm` 严格单调
- **AND** 由此得出"按 base 排序 == 按融合顺序排序"

**实测**：

```
输入 [0.0, 0.1, 0.5, 1.0, 2.0, 5.0]
输出 [0.0, 0.02, 0.1, 0.2, 0.4, 1.0]   严格递增
```

**为什么这条重要**：它把"base-only 的 ratio = 0.20"从
"base 是负贡献"纠正为"融合顺序本身的 top-1 率"。
前者会让人以为"去掉 base 更好"，而剥掉 base 等于剥掉裁决规则本身。

#### Scenario: authority 必须是过滤器，不是信号

- **WHEN** 只在 authority 上排序（base=0, status=0）
- **THEN** MUST 断言"同一 authority 层内部，相对顺序与融合顺序完全一致"
- **AND** MUST NOT 把 auth-only 的增益解释为"authority 选中了 gold"

**实测**：22 个 case（sample 10 + billing 12），**同层逆序 0 个**。

**这意味着**：authority 的全部作用是**把低 authority 的项推到高层之后**，
层内裁决仍由融合顺序完成。

**若同层逆序 > 0**：说明 authority 内部还有额外信号（比如浮点精度差异），
那时"过滤器"这个结论要重核。

### Requirement: 数据侧 MUST NOT 制造 authority 与 gold 的相关性

v3 数据 MUST NOT 为了提高排序增益而让 `authority` 与 gold 相关。
该禁止 MUST 有断言守着。

**为什么这是最重要的一条**：它是"为达标造数据"的新形态——
不是改分数，而是**改数据结构让某个特征变得决定性**。

#### Scenario: gold 不得是唯一的最高 authority

- **WHEN** 检查任意 subject 的任意 case
- **THEN** "gold 的 authority 严格高于池内所有其他项"的 case 数 MUST 为 0

**实测 v2**：`sample 0/10`、`billing 0/12`。

**为什么它是泄漏**：若 gold 唯一最高，auth-only 直接 = 1.0，
任务退化成"选权威最高的那个"，一个特征解决全部。

#### Scenario: gold 与干扰项的平均 authority 不得有系统差

- **WHEN** 计算 `mean(authority of gold)` 与 `mean(authority of distractors)`
- **THEN** 两者之差 MUST 满足 `|差| < 0.05`

**实测 v2**：

| subject | gold mean | distractor mean | 差 |
|---|---|---|---|
| `sample` | 0.8660 | 0.8904 | **−0.0244** |
| `billing` | 0.9433 | 0.9221 | **+0.0213** |

两个都在阈值内。**sample 上 gold 甚至更低**——它不是靠权威赢的。

#### Scenario: 这条禁止必须可被违反

- **WHEN** 构造一份数据，让 gold 的 authority 是池内唯一最高
- **THEN** 上述两条断言 MUST 红

**为什么需要**：否则"不得制造相关性"只是一句话。
证伪的具体形式见 tasks.md §4。

#### Scenario: v3 的 authority 与 v2 的 condition 处在同一个位置

- **WHEN** 设计 v3 数据
- **THEN** MUST NOT 让 `authority` 成为"与 gold 同向的元数据先验"

**v3 的 `authority` 与 v2 的 `condition` 是同一位置上的同一个东西**：
一个与 gold 同向的元数据先验。

| 装置 | 先验 | 后果 |
|---|---|---|
| v2 | `condition` 匹配 | 几乎自动第 1，实测 `SEH@1 = 1.0000` |
| v3（若按"让 authority 有区分度"造数据） | `authority` 更高 | 同样会退化成单特征决定 |

**区别在于可发现性**：`condition` 是显式的查询条件，
而 `authority` 看起来像"合理的排序信号"——**因此更难发现**。

**所以这条禁止必须写成断言**，而不是"注意不要"。
