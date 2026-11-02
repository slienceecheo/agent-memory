# Tasks

## 1. 修正文超长

- [x] 1.1 把 `四特征重排` 正文里的"与历史产物的关系"移进 scenario
  - 验证：正文长度从 725 字符降到 124 字符（阈值 500）
  - **完成**：新增 `#### Scenario: 历史产物的特征数与当前不同`，
    四条 MUST 与那张版本对照表全部移入

- [x] 1.2 确认 scenario 一个不丢
  - 验证：`openspec validate fix-oversized-requirement-text --strict` 通过
  - **完成**：9 个 scenario（原 8 个 + 新增 1 个）

## 2. 修 `全部特征关闭` 与 `retrieval-apparatus` 的矛盾

- [x] 2.1 把该场景的内容改为"全零权重被拒绝"，并写明场景名沿用旧名
  - 验证：与 `openspec/specs/retrieval-apparatus/spec.md` 的
    `全零权重被拒绝` 不再矛盾
  - **完成**：内容改为四条约 MUST；场景名保留（OpenSpec MODIFIED
    不允许丢弃已有场景，实测报错 `omits scenario(s)...archive refuses to drop them`）

## 3. 归档前验证

- [x] 3.1 `openspec validate fix-oversized-requirement-text --strict` 通过
- [ ] 3.2 **归档前**跑 `openspec validate --all --strict`
  - **这一步就是上次漏掉的**
  - 验证：6 个 spec 全部 valid，无 WARNING

- [ ] 3.3 全量测试通过（应无变化：本变更不动代码）
  - 验证：`uv run --no-sync pytest -q`

- [ ] 3.4 归档后复验 `openspec validate --all --strict`
  - 验证：`memory-retrieval` 不再有 WARNING

## 4. 记录流程缺口

- [x] 4.1 在 proposal 的"附"节写明：`validate <change>` 与 `validate --all` 管不同的东西
- [x] 4.2 写明"同一句话在两个 capability 里各有一份"的教训
  - **完成**：改 `retrieval-apparatus` 时没搜 `memory-retrieval` 里的同名场景，
    导致两条 spec 对同一件事说法相反
