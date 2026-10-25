# Spec Delta

## ADDED Requirements

### Requirement: 分类质量的度量

系统 SHALL 为多类别判定任务提供：逐类混淆矩阵、macro-F1、以及逐类的配对 bootstrap 区间。
指标 MUST 对类别不均衡稳健，且 MUST NOT 只报总体准确率。

#### Scenario: 六类混淆矩阵
- **WHEN** 对一批判定结果计算质量
- **THEN** 输出 6×6 混淆矩阵，行是人工确认的期望类别，列是系统给出的判定

#### Scenario: macro-F1 不偏向多数类
- **WHEN** 某个类别只有 3 条样本且全部判错，其余类别全对
- **THEN** macro-F1 因该类的 0 分而明显下降，而不是被总体准确率掩盖

#### Scenario: 逐类区间
- **WHEN** 报告某一类的 F1
- **THEN** 同时给出该类的样本数与 bootstrap 区间，样本数过少时明确标注区间不可靠

#### Scenario: 单类无样本
- **WHEN** 某个类别在评估集中没有样本
- **THEN** 该类在矩阵中显示为 0 样本，且不计入 macro-F1 的分母，
  而不是被当作 0 分拉低整体

#### Scenario: 同种子可复现
- **WHEN** 用相同种子重复计算
- **THEN** 混淆矩阵与全部区间逐位相同

#### Scenario: 标注不一致的条目单列
- **WHEN** 两名标注者的标签不一致
- **THEN** 这些条目在报告中单列，且不静默采用任意一方
