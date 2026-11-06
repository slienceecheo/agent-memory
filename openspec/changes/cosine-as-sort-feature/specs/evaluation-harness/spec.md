## MODIFIED Requirements

### Requirement: 结果文件记录逐条特征分

检索评测的结果文件 MUST 为每条 case 记录三个排序特征：`base`、`authority`、`cosine`，置于 `features` 子对象。

`condition` MUST 单独记录在 `condition_score` 字段（数值或 `null`），不得放进 `features`。
`status` MUST NOT 出现在 `features` 里：它在候选池内恒为常数，不构成可审计的内容。

#### Scenario: 每条 case 的 features 含三个键

- **WHEN** 一次评测产生 N 条 case
- **THEN** 每条 case 的 `features` 恰好含 `base` / `authority` / `cosine` 三个数值字段

#### Scenario: condition_score 独立记录

- **WHEN** 一次评测产生 N 条 case
- **THEN** 每条 case 都含 `condition_score` 字段，值为数值或 `null`

#### Scenario: 字段缺失时拒绝写出

- **WHEN** 任一 case 的 `features` 缺键，或缺 `condition_score` 字段
- **THEN** 评测 MUST 报错，不得写出缺字段的结果文件

#### Scenario: gold 未召回时两侧同时表达

- **WHEN** 某条 case 的 gold 没有进入重排候选集
- **THEN** `features` MUST 为 `null`，**且** `features_by_tag` 里 MUST 不含 gold 的 tag

- **AND** MUST NOT 用 `{}` 表示未召回：`{}` 是"存在但没有键"的对象，与"不存在"无法区分

#### Scenario: 特征分足以复现名次

- **WHEN** 用结果文件中记录的 `features` 与当次权重重新计算得分并排序
- **THEN** 每条 case 的名次与记录中的 `rank_after_rerank` 完全一致

### Requirement: v3 排序特征的能力边界必须可复算

v3 的三项排序特征（`base` / `authority` / `cosine`）各自"能提供什么信号"
MUST 被写成可执行的断言，MUST NOT 只写在报告或注释里。

**实测边界**（v2 数据，v3 装置）：

| 特征 | 性质 | 判据 |
|---|---|---|
| `base` | 等于融合顺序 | `rrf_norm` 严格单调 |
| `authority` | 分层过滤器 | 同层逆序 == 0 |
| **`cosine`** | **真信号** | **泄漏四判据 + 噪声边界 + 扰动零翻转** |

#### Scenario: status 在候选池内必须有方差，否则必须登记它恒为常数

- **WHEN** 检查 `status` 特征
- **THEN** MUST 断言"池内方差 == 0"这个事实，或断言它有方差
- **AND** 声明"恒为常数"时 MUST 同时指出它占的权重是空的

**实测（该特征已据此删除）**：

```
记忆库的 status 取值：sample {'ACTIVE'}  billing {'ACTIVE'}
候选池内 status 有方差：0/10、0/12
旧 uniform 里 status 权重 0.3 -> 净效为空
```

**登记之后必须删除，不能只登记**：见「恒常数字段不得作为排序特征」。
本场景保留原名作为历史记录，记录的是"当初怎么发现的"，
**不构成"保留一个恒常数字段"的许可**。

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

- **WHEN** 只在 authority 上排序（base=0, cosine=0）
- **THEN** MUST 断言"同一 authority 层内部，相对顺序与融合顺序完全一致"
- **AND** MUST NOT 把 auth-only 的增益解释为"authority 选中了 gold"

**实测**：22 个 case（sample 10 + billing 12），**同层逆序 0 个**。

**这意味着**：authority 的全部作用是**把低 authority 的项推到高层之后**，
层内裁决仍由融合顺序完成。

**若同层逆序 > 0**：说明 authority 内部还有额外信号（比如浮点精度差异），
那时"过滤器"这个结论要重核。

### Requirement: 权重命名必须与语义一致

当给一组预注册权重命名时，
MUST 让名字反映"这组权重回答什么问题"，MUST NOT 让它描述数值形状。

新增的组 MUST 按语义命名；`uniform` 是已登记的历史遗留接口名，不适用"按语义命名"这一条，
但 MUST 在 spec 里被显式登记为历史遗留。

#### Scenario: `(0,0,1)` 不得命名为 `uniform`

- **WHEN** 某组权重是 `(0, 0, 1)`
- **THEN** MUST NOT 命名为 `uniform`
- **AND** MUST 命名为 `cosine_only` 或 `single_signal` 这类语义准确的名字

**为什么**：`uniform` 暗示"各项权重相等"，而 `(0,0,1)` 是"只有一项"。

**还有一个冲突**：`disabled_weights()` 的语义是"只开 base = `(1,0,0)`"。
若 `(0,0,1)` 成为 `uniform`，"全关"与"只开 cosine"会混淆。

| 权重 | 建议名 | 理由 |
|---|---|---|
| `(0,0,1)` | **`cosine_only`** / `single_signal` | 只有一项有信号 |
| `(0.2,0.2,0.6)` | **`mixed`** | 不等权但有退路 |

#### Scenario: `uniform` 从未在 v3 里均匀过，这个事实必须写进 spec

