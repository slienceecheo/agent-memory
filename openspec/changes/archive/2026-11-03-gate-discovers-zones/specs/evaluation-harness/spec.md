## MODIFIED Requirements

### Requirement: 门禁的适用域

读结果文件的门禁 MUST 区分**两件不同的事**，且 MUST 分别回答：

| 问题 | 必须由什么回答 |
|---|---|
| 当前代码是哪一代装置？ | 一个**显式常量**（MUST NOT 从产物推） |
| 这份文件能不能回答当前装置的问题？ | **常量与文件签名的比较** |

**只判断第一个问题是错的**：常量在任意一次运行内恒定，所以
`CURRENT_APPARATUS == "v3"` 这类条件**恒为真**，会让"不适用"变成无条件结论。

**只有当判据依赖装置时**才返回"不适用"；判据不依赖装置的门禁 MUST 照常执行。

#### Scenario: 判据依赖装置的门禁返回不适用

- **WHEN** 某门禁的判据依赖排序装置，且文件签名**不等于** `CURRENT_APPARATUS`
- **THEN** 门禁 MUST 返回 `applicable=False`，`passed` MUST 为 False

- **AND** detail MUST 写明**两边**分别是什么（"X 装置产物，当前为 Y"）

- **AND** MUST NOT 因为"当前装置是 v3"就直接判不适用

#### Scenario: 判据不依赖装置的门禁照常执行

- **WHEN** 某门禁的判据与排序装置无关
- **THEN** 它 MUST 照常执行并给出**通过或失败**

- **AND** MUST NOT 因为"产物来自旧装置"就返回"不适用"

#### Scenario: 装置签名只读结构事实

- **WHEN** 需要判断一份结果文件由哪个装置产生
- **THEN** 签名 MUST 由文件自身的结构决定：

  | 格式 | 判据 |
  |---|---|
  | 有 `per_case` | `per_case[0]` 有 `features` -> v3 |
  | 消融聚合（无 `per_case`） | 两轴逐条 rank 相同 -> v3 |

- **AND** MUST NOT 依赖 `apparatus` 之类的常量字段

- **AND** 签名是 `unknown` 时 MUST 保守处置为"不适用"

#### Scenario: 分类写宽时必须被抓住

- **WHEN** 有人把"判据不依赖装置"的门禁也判成"不适用"
- **THEN** MUST 有测试会红

- **AND** 该测试 MUST 断言**哪些**门禁不适用

#### Scenario: 当前装置必须识别为适用

- **WHEN** 断言"当前装置是哪一代"，或对当前代码产出的结果文件跑门禁
- **THEN** MUST 比较 `CURRENT_APPARATUS` 与**当前代码实际产出的签名**

- **AND** MUST NOT 只断言常量值——那是同义反复

- **AND** 同装置签名的文件 MUST 让门禁**执行**；若改回"只看常量"，MUST 有测试变红

#### Scenario: 判据依赖装置不等于判据失效

- **WHEN** 某门禁的判据在 v3 下的**期望值**变了（而非判据本身失效）
- **THEN** MUST 在 v3 下给出**新的期望值并执行**，MUST NOT 永久返回"不适用"

- **AND** 例：`F20` 在 v3 下期望 `drop == 0`（能抓"BREAKING 被回退"）

#### Scenario: 门禁必须能发现所有分区的产物

- **WHEN** 结果文件位于任何**已登记分区**（`results/` 顶层或 `results/v3/` 等）
- **THEN** 门禁 MUST 能发现它

- **AND** 文件发现 MUST NOT 依赖文件名前缀（如 `v2-`）——
  前缀是历史约定，不该成为"能不能被发现"的条件

- **AND** 装置归属 MUST 由 `apparatus_signature` 判断，MUST NOT 由文件名判断

#### Scenario: 找不到文件必须显式区分三件事

- **WHEN** 门禁没有找到可用的结果文件
- **THEN** MUST 区分以下三种情形，且 MUST NOT 混为一种：

  | 情形 | 应有结果 |
  |---|---|
  | 目标分区**为空**（该代尚无产物） | `applicable=False`，写明"尚无产物" |
  | 有文件但**不匹配本数据集** | `passed=False`，写明是配置问题 |
  | 有匹配文件 | 执行判据 |

- **AND** 前两种 MUST NOT 返回 `passed=True`

**为什么这条必须存在**：实测 `F20` 与 `F24` 对"没找到文件"给出**相反**的结论
（`passed=False` vs `passed=True`）。同一个状态两种处置，
而 `passed=True` 让"门禁没跑"伪装成"执行过"。

### Requirement: A 轴饱和判据的分母

`F24`（A 轴 `SEH@1` 不得满分）的分母 MUST 是**已评分**的 A 轴 case 数，
MUST NOT 是全部 A 轴标注数。

未评分的 case（池不足 K 被跳过、`rank_after_rerank` 为 `None`）
MUST 从分母中排除。

#### Scenario: 未评分 case 不计入分母

- **WHEN** 某 subject 的 A 轴有 10 条标注，其中 6 条因池不足被跳过
- **THEN** 分母 MUST 为 4，MUST NOT 为 10

#### Scenario: 三路配置下的数字不变

- **WHEN** 结果文件里全部 A 轴 case 都被评分
- **THEN** 修改前后 `SEH@1` MUST 相同

#### Scenario: 低报必须可被看见

- **WHEN** 存在一份单路配置的结果文件，其 A 轴有未评分 case
- **THEN** MUST 有测试断言其 `SEH@1` 用正确口径计算

- **AND** 该测试 MUST 用**单路**文件：`F24` 自己只读三路文件

#### Scenario: 结果侧未跑不得算作通过

- **WHEN** `F24` 没有找到任何结果文件
- **THEN** `passed` MUST 为 False

- **AND** 若该代产物尚无（分区为空），MUST 返回 `applicable=False` 并说明

**为什么**：`F24` 的 `passed = data_side_problem is None and result_side_problem is None`
里，"没找到文件"与"找到了且没问题"都是 `None`——
实测前者得到 `passed=True`，即**门禁没跑却报告通过**。
