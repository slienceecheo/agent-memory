## 决策 1：登记表改为"从源码派生比对"，不是"再手写一遍"

**备选：把登记表补全，再加一条"登记里的文件都存在"的断言。**

不可行。那只能抓到"文件没了"，抓不到"登记写的是另一个文件"：

```
L6b 登记 a3-with-dedup.json，实际读 a3-lexical-vector-adjacency.json
两个文件都存在 -> 存在性检查全绿 -> 漂移不被发现
```

**所以改用 AST 派生**：

| 写法 | 能抓漂移吗 |
|---|---|
| 手写清单 + 存在性检查 | ❌ |
| 手写清单 + AST 派生比对 | ✅ |

**派生的三条规则**（都是"代码里写了什么"，不是"我以为它读什么"）：

| 模式 | 归入 |
|---|---|
| `_load_run(CONST)` | 写死路径，解析 `CONST` 的值 |
| `ROOT / "results" / "<name>"` | 写死路径 |
| `result_files("<pattern>")` | 发现式，保留 pattern |
| 调用模块内 helper | **递归跟进** |

**为什么必须递归**：`F19b`/`F20` 不直接调 `result_files`，而是经
`_ablation_for_subjects`。只看函数体会把它们漏掉——而它们恰好是能看到 v3 的一族。

## 决策 2：分两族登记，因为"发现方式"决定适用域

| 族 | 门禁 | 能看到 `results/v3/` |
|---|---|---|
| 写死路径 | L6a / L6b / L6c / L8 | ❌ |
| 发现式 | F19b / F20 / F24 | ✅ |

**这不是分类的美学问题**：它直接决定"造完 v3 数据谁来验"的答案。
合并成一张 7 条的清单，会让人读成"7 条都在验"。

**所以计数断言也分组**：总数 7、写死 4、发现 3。
只断言总数时，把一条从写死组挪到发现组不会红，但它的适用域完全变了。

## 决策 3：`_ablation_for_subjects` 优先当前装置，但仍保留回落

```python
if matched:
    for payload, name, sig in matched:
        if sig == CURRENT_APPARATUS:
            return payload, name, sig, "ok"
    return matched[0]        # 没有当前装置产物 -> 保持旧行为
```

**为什么保留回落**：没有 v3 产物时若报"空"，会把"这代还没数据"
（不适用）变成"失败"。三态语义是"不适用不算失败"，不能在这里破例。

**为什么不能改成"按文件名前缀挑"**：`v2-`/`v3-` 是历史命名约定，
而 `result_files()` 的注释已经写明"装置归属由签名判断，不由文件名判断"。
按前缀挑会在有人把 v3 产物命名成别的形式时失效。

## 决策 4：遮蔽的证伪判据是"结论改变"，不是"返回值包含"

**我第一版验证写错了**（记录在此，防止再犯）：

```python
new = m.result_files("*-lexical-vector-adjacency.json")
print(any(x.parent == V3 for x in new))   # True
```

`result_files()` 返回了 v3 路径，但 `_ablation_for_subjects` 仍可能选 v2。
**"能发现文件"与"用了那个文件"是两件事。**

正确的判据：

```python
before = snapshot()
_write_v3_ablation()
after = snapshot()
assert after["F20"] != before["F20"]      # 结论必须改变
assert after["F20"] == (True, True)       # 且必须是"执行并通过"
```

## 决策 5：`test_v3_aware_gates_are_exactly_three` 用源码体判断，不用名单

```python
for fn in m.ALL_CHECKS:
    body = inspect.getsource(fn).split('"""')[-1]   # 跳过 docstring
    if "result_files(" in body or "_ablation_for_subjects(" in body:
        aware.append(code_of(fn))
```

**为什么跳过 docstring**：`L6b` 的 docstring 里写着"与 `SEH@5` 同理"这类文字，
但不含 `result_files`。真正的风险是**实现里没扫 v3 却在 docstring 里提了**——
不跳过就会把"提过"当成"用了"。

**取代号时必须保留大小写**：`f19b` -> `F19b`。
`.upper()` 会给出 `F19B`，与实际代号不符（这是本变更的第一版 bug）。

## Risks / Trade-offs

| 风险 | 缓解 |
|---|---|
| 派生逻辑跟不上代码结构（如新增 helper 层） | 派生的空集与登记比，多一层 helper 只会让派生结果变，比对会红 |
| 优先当前装置可能选错（签名误判） | `apparatus_signature` 的误判方向是安全的：误判成 v3 -> 门禁执行 -> 更严格 |
| 测试会创建/删除 `results/v3/` | `clean_v3` fixture 先备份再还原，测试前后状态一致 |

## 不做的事

- **不改 `_load_run` 的三态**：本轮不讨论"缺文件算失败还是不适用"，
  那是另一个决策，会改 4 条门禁的行为
- **不造 v3 数据**
- **不改 `apparatus_signature` 的判据**
