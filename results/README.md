# 评测结果

这个目录**不入库**（见 `.gitignore`），内容由 `uv run python -m evals.run` 重新生成。

## 为什么不入库

- 结果可以完全重跑得到，占用体积没有收益
- 报告（`docs/reports/c1-baselines.md`）里的每个数字都有测试
  （`tests/test_report_consistency.py`）与结果 JSON 交叉核对，
  所以"提交的数字"由报告承担，而不是由原始文件承担

## 内容

| 文件 | 说明 |
|---|---|
| `{baseline}-{length}-{hop}.json` | 每条基线的逐样本结果（含预测、对错、token 用量） |
| `events-{baseline}-{run_id}.jsonl` | 逐样本追踪事件，字段见 `tests/test_tracer.py` |

## 重新生成

```bash
uv run python -m evals.run --baseline no-memory
uv run python -m evals.run --baseline naive-rag
uv run python -m evals.run --baseline full-context
```
