# Spec Delta

## ADDED Requirements

### Requirement: 检索质量的度量

系统 SHALL 为检索任务提供 SEH@K、SRS 与四类失败归因，并 MUST 同时给出
样本数与配对 bootstrap 区间。

#### Scenario: SEH@K 的定义
- **WHEN** 计算某 K 值的 SEH
- **THEN** 标准答案位于前 K 条的比例即为该值，取值在 [0, 1]

#### Scenario: SRS 的定义
- **WHEN** 计算 SRS
- **THEN** 按标准答案的排名归一化到 [0, 1]，排名第 1 得 1.0，
  完全未召回得 0.0，且 MUST 与 SEH@K 分开报告

#### Scenario: K 大于结果总数
- **WHEN** K 超过实际返回条数
- **THEN** 按实际返回条数计算，不把缺失位置算作命中

#### Scenario: 区间与样本数
- **WHEN** 报告任一检索指标
- **THEN** 同时给出样本数与 bootstrap 区间；样本数过少时明确标注

#### Scenario: 配对比较
- **WHEN** 比较两个检索配置
- **THEN** 用配对 bootstrap 在同一批查询上比较，而非两次独立采样