- **WHEN** 检查预注册权重表里名为 `uniform` 的那一组
- **THEN** MUST 在 spec 里登记它是历史遗留，MUST NOT 只在代码注释或 docstring 里解释

**三次改名、三次都不均匀**：

| 装置 | `uniform` 的实际取值 | 均匀吗 |
|---|---|---|
| 四特征时代 | 0.25 × 4 | ✅ 唯一一次 |
| v3 三特征时代 | 0.4 / 0.3 / 0.3 | ❌ |
| **加 cosine 后** | **0.2 / 0.2 / 0.6** | ❌ |

**为什么不改名**：`weights_name="uniform"` 在测试里有 48 处调用，
其中 47 处只依赖"这个名字存在且是一组合法权重"——
`test_determinism` 只要求同一配置两次一致，`test_fusion_cap` 只数 `path_returns`，
`test_pool_vectors` 只看向量写入。改名等于改 47 处，而它们的判据与名字无关。

**为什么必须写进 spec 而不是只写注释**：`rerank.py` 的注释已经解释过三次
（"从四特征各 0.25 重算为三特征 0.4/0.3/0.3"），读者仍然误会过。
注释不是权威，spec 是。

## ADDED Requirements

### Requirement: 报告数字必须标注产生它的权重配置

报告的每个排序指标数字 MUST 标注产生它的权重配置，MUST NOT 留下"不知道是哪个装置跑出来的"数字。
同一命题在两套装置下的数字 MUST 并列保留，MUST NOT 用新数字覆盖旧数字。

#### Scenario: 装置标签必须是可查的名字，不是"当前配置"

- **WHEN** 报告写出一个 `SEH@1` 或增益数字
- **THEN** MUST 在同一行或同一张表的表头写明权重配置
  （例如 `uniform-v3-three-features` / `uniform-v3-cosine`）
- **AND** MUST NOT 用"当前"、"最新"这类随时间失效的措辞代替配置名

#### Scenario: 换装置后旧数字必须保留

- **WHEN** 换排序特征导致同一命题的数字变化
- **THEN** 两套数字 MUST 并列保留，各自带装置标签
- **AND** MUST NOT 删掉旧数字——删掉会丢失"装置变化带来了多少差异"这个信息

**实测例子**：结论 5（三路融合的 top-1 低于 lexical 单路）的
`sample` 相对增益 `+0.2167`、`billing` `−0.0278` 是在
`base + authority + status` 三项装置下测的。换装置后同池同基线的增益预测为
`+0.817` / `+0.722`（上界估计）——**两个数字都要在，且都要带标签**。

#### Scenario: 标签缺失时必须有断言变红

- **WHEN** 报告里某张结论表的表头缺少装置标签
- **THEN** MUST 有测试变红
- **AND** 判定 MUST 定位到表头单元格，MUST NOT 用"关键词出现在整节里"

### Requirement: 缺陷载体必须独立于预注册权重

用于验证某个已登记缺陷是否仍然成立的权重，
MUST 由独立常量提供，MUST NOT 从预注册权重表里取。

#### Scenario: 缺陷的成立不依赖"预注册里恰好有一组非零 authority"

- **WHEN** 验证缺陷 19（authority 罚分能否推翻 base 优势）
- **THEN** MUST 读独立的缺陷载体常量
- **AND** MUST NOT 读 `PREREGISTERED_WEIGHTS` 的任何一项

- **AND** MUST 有一条断言检查"载体与预注册解耦"：
  载体 MUST 有非零 `authority`，且 MUST 有一条断言让"删掉某一组预注册"不会静默使缺陷验证失效

**生命周期不同，所以必须分开**：

| 常量 | 什么时候变 |
|---|---|
| `PREREGISTERED_WEIGHTS` | 每次实验设计变更 |
| 缺陷载体 | 只有当缺陷的算术需要重新验证时 |

**绑在一起的后果**：换一组实验配置会意外地改变"缺陷是否成立"，
而这两件事在报告里是两个独立结论。

**先例**：`test_authority_weight_threshold_is_quantified` 一直用独立权重，
所以 `uniform` 改名/改值时它不受影响。

#### Scenario: 载体换值后缺陷算术必须重算，不能只改一个数

- **WHEN** 缺陷载体从 `0.4/0.3/0.3` 换成 `0.2/0.2/0.6`
- **THEN** `advantage`、`penalty`、净差三项 MUST 全部重算
  （实测 `0.0360/0.3000/0.2640` → `0.0180/0.2000/0.1820`）
- **AND** 结构断言（`penalty > advantage`）MUST 仍然是独立的判据，
  MUST NOT 只靠数值断言——数值断言红时缺陷可能完好

#### Scenario: 载体取到"缺陷被修"的值时必须红

- **WHEN** 载体是 `(0, 0, 1)`（`cosine_only`）
- **THEN** `penalty == 0` 且 `advantage == 0`，结构断言 `penalty > advantage` MUST 变红

**实测**：`cosine_only` 下 `advantage 0.0000 / penalty 0.0000 / 净差 0.0000`。
**这是"缺陷被修"的形态**，不是"算术过期"。
两者必须能区分：结构断言红 = 缺陷没了；只有数值断言红 = 缺陷可能完好。
