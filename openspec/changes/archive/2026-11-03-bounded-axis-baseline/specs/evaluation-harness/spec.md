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

- **AND** 该测试 MUST 用**单路**文件：`F24` 自己只读三路文件

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

**为什么**：实测 `n_competitors + 1 == len(competing_set)` 在 5 条查询上不成立——

| 查询 | `n_competitors` | `competing_set` | `n+1` |
|---|---|---|---|
| `ledger-q11` / `q12` | 0 | **12** | 1 |
| `billing-c1` / `c2` / `c3` | 2 | **9** | 3 |

按 `n+1` 推会让 cross 轴基线变成 `1/1 = 1.0`（随机也能满分），**与真值差 12 倍**。

#### Scenario: 随机基线必须按派生轴分组

- **WHEN** 计算某装置的随机基线
- **THEN** 轴归属 MUST 由池结构派生（`derive_axis`），MUST NOT 读数据集的标注字段

- **AND** 基线 MUST 用 `ranking_pool_size` 的 `1/N`

- **AND** 现有 v2 数据的验收值：

  ```
  axis_baseline_derived(sample) ==
      {"relation_within": 0.3000, "relation_cross": 0.0833}
  ```

- **AND** `relation_cross` MUST 是 `1/12`，MUST NOT 是 `1/1`——
  后者说明用了 `n_competitors + 1`

#### Scenario: v3 下的判据是"比随机好"

- **WHEN** `F24` 在 v3 装置下执行
- **THEN** 结果侧判据 MUST 是 `ratio > baseline`，
  MUST NOT 是"不满分"（`ratio < 0.9999`）

- **AND** "不满分"在 v3 下没有意义：v2 里满分意味着"数据太简单"，
  v3 里满分可能意味着"排序有效"——**两个方向相反**

#### Scenario: 标注与派生的不一致必须被报告

- **WHEN** 报告某 subject 的轴统计
- **THEN** MUST 报"标注与派生不一致 N/M"

- **AND** 该数字 MUST NOT 依赖门禁使用哪套轴——可追溯性来自报告写不写它，
  不来自门禁的轴口径

- **AND** 实测基线：`sample` 0/12、`billing` **3/12**
