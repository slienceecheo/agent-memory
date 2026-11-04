## MODIFIED Requirements

### Requirement: 门禁的适用域

读结果文件的门禁 MUST 区分**两件不同的事**，且 MUST 分别回答：

| 问题 | 必须由什么回答 |
|---|---|
| 当前代码是哪一代装置？ | 一个**显式常量**（MUST NOT 从产物推） |
| 这份文件能不能回答当前装置的问题？ | **常量与文件签名的比较** |

**只有当判据依赖装置时**才返回"不适用"；判据不依赖装置的门禁 MUST 照常执行。

#### Scenario: 判据依赖装置的门禁返回不适用

- **WHEN** 某门禁的判据依赖排序装置，且文件签名**不等于** `CURRENT_APPARATUS`
- **THEN** 门禁 MUST 返回 `applicable=False`，`passed` MUST 为 False

#### Scenario: 判据不依赖装置的门禁照常执行

- **WHEN** 某门禁的判据与排序装置无关
- **THEN** 它 MUST 照常执行并给出**通过或失败**

#### Scenario: 装置签名只读结构事实

- **WHEN** 需要判断一份结果文件由哪个装置产生
- **THEN** 签名 MUST 由文件自身的结构决定

- **AND** MUST NOT 依赖 `apparatus` 之类的常量字段

#### Scenario: 分类写宽时必须被抓住

- **WHEN** 有人把"判据不依赖装置"的门禁也判成"不适用"
- **THEN** MUST 有测试会红

#### Scenario: 当前装置必须识别为适用

- **WHEN** 断言"当前装置是哪一代"
- **THEN** MUST 比较 `CURRENT_APPARATUS` 与**当前代码实际产出的签名**

- **AND** MUST NOT 只断言常量值

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

- **AND** 结果文件的每条 check MUST 含 `applicable` 字段

#### Scenario: 判据没有主语时必须判失败，不判不适用

- **WHEN** 装置匹配、文件可读，但数据形状让某条判据**没有对象**
- **THEN** `passed` MUST 为 False，`applicable` MUST 保持 True

#### Scenario: 测试判据必须与账本三态一致

- **WHEN** 某测试检查"未通过项是否被分类"
- **THEN** 它 MUST 用 `applicable and not passed`，MUST NOT 用 `not passed`

- **AND** 必须有证伪证明：删真失败 -> 红；删不适用 -> 不红

#### Scenario: 历史判定与当前判定必须分开标注

- **WHEN** 某测试读**冻结的结果文件**做出判定
- **THEN** 测试名与 docstring MUST 写明它验的是**哪一代装置**

- **AND** MUST NOT 使用 `actually_fails` 这类默认"现在"的措辞

#### Scenario: 读冻结文件时不得假设三态字段存在

- **WHEN** 某测试读**冻结的 v2 文件**（`v2-*-gates.json`）
- **THEN** 它 MUST 只用该文件实际拥有的字段

- **AND** MUST NOT 用 `applicable` 做判据——**那份文件没有这个字段**

- **AND** 实测：`v2-sample-gates.json` 与 `v2-billing-gates.json`
  的 `checks[*]` 键只有 `[code, detail, passed, title]`

**为什么**：那些文件由 v2 装置产出，那时只有两态。
用三态判据读会 `KeyError`，或更糟——静默把缺失当成 `False`。

- **AND** 三态判据只适用于**当前 `run_all()` 的返回值**，不适用于冻结文件
