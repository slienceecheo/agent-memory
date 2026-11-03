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

- **AND** detail MUST 写明**两边**分别是什么

#### Scenario: 判据不依赖装置的门禁照常执行

- **WHEN** 某门禁的判据与排序装置无关
- **THEN** 它 MUST 照常执行并给出**通过或失败**

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

#### Scenario: 当前装置必须识别为适用

- **WHEN** 断言"当前装置是哪一代"
- **THEN** MUST 比较 `CURRENT_APPARATUS` 与**当前代码实际产出的签名**

- **AND** MUST NOT 只断言常量值——那是同义反复

#### Scenario: 判据依赖装置不等于判据失效

- **WHEN** 某门禁的判据在 v3 下的**期望值**变了
- **THEN** MUST 在 v3 下给出**新的期望值并执行**

#### Scenario: 门禁必须能发现所有分区的产物

- **WHEN** 结果文件位于任何**已登记分区**
- **THEN** 门禁 MUST 能发现它

- **AND** 文件发现 MUST NOT 依赖文件名前缀

#### Scenario: 找不到文件必须显式区分三件事

- **WHEN** 门禁没有找到可用的结果文件
- **THEN** MUST 区分：分区为空（`applicable=False`）/
  有文件但不匹配（`passed=False`）/ 有匹配文件（执行判据）

- **AND** 前两种 MUST NOT 返回 `passed=True`

#### Scenario: 不适用在账本里必须与失败分开

- **WHEN** 汇总一次 `run_all()` 的结果
- **THEN** MUST 分别报 **通过 / 不适用 / 未通过** 三个数

- **AND** `不适用` MUST NOT 计入 `未通过`

- **AND** 结果文件的每条 check MUST 含 `applicable` 字段——
  否则从文件复算时无法区分两种 false

**为什么**：实测 `billing` 的 27 条里 `passed=True` 是 23、
`applicable=False` 是 2，而旧 `main()` 报 `通过 23/27` 并把
`[F6, F20, F21b, F24]` 一起列为"未通过"——**2 条不适用被算进了失败**，
而 `--json` 不写 `applicable`，结果文件也复算不出这个区别。

#### Scenario: 判据没有主语时必须判失败，不判不适用

- **WHEN** 装置匹配、文件可读，但数据形状让某条判据**没有对象**
  （例如 `F24` 在"派生 within 为空"的 subject 上）
- **THEN** `passed` MUST 为 False，`applicable` MUST 保持 True

- **AND** MUST NOT 用 `applicable=False`：
  它的语义是"跨装置，判据不成立"，而这里装置是对的，是数据形状的问题

- **AND** v3 的数据约束 MUST 写明"每个 subject 至少 1 条派生 within 查询"，
  否则 `F24` 会在合法数据上永久红
