# Tasks

## 0. 为什么要有这个变更

三处小项，都是"改过但没人检查"的形态：

| # | 事实 | 为什么没被发现 |
|---|---|---|
| 1 | `HANDOFF.md:3` 写 `2026-10-30`，实际今天 `2026-11-04` | **没有测试断言它** |
| 2 | `ACCEPTED_FAILURES["F24"]` 只写 billing | `sample` 上它是通过 |
| 3 | `archive` 失败留下的 lock 无记录 | 只在"想再归档"时暴露 |

## 1. HANDOFF 更新日期

- [x] 1.1 日期改为 `2026-11-04`（最后一次归档的日期）

- [x] 1.2 写测试：更新日期 == 最后一次归档目录名的日期
  - 判据：`max(archive/ 下 YYYY-MM-DD 前缀)`
  - **不用 `date.today()`**：跨日会红，而红的原因与文档无关
  - 验证：`pytest -k update_date_matches_latest_archive`

- [x] 1.3 写测试：日期不得晚于今天
  - **单独一条**：防"写 2099-01-01 让它一直通过"
  - 验证：`pytest -k not_in_the_future`

- [x] 1.4 证伪（双向）
  - 改回 `2026-10-30` -> **红**，消息写"文档更旧"
  - 改为 `2099-01-01` -> **红**，消息写"未来日期不是新鲜度标记"
  - **已做**，两条都按预期红

## 2. `ACCEPTED_FAILURES["F24"]` 补范围

- [x] 2.1 写全两个 subject
  ```
  "正确的失败：**billing** A 轴 SEH@1 = 1.0000（满分=测不到区分）；
   **sample 上是通过**（SEH@1 = 0.9000）"
  ```
  - 实测：`billing` 冻结文件 `passed=False`、`sample` `passed=True`
  - 验证：`pytest tests/retrieval/test_accepted_failures.py -q` 通过

- [x] 2.2 在注释里写明"这份文件没有 `applicable` 字段"
  - **并写明判据 `not c["passed"]` 在这份文件上是正确的**
  - 防下一个人把它"改成三态"

## 3. lock 说明

- [x] 3.1 `HANDOFF` 的「环境与纪律」加一行
  - 写明：失败后 `openspec list` 仍显示活动变更、`validate` 通过，
    **唯一信号是下一次 archive 报错**
  - 写明处置：删 lock 再重跑

## 4. 验收

- [x] 4.1 `openspec validate handoff-freshness --strict` 通过
- [x] 4.2 **归档前**跑 `openspec validate --all --strict`
- [x] 4.3 全量测试通过
- [ ] 4.4 归档

## 5. 不在本变更范围

- **不改 `test_accepted_failures` 的判据**：冻结文件是两态格式（见 design 决策 3）
- **不做"统计回填脚本化"**：下一个变更
  - 已收窄范围：只把"单一数字"与"百分比 + 分母"两类改成读脚本，
    "章节结构文案"保留字面（它是文案，不是数字）
