## ADDED Requirements

### Requirement: 结论必须区分"现象"与"机制归因"

当报告陈述"配置 A 比配置 B 差"时，
若存在多个机制都能产生同样的结果，MUST 显式声明"机制未区分"，
且 MUST 列出这些机制。

#### Scenario: 未区分机制时必须写明

- **WHEN** 报告陈述某个下降
- **THEN** MUST 说明该下降的可能机制，若未区分则 MUST 明写"机制未区分"

**实测**：结论 5 的 `0.8333 → 0.5000` 有两个可能机制：

| 机制 | 处置 |
|---|---|
| 融合规则（RRF 稀释） | 改融合 |
| vector 召回质量（cosine 排序） | 改召回 |

**两者处置完全不同，而现象完全相同。**

#### Scenario: 未区分的原因必须写明

- **WHEN** 声明"机制未区分"
- **THEN** MUST 说明**为什么**不能区分

**实测**：区分它们需要 cosine 分，而现有 15 份冻结产物都没有记录：

```
v2-billing-lexical-vector-adjacency.json   features_by_tag 为空
含 cos/similar 的字段：无
```

**若不写原因**，读者会以为"还没做"，而实际是"当前产物格式做不到"。

#### Scenario: 累加值必须标明，不得被读成单条

- **WHEN** 报告引用 `path_returns.<path>` 这类顶层聚合值
- **THEN** MUST 说明它是累加值
- **AND** MUST 给出单条 case 的量级

**实测**：

| 产物 | 顶层 `vector` | 单条 case | `pool_size` |
|---|---|---|---|
| `a3-lexical-vector-adjacency.json` | 462 | 14 | 14 |
| `v2-billing-lexical-vector-adjacency.json` | 108 | 9 | 9 |

**单条 case 的 `path_returns.vector` 恒等于 `pool_size`**：vector 路返回整个池。

**误读的代价**：以为"vector 返回海量噪声"，从而去压缩召回——
而它返回的就是全部候选，没有可压缩的东西。

### Requirement: 产物断言与文档断言必须分开

当某个事实同时体现在"产物"与"文档"两处时，
MUST 分成两条断言，MUST NOT 用一条断言声称覆盖两者。

#### Scenario: 只读产物的断言不得声称覆盖文档

- **WHEN** 断言函数名声称"文档写了 X"（如 `test_report_documents_...`）
- **THEN** 它 MUST 真的读文档
- **AND** MUST NOT 只读产物

**实测的坑**：本轮先写了一条 `test_report_documents_vector_returns_whole_pool`，
**但它只读产物**。删掉文档里"返回了整个池"那句话，断言不会红——
**名字声称覆盖的内容无人守**。

#### Scenario: 两条断言必须各自能被单独违反

- **WHEN** 拆分产物断言与文档断言
- **THEN** 改文档 MUST 只让文档断言红
- **AND** 改产物 MUST 只让产物断言红

**验证方式**：

| 构造 | 文档断言 | 产物断言 |
|---|---|---|
| 删掉文档里那句话 | **红** | 绿 |
| 改产物里一个值 | 绿 | **红** |

**若两者同时红或同时绿**，说明它们没有真正分开。
