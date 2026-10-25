"""用**同主题干扰项**重建候选池。

第一次评测得到 SEH@5 = 1.000，诊断后确认是**任务太简单**：
干扰项取自其他场景的 gold，主题与 query 毫不相干（如 `package_manager`
vs `dietary_restriction`），词面召回几乎是唯一竞争者。

真实检索的难度来自**同主题、相似但不能回答**的干扰项。本模块提供三种池：

| 模式 | 干扰项来源 | 难度 |
|---|---|---|
| `unrelated` | 其他场景的 gold（原方案） | 低 |
| `same_relation` | 同 relation、不同 subject | 中 |
| `adversarial` | 同 relation + 与 gold 词汇重叠 | 高 |

报告必须给出三种模式的分数，否则"SEH=1.0"会被误读成检索能力强。
"""
