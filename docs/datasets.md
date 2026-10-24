# 数据集：FactConsolidation

## 来源与许可

| 项 | 值 |
|---|---|
| 来源 | [ai-hyz/MemoryAgentBench](https://huggingface.co/datasets/ai-hyz/MemoryAgentBench) |
| 许可 | **MIT**（HuggingFace dataset card 标注） |
| 文件 | `data/Conflict_Resolution-00000-of-00001.parquet`（约 1.4 MB） |
| 下载 | 需代理（本机 `127.0.0.1:7897`） |

**因为 MIT 允许再分发，但 1.4MB 的二进制不适合进 git**，所以策略是：
数据不进仓库，提供下载命令；缓存与结果进仓库（体积小、可核对）。

## 放置路径

```
data/raw/Conflict_Resolution.parquet
```

下载命令（PowerShell，需代理）：

```powershell
$env:HTTPS_PROXY="http://127.0.0.1:7897"
New-Item -ItemType Directory -Force data/raw | Out-Null
Invoke-WebRequest `
  "https://huggingface.co/datasets/ai-hyz/MemoryAgentBench/resolve/main/data/Conflict_Resolution-00000-of-00001.parquet" `
  -OutFile data/raw/Conflict_Resolution.parquet
```

## 真实结构（2026-10-24 实测）

一个 parquet 只有 **8 行**，每行是一个"子集"，不是一条样本：

| 行 | source | 上下文长度 | 问题数 |
|---|---|---|---|
| 0 | `factconsolidation_mh_6k` | 26,157 字符 | 100 |
| 1 | `factconsolidation_mh_32k` | 136,565 字符 | 100 |
| 2 | `factconsolidation_mh_64k` | 273,473 字符 | 100 |
| 3 | `factconsolidation_mh_262k` | 1,118,123 字符 | 100 |
| 4 | `factconsolidation_sh_6k` | 26,157 字符 | 100 |
| 5 | `factconsolidation_sh_32k` | 136,565 字符 | 100 |
| 6 | `factconsolidation_sh_64k` | 273,473 字符 | 100 |
| 7 | `factconsolidation_sh_262k` | 1,118,123 字符 | 100 |

每行的 `context` 形如：

```
Here is a list of facts:
0. Thomas Kyd was born in the city of London.
1. The chairperson of Fatah is Mahmoud Abbas.
...
454. The name of the current head of the Tucson government is Jonathan Rothschild.
```

6K 子集含 **455 条事实**（编号 0–454），每个子集有 100 个问题、100 个标准答案。

`metadata` 里的字段：
- `source`：如 `factconsolidation_sh_6k`
- `qa_pair_ids`：如 `factconsolidation_sh_6k_no0`，**跨运行对齐结果的主键**
- `question_types`：本数据集为 `None`（SH/MH 的区分在 source 里）

`answers` 是**列表的列表**（每个问题可能有多个可接受答案）。

## 三个容易踩的点

### 1. "新旧"由编号决定，不是列表位置

编号越大越新。这一点必须映射到 `ordinal` 字段，**不能用 `recorded_at`**——
真实时间在数据里不存在。

### 2. `factconsolidation_sh_6k` 按 `_` 切分只有 3 段

`factconsolidation` 本身不含下划线。写成 `len(parts) < 4` 会直接把所有合法子集
判为非法（我在实现时踩过）。

### 3. `answers` 是嵌套列表

`[["Paris"], ["London"]]` 而不是 `["Paris", "London"]`。当成扁平列表会让答案
错位一位，且分数看起来"还行"——最难查的那类 bug。

## 已锁定的行为

`tests/test_factconsolidation.py` 里有一条直接跑真实数据的断言（数据缺失时自动跳过）：

```python
assert len(sample.facts) == 455
assert sample.facts[-1].ordinal == 454
assert len(sample.questions) == 100
```

这条测试的价值：如果哪天换了数据版本导致事实数或问题数变化，它会立刻失败，
而不是静默地让报告数字变得不可比。

## 与论文数字的关系

论文里 FactConsolidation-SH 的对比表（Mem0 18.0%、BM25 48.0%、HippoRAG-v2 54.0%、
手写 resolver 80.25%）是在这个数据集上跑的。我们的适配器必须与它完全对齐，
否则复现出来的基线分数无从比较。

**C1 的职责只是把 6K + SH 这一格跑通**；32K / 64K / 262K 与 MH 留到 C5。
