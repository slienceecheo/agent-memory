## MODIFIED Requirements

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

- **AND** 该测试 MUST 用**单路**文件

#### Scenario: 结果侧未跑不得算作通过

- **WHEN** `F24` 没有找到任何结果文件
- **THEN** `passed` MUST 为 False

- **AND** 若该代产物尚无（分区为空），MUST 返回 `applicable=False` 并说明

#### Scenario: 两个池大小必须分别命名

- **WHEN** 计算轴归属或随机基线
- **THEN** MUST 使用对应的量：

  | 量 | 定义 | 用途 |
  |---|---|---|
  | `n_competitors` | 池中与 gold **同 relation** 的候选数（不含 gold） | 轴派生 |
  | `ranking_pool_size` | 实际参与排名的候选数（含 gold） | 随机基线 `1/N` |

- **AND** `ranking_pool_size` MUST 从竞争集定义取，
  MUST NOT 由 `n_competitors + 1` 推算

- **AND** 实测例外（全部是 C 轴）：`ledger-q11/q12`（`n=0, cs=12`）、
  `billing-c1/c2/c3`（`n=2, cs=9`）

#### Scenario: 随机基线必须按派生轴分组

- **WHEN** 计算某装置的随机基线
- **THEN** 轴归属 MUST 由池结构派生，MUST NOT 读数据集的标注字段

- **AND** 基线 MUST 用 `ranking_pool_size` 的 `1/N`

- **AND** 现有 v2 数据的验收值：

  ```
  axis_baseline_derived(sample) ==
      {"relation_within": 0.3000, "relation_cross": 0.0833}
  ```

- **AND** `relation_cross` MUST 是 `1/12`，MUST NOT 是 `1/1`

#### Scenario: 空轴必须返回缺失值，不得返回 0

- **WHEN** 某个派生轴没有任何查询
- **THEN** 该轴的基线 MUST 为 `None`（或缺席），**MUST NOT 为 `0.0`**

- **AND** 调用方 MUST 显式处理 `None`

**为什么**：`0.0` 作为基线意味着"随机命中率是 0"，于是任何实测值
（哪怕也是 0）都会 `ratio <= baseline` 而报红——
**"没有数据"会伪装成"基线是 0"**。

- **AND** 实测：`billing` 的 `relation_cross` 是空组（三个 relation 全多分支），
  MUST 返回 `None`

#### Scenario: v3 下的判据是"比随机好"

- **WHEN** `F24` 在 v3 装置下执行
- **THEN** 结果侧 MUST **同时**满足两档：

  | 档 | 判据 | 违反形式 |
  |---|---|---|
  | 下限 | `ratio > baseline` | 排序比随机还差 |
  | 上限 | `ratio < ceiling`（`0.9999`） | **数据太简单** |

- **AND** MUST NOT 只设下限：v3 数据要求"每 subject 至少一个单值 relation"，
  而单值 relation 意味着池可能很小（`n_competitors=1` -> 池 2），
  `ratio` 容易满分——**只设下限会放行"数据太简单"**

- **AND** 上限在 v3 下的语义是**数据难度**，不是装置语义：
  v2 里满分意味着"指标测不到区分能力"（装置与数据都有关），
  v3 里满分只说明"这份数据太容易"

#### Scenario: v3 的数据侧恒真必须被登记

- **WHEN** `F24` 在 v3 下检查数据侧（基线是否饱和）
- **THEN** MUST 在代码注释与本节写明：**该判据在 v3 下恒真**

- **AND** 理由：派生 within 的池大小 `= n_competitors + 1 >= 2`，
  基线最大 `1/2 = 0.5`，永远小于 `0.9999`

- **AND** MUST 保留该判据：它防的是"池大小退化成 1"这个形状退化
  （`n_competitors` 全为 0 时基线变 1.0）

- **AND** 真正有判别力的是结果侧（下限 + 上限），MUST NOT 让读者以为两段都在验

#### Scenario: 标注与派生的不一致必须被报告

- **WHEN** 报告某 subject 的轴统计
- **THEN** MUST 报"标注与派生不一致 N/M"

- **AND** 该数字 MUST NOT 依赖门禁使用哪套轴

- **AND** 实测基线：`sample` 0/12、`billing` **3/12**
