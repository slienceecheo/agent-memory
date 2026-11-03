# Tasks

## 0. 为什么要有这个变更

**上一轮交付的 `apparatus_signature` 没有被任何门禁使用。**

AST 实测：

```
定义：check_v2_dataset.py:114
调用：check_v2_dataset.py:982（唯一一处，在 _ablation_for_subjects 里）
```

而决定"是否不适用"的是 `if CURRENT_APPARATUS == "v3"`（两处），
常量恒为 "v3"，所以**条件恒真**。

后果：v3 数据造出来后，`F20`/`F24` 仍永久不适用。

## 1. 把签名接进判断

- [x] 1.1 写测试：`F20` 必须真的读签名
  - 同装置签名的假消融文件 -> **执行**并断言 `drop == 0`
  - 跨装置签名的假消融文件 -> **不适用**
  - 验证：`pytest -k f20_actually_reads_the_signature`
  - **完成**：`tests/retrieval/test_gate_apparatus_binding.py`

- [x] 1.2 实现：`if CURRENT_APPARATUS != signature:` 代替 `== "v3"`
  - 两处：`F20`、`F24`
  - 验证：1.1 转绿

- [x] 1.3 修 `F20` 的 `signature` 变量被丢弃的问题
  - `payload, source, signature = _ablation_for_subjects(dataset)`
  - （上一轮写成 `_`，却又在下面用 `signature`，直接 NameError）
  - 验证：导入不报错

## 2. `F20` 在 v3 下换判据，而不是永久关闭

- [x] 2.1 写测试：v3 下 `drop != 0` 必须红
  - 构造 v3 签名（rank 相同）但 `drop=0.6` 的矛盾文件
  - 验证：`pytest -k f20_rejects_nonzero_drop_on_v3`
  - **完成**：detail 写"v3 下掉幅 +0.6000 不为 0——说明 condition 又参与了加权"

- [x] 2.2 实现：v3 分支断言 `abs(drop) < 1e-9`
  - 通过时 detail 写"期望 0"
  - 失败时 detail 写"BREAKING 被回退"
  - 验证：2.1 转绿

## 3. 常量自检要比较"常量 vs 现实"

- [x] 3.1 改 `test_current_apparatus_is_v3`
  - 旧写法 `assert CURRENT_APPARATUS == "v3"` 是同义反复
  - 新写法：`assert CURRENT_APPARATUS == apparatus_signature(evaluate() 的产物)`
  - 验证：`pytest -k current_apparatus_is_v3`
  - **完成**：用真实 `evaluate()` 产出，不手写 dict

## 4. 反向证伪

- [x] 4.1 把 `F20` 改回 `if CURRENT_APPARATUS == "v3"`，测试必须红
  - **这是本变更最重要的一条**：验收 1-4 都能通过而签名仍未接入
  - **已做**：
    ```
    缺陷版（只看常量）跑新测试
      -> FAILED test_f20_actually_reads_the_signature
      -> "同装置的文件却判'不适用'——说明判断只看常量"
    ```
  - 恢复后 7 passed

## 5. 验收

- [x] 5.1 `openspec validate wire-apparatus-signature --strict` 通过
- [x] 5.2 **归档前**跑 `openspec validate --all --strict`
- [x] 5.3 全量测试通过
  - **实测**：1601 passed, 3 skipped（数字不变，理由变了）
- [x] 5.4 `run_all()` 数字不变：`sample 19/27`、`billing 23/27`
  - 但 detail 从"v3 装置"变成"v2 装置产物，当前为 v3"
- [ ] 5.5 归档

## 6. 不在本变更范围

- [ ] `F24` 的 v3 判据（如"A 轴 SEH@1 不得低于随机基线"）
  - 需要 v3 数据才能定阈值
  - **显式登记为"未做"，不是遗漏**
