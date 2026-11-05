# Tasks

## 0. 为什么要有这个变更

在 v2 数据上做特征归因实验（四组权重），得到的结果推翻了我前两轮的判断。

**原本我要写的**是"v3 数据的设计约束：让 authority 有区分度"。
**那是错的**——等于把 v2 已登记的 `condition` 直通缺陷在新特征上重造一遍。

**改成写能力边界**：v3 能测什么、不能测什么、数据侧不得做什么。

## 1. 特征归因实验（不造新数据）

- [x] 1.1 四组权重对比（sample / billing，派生 within 的 SEH@1）

  | 组合 | 权重 | sample | billing |
  |---|---|---|---|
  | A 只有 base | 1.0/0/0 | 0.2000 | 0.1667 |
  | B 只有 authority | 0/1.0/0 | 0.4000 | 0.1667 |
  | C 只有 status | 0/0/1.0 | 0.2000 | 0.1667 |
  | D base=auth | 0.5/0.5/0 | 0.3000 | 0.1667 |
  | G 全开 | 0.4/0.3/0.3 | 0.3000 | **0.0833** |

- [x] 1.2 **修正自己的方法缺陷**：第一版对比 D 与 G 得出"加 status 有害"
  - 那是错的：`base:authority` 从 1:1 变成 4:3，变化来自**权重再分配**
  - 正确对照：保持 1:1，只加 status
    ```
    D (0.50/0.50/0.00) -> 0.3000 / 0.1667
    E (0.45/0.45/0.10) -> 0.3000 / 0.1667   逐条相同
    F (0.35/0.35/0.30) -> 0.3000 / 0.1667   逐条相同
    ```
  - **结论：status 完全中性**

- [x] 1.3 验证 `rrf_norm` 严格单调
  - 输入 `[0, 0.1, 0.5, 1.0, 2.0, 5.0]` -> 输出 `[0, .02, .1, .2, .4, 1.0]`
  - **所以 base == 融合顺序**，`base-only = 0.20` 是融合顺序的 top-1 率

## 2. 核心实测：authority 是过滤器，不是信号

- [x] 2.1 gold 的 authority 与干扰项比较

  | 量 | sample | billing |
  |---|---|---|
  | gold 唯一最高 | **0/10** | **0/12** |
  | gold 并列最高 | 8/10 | 10/12 |
  | gold 低于最高 | 2/10 | 2/12 |
  | gold mean − distractor mean | **−0.0244** | **+0.0213** |

  **sample 上 gold 反而更低**——它不是靠权威赢的。

- [x] 2.2 决定性判据：同层逆序

  ```
  sample  同层逆序 0/10
  billing 同层逆序 0/12
  合计    0/22
  ```

  **层内相对顺序与融合顺序完全一致** -> authority 只分层，层内裁决由融合顺序完成。

  - 第一次实现算错（用 `pool_tag_meta` 找 gold tag 失败），已修正
  - 第二次把非 within 的 `ledger-q11/q12` 也算进去，总数 24 而非 22，已修正

## 3. 写测试（10 条）

- [x] 3.1 三条边界

  | 断言 | 判据 |
  |---|---|
  | `test_status_has_no_variance_in_pools` | 池内方差 == 0 |
  | `test_rrf_norm_is_strictly_monotonic` | 严格递增 |
  | `test_base_only_equals_fusion_order` | base 名次 == 融合名次 |
  | `test_authority_is_a_filter_not_a_signal` | 同层逆序 == 0（22 个 case） |
  | `test_auth_only_top1_is_earliest_in_top_tier` | 10/10、12/12 |

- [x] 3.2 防泄漏守卫

  | 断言 | 判据 |
  |---|---|
  | `test_gold_authority_has_no_systematic_advantage` | `|差| < 0.05` |
  | `test_no_case_has_gold_as_unique_top_authority` | 唯一最高 == 0 |
  | `test_leak_guard_passes_on_real_data` | 真实数据上两条都绿 |

- [x] 3.3 守卫必须可被违反

  | 断言 | 作用 |
  |---|---|
  | `test_leak_guard_catches_doctored_pool` | 构造 gold 唯一最高 -> 判据红 |

  **关键**：判据委托给 `_assert_no_unique_top` / `_assert_authority_no_bias`，
  真实测试调的是同一个函数。所以"证明它会红"验证的是**真实的判据**。

  **上一版写错了**：
  ```python
  with pytest.raises(AssertionError):
      assert stats["unique_top"] == 0, "模拟断言"
  ```
  那是 `assert False`，**必然抛**，与被测对象无关——恒真断言的反面（永远红）。
  已改成调用真实 helper。

- [x] 3.4 合成结论

  | 断言 | 作用 |
  |---|---|
  | `test_three_features_have_no_semantic_signal` | 三个性质都在 |

## 4. 双向证伪（9 个方向全部符合预期）

| 组 | 构造 | 期望 | 实测 |
|---|---|---|---|
| A | gold 唯一最高 authority | 红 | 红（"1/3 个 case 的 gold 是唯一最高"） |
| B | gold 平均明显更高 | 红 | 红（"差 +0.3400 超过阈值 0.05"） |
| C | **gold 平均更低**（−0.0244 那种） | **绿** | **绿** |
| D | 构造的真实 per_case 走 `_authority_stats` | unique_top==1 且 diff>0.05 | 是 |
| E | `rrf_norm` 恒为 0.5 | 红 | 红（"不严格递增：0.5 -> 0.5"） |
| F | 恢复 `rrf_norm` | 绿 | 绿 |
| G | 构造同层逆序的 case | 检出 1/1 | 1/1 |
| H | **保序的 case** | **不误报 0/1** | **0/1** |
| I | status 有方差 | 会红 | 是 |

**C 和 H 是双向验证**：不只"改坏了会红"，还要"没改坏不会红"。

## 5. 验收

- [x] 5.1 `openspec validate v3-apparatus-capability-boundary --strict` 通过
- [x] 5.2 **归档前**跑 `openspec validate --all --strict`
- [x] 5.3 全量测试通过
- [x] 5.4 归档

## 6. 不在本变更范围

- **不造 v3 数据**
- **不改权重**：`PREREGISTERED_WEIGHTS` 是预注册的，事后改是 HARKing
- **不加第四特征**（如 vector 余弦）：那是装置变更，且要先确认它不与 gold 相关
- **不改任何门禁判据**

