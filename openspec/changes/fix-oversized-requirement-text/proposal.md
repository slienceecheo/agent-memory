## Why

`openspec validate --all --strict` 在归档 `retrieval-v3-apparatus` 之后失败，
报 `memory-retrieval` 的 `requirements[4]`（`四特征重排`）正文超过 500 字符。

**这不是归档引入的**：归档前 delta 里那段正文就有 **725 字符**。
而 `openspec validate <change> --strict` **不检查这条**——它只校验 delta 的结构
（requirement 名、scenario 名、MODIFIED 的匹配键）。
只有对**正式 spec** 跑 `validate --type spec` 才检查。

**同时发现的第二处**：`memory-retrieval` 里 `全部特征关闭` 这个 scenario
说"三个特征全部关闭 -> 退化为融合分排序"，而 `retrieval-apparatus` 里
同名的旧场景已被改成 `全零权重被拒绝`。**两条 spec 对同一件事说法相反**，
而 `RerankWeights(0,0,0)` 实际会被拒绝——所以 `memory-retrieval` 那份是错的。

## What Changes

**纯格式与事实修正，不改变行为**：

1. 把 `四特征重排` 正文里"与历史产物的关系"从**正文**移进一个 **scenario**
   —— 正文只该说"这条要求是什么"，示例与边界进 scenario（OpenSpec 的警告原文）
2. 把 `全部特征关闭` 改为 `全零权重被拒绝`，并写明
   `disabled_weights()` 的语义是"只开融合分"而非"全关"
   —— 与 `retrieval-apparatus` 对齐

不改的：

- requirement 的标题（`四特征重排`）——它是 MODIFIED 的匹配键
- 任何 MUST / SHALL 的语义内容
- 任何代码、测试、结果文件

## Impact

- 代码：无
- 数据：无
- 测试：`test_rerank.py` 已在归档前改名并补断言，本次不动
- 规格：`openspec/specs/memory-retrieval/spec.md` 一条 requirement 的正文结构与一个场景

## 附：这次是怎么漏过去的（必须记下来）

| 检查 | 归档前 | 归档后 |
|---|---|---|
| `validate <change> --strict` | ✅ 通过 | 不适用（change 已归档） |
| `validate --all --strict` | ❌ **没跑** | ❌ 失败 |

**归档流程里必须有一步 `validate --all --strict`，且必须在归档前跑。**
否则"归档前全绿"只说明 delta 结构对，不说明归档后的 spec 合法。

**第二处漏过的原因更具体**：同一个"全部特征关闭"场景在**两个 capability**
里各有一份。我改 `retrieval-apparatus` 时没有搜 `memory-retrieval` 里的同名场景。
**所以"改一处"之前必须先 `grep` 同一句话有几处。**
