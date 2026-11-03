# Tasks

## 0. 设计修正（重要）

**原计划是"6 条 result-side 门禁 + 装置签名 -> 不适用"，这个计划被推翻了。**

正确的区分不是"读的文件新不新"，而是**判据是否依赖装置**：

| 门禁 | 判据 | 依赖装置？ | 处置 |
|---|---|---|---|
| `L6b` | 池内向量都写入（范数非零） | ❌ | **照跑** |
| `L8` | dedup 收到的分数有方差 | ❌ | **照跑** |
| `L6c` | 三路召回都返回非空 | ❌ | **照跑** |
| `F19b` | implicit 的 gold 被召回 | ❌（召回不依赖排序） | **照跑** |
| `F20` | condition 对 A 轴有贡献 | **✅ 判据随装置消失** | 不适用 |
| `F24` | A 轴 SEH@1 不满分 | **✅ 阈值语义随装置反转** | 不适用 |

**原计划错在哪**：把 `L6c`/`L6b`/`L8`/`F19b` 判成"不适用"，
等于**永久关掉四条在 v3 下仍然有效的门禁**。
`L6c` 测"三路召回都返回非空"，与 condition 加权毫无关系。

**分类只有 2 条，不是 6 条。** 这决定了下面的数字。

## 1. 装置签名（TDD）

- [x] 1.1 写失败测试：`apparatus_signature(payload)` 两种文件格式、两套结构判据
  - 有 `per_case` -> `features` 存在 = v3
  - 消融聚合（无 `per_case`）-> 两轴逐条 rank 相同 = v3
  - **反例**：`weights` 名字改掉不影响；`code_version` 改掉不影响；
    `apparatus: "v3"` 常量**不影响**（常量可以说谎）
  - 验证：`pytest -k apparatus_signature` 先红
  - **完成**：`tests/retrieval/test_gate_apparatus_binding.py` 5 条

- [x] 1.2 实现 `apparatus_signature`
  - 验证：1.1 转绿
  - **完成**：两种格式分支；`unknown` 用于"无法判断"

- [x] 1.3 写测试（验收 5，自检）：当前代码产出的结果必须被判为 `"v3"`
  - **用真实 `evaluate()` 产出一份 `per_case`**，不手写 dict
  - 若这条红，签名函数会把当前装置也判成"不适用"——所有门禁静默变"已处置"
  - 验证：`pytest -k current_apparatus_is_v3`

## 2. `Check` 增加适用域

- [x] 2.1 写测试：`Check` 新增 `applicable: bool = True`
  - 默认 True 保证 21 条数据侧门禁不受影响
  - 验证：`pytest -k check_has_applicable`

- [x] 2.2 实现：`Check` 加字段；`applicable=False` 时 `passed` MUST 为 False
  - **构造违反**：`Check(..., applicable=False, passed=True)` 直接报错
  - 验证：`pytest -k applicable_implies_not_passed`

- [x] 2.3 写测试：**只有判据依赖装置的两条**返回 `applicable=False`
  - `F20` / `F24` -> 不适用；`L6b` / `L8` / `L6c` / `F19b` -> 照跑
  - 验证：`pytest -k only_apparatus_dependent_gates_are_not_applicable`

- [x] 2.4 实现：`F20` / `F24` 按 `CURRENT_APPARATUS` 分支
  - **按"当前代码的装置"判，不按产物签名**：产物是 v2 的只说明"能读"，
    不说明"它的数字能回答当前装置的问题"
  - detail MUST 写明"为什么判据不成立"
  - 验证：2.3 转绿
  - **完成**：`CURRENT_APPARATUS = "v3"` 是显式常量，不从产物推

- [x] 2.5 **验收 3**：签名与内容矛盾的文件必须被抓到
  - 构造两份消融文件：rank 变了（v2 行为）/ rank 没变（v3 行为），
    各带一个**相反的** `apparatus` 常量
  - 判据：签名必须按结构判，不被常量左右
  - 验证：`pytest -k contradiction_between_signature_and_content_is_caught`

## 3. 真实 v2 文件的结论

- [x] 3.1 写测试：对真实 v2 文件，**只有 `F20` / `F24` 不适用**，其余照跑
  - **原计划写的"6 条全部不适用"是错的**（见 §0）
  - 验证：`pytest -k only_apparatus_dependent_gates_are_not_applicable`

- [x] 3.2 记录数字变化（**实测，不是推算**）
  - | subject | 修前 | 修后 | 差异 |
    |---|---|---|---|
    | `sample` | 21/27 | **19/27** | -2（F20、F24） |
    | `billing` | 24/27 | **23/27** | -1（F20 原通过，F24 原就失败） |
  - **`billing` 只减 1 的原因**：F24 在 billing 上原本就被"满分"判为失败，
    变成"不适用"后仍不是通过——通过数不变，但语义从"失败"变成"不适用"
  - 写进 HANDOFF，并说明"其余 4 条读历史产物的门禁照跑"

## 4. `F24` 分母（先于适用域生效）

- [x] 4.1 写失败测试：单路文件 `v2-sample-lexical.json` 的正确口径 == 1.0000
  - **当前是 0.6000**（6/10），正确是 6/6
  - 用**单路**文件：`F24` 自己只读三路，所以这是唯一能抓低报的断言
  - **A 轴必须从数据集 `axis` 字段读**：实测 `sample` 的 A 轴是 `ledger-q1..q10`、
    C 轴是 `q11/q12`——`-q` 前缀**不能**区分 A/C，按前缀判会多算 2 条
  - 验证：`pytest -k single_path_seh1_is_not_underreported` 先红

- [x] 4.2 实现：分母改为"已评分 A"（`rank_after_rerank is not None`）
  - 验证：4.1 转绿

- [x] 4.3 写测试（回归）：三路文件的数字**不变**
  - `v2-sample-threeway.json` 0.9000、`v2-billing-lexical-vector-adjacency.json` 1.0000
  - 前提：三路的已评分数 == A 标注总数（10/10、9/9）
  - 验证：`pytest -k threeway_numbers_unchanged`

- [x] 4.4 写测试：空分母不产生 NaN
  - 验证：`pytest -k empty_denominator`

## 5. 验收

- [x] 5.1 `openspec validate gate-apparatus-binding --strict` 通过
- [x] 5.2 **归档前**跑 `openspec validate --all --strict`
  - 上一轮学到的：`validate <change>` 不检查归档后的 spec 正文长度
- [x] 5.3 全量测试通过
  - **实测**：1600 passed, 4 skipped
- [x] 5.4 更新 `docs/HANDOFF.md`
  - `ledger 19/27` / `billing 23/27`，并说明 2 条不适用的理由
  - 说明其余 4 条读历史产物的门禁照跑
- [ ] 5.5 归档

## 6. 顺带修掉的两处真实缺陷

- [x] 6.1 **`F24` 的 detail 曾取错 subject 的文件**
  - `glob("v2-*-lexical-vector-adjacency.json")` 匹配到两个 subject 的文件
  - 若先判适用域再按内容匹配 subject，`sample` 会拿 `billing` 的文件名说话
  - **修法**：先按 `dataset_a <= case_ids` 匹配 subject，再判适用域
  - 实测：修前 `sample` 的 detail 写 `v2-billing-...`，修后写 `v2-ledger-...`

- [x] 6.2 **`test_l6c_criterion` 的假文件必须造成 v3 签名**
  - 否则适用域会短路，测试**测不到 L6c 的判据**，只是恰好因 `passed=False` 通过
  - 这正是"不适用掩盖判据"的形态
  - **修法**：假文件带 `features`，并断言 `result.applicable` 为 True
