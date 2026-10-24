# Tasks

> TDD 顺序：每组先写会失败的测试，再写实现。
> 环境约束见 `AGENTS.md`；设计决策见 `design.md`。

## 1. 项目骨架

- [x] 1.1 用 `uv` 初始化项目（`pyproject.toml` 中 Python 3.12、`src` 布局），
      添加依赖 `httpx pydantic numpy pytest hypothesis ruff mypy`，
      验证：`uv sync` 成功，`uv run python -c "import memory"` 无报错
- [x] 1.2 建立目录骨架 `src/memory/{embedding,llm,tracing,eval}`、`evals/`、`tests/`、
      `data/cache/`，每个包加 `__init__.py`，
      验证：`uv run python -c "from memory import embedding, llm, tracing, eval"` 通过
- [x] 1.3 配置 `ruff` 与 `mypy`（strict 模式、排除 `evals/` 的宽松检查），
      验证：`uv run ruff check` 与 `uv run mypy src` 均以 0 退出

## 2. 配置与密钥

- [x] 2.1 先写测试：`Settings` 在缺少 `DASHSCOPE_API_KEY` 时抛出可读错误、
      在设置代理变量时正确透传给 httpx 客户端、`NO_PROXY` 含 `127.0.0.1` 时本地地址不走代理，
      验证：`uv run pytest tests/test_settings.py -q` 全绿
- [x] 2.2 实现 `memory/config.py`（读取 `.env`、校验必填项、默认值集中管理），
      验证：`uv run pytest tests/test_settings.py -q` 全绿且 `uv run mypy src` 无错

## 3. Embedding 与缓存

- [x] 3.1 先写测试：缓存键对 `(model, dims, text_type, text)` 四个字段敏感——
      改任一字段产生不同键，四者相同则键相同，
      验证：`uv run pytest tests/test_cache_key.py -q` 全绿
- [x] 3.2 实现 `memory/embedding/cache.py`（SQLite 存 float32 二进制 + 元数据，
      损坏条目视为未命中并告警），
      验证：`uv run pytest tests/test_cache.py -q` 覆盖命中/未命中/损坏/批量部分命中四种情形
- [x] 3.3 先写测试：`DashScopeEmbedder` 对同一批文本返回顺序一致的向量、
      维度不符时报错、非法 `text_type` 在发请求前被拒，
      验证：`uv run pytest tests/test_embedder.py -q` 全绿（用 mock 传输层，不打真实网络）
- [x] 3.4 实现 `memory/embedding/dashscope.py`（OpenAI 兼容端点、`text_type` 区分
      query/document、批大小 10 自动分片、分片失败整体失败），
      验证：`uv run pytest tests/test_embedder.py -q` 全绿
- [x] 3.5 加一个真实网络冒烟测试（`-m network` 标记，默认跳过），
      对 `qwen3.7-text-embedding-flash` 编码两条中文短句，
      验证：`uv run pytest tests/test_embedder_live.py -q -m network` 通过并输出维度 1024
- [x] 3.6 编写 `docs/embedding.md`，记录北京端点限制、`text_type` 的影响（同文本余弦 0.842）、
      实测非确定性（跨变体 0.9976）与缓存策略，
      验证：文档中的命令按原样可执行

## 4. LLM 客户端与 SSE 收拢

- [x] 4.1 先写测试：对四种分块形态（单块完整、多块拼接、带 `[DONE]`、中断）的解析结果，
      验证：`uv run pytest tests/test_sse.py -q` 全绿，中断场景断言抛出特定异常
- [x] 4.2 实现 `memory/llm/sse.py`（按行解析 `data:`、拼接 delta、处理 `[DONE]`），
      验证：`uv run pytest tests/test_sse.py -q` 全绿
- [x] 4.3 先写测试：响应含 `reasoning_content` 时正文不含推理、`reasoning_tokens` 被统计、
      只有推理无正文时报错并保留原文，
      验证：`uv run pytest tests/test_llm_reasoning.py -q` 全绿
- [x] 4.4 实现 `memory/llm/client.py`（强制 `stream` 收拢、丢弃推理正文、统计浪费比例、
      网络错误分类与固定退避重试），
      验证：`uv run pytest tests/test_llm_client.py -q` 覆盖限流重试、鉴权不重试、重试耗尽
- [x] 4.5 加真实网关冒烟测试（`-m network`），发一次 `stream=false` 请求并断言能拿到正文，
      验证：`uv run pytest tests/test_llm_live.py -q -m network` 通过
- [x] 4.6 编写 `docs/llm-gateway.md`，记录"强制 SSE"现象的复现命令与收拢策略，
      验证：文档中的 curl/httpx 片段可执行且结论一致

## 5. 追踪

- [x] 5.1 先写测试：`JsonlTracer` 每条事件含 `run_id/sample_id/stage/duration_ms/
      network_calls/error` 且可被 JSON Schema 校验，
      验证：`uv run pytest tests/test_tracer.py -q` 全绿
- [x] 5.2 实现 `memory/tracing/jsonl.py` + `memory/tracing/base.py`（`Tracer` 协议），
      验证：`uv run pytest tests/test_tracer.py -q` 全绿
- [x] 5.3 在 embedding 与 LLM 客户端挂计数器，使"本次运行的网络调用数"可被断言，
      验证：`uv run pytest tests/test_network_counter.py -q`——缓存全命中时计数为 0

## 6. 指标与置信区间

- [x] 6.1 先写测试：`substring_exact_match` 覆盖完全一致、大小写空白、包含额外说明、
      空预测、空标准答案、中文六种情形，
      验证：`uv run pytest tests/test_metrics.py -q` 全绿
- [x] 6.2 实现 `memory/eval/metrics.py`，
      验证：`uv run pytest tests/test_metrics.py -q` 全绿
- [x] 6.3 先写测试：配对 bootstrap 在全对、各半、n=1、同种子可复现四种情形下的输出，
      验证：`uv run pytest tests/test_bootstrap.py -q` 全绿
- [x] 6.4 实现 `memory/eval/bootstrap.py`（10000 次重采样、配对差值、可配置种子），
      验证：`uv run pytest tests/test_bootstrap.py -q` 全绿

## 7. 数据集适配

- [x] 7.1 先写测试：本地文件存在时正确加载 6K 单跳子集、事实序号保留且单调、
      不存在的子集报错并列出可用值，
      验证：`uv run pytest tests/test_factconsolidation.py -q` 全绿（用 3 条手造样本的 fixture）
- [x] 7.2 实现 `evals/datasets/factconsolidation.py`（本地优先，
      缺失时打印下载链接与校验和提示，不自动联网），
      验证：`uv run pytest tests/test_factconsolidation.py -q` 全绿
- [x] 7.3 编写 `docs/datasets.md`，记录数据来源、许可证状态与放置路径约定，
      验证：按文档放置后 7.1 的测试可在真实数据上运行

## 8. 三条基线

- [x] 8.1 先写测试：三条基线共用同一 `answer()` 与同一匹配逻辑，
      用假 LLM 返回固定答案时三者预测完全相同，
      验证：`uv run pytest tests/test_baselines.py -q` 全绿
- [x] 8.2 实现 `evals/baselines/{no_memory,full_context,naive_rag}.py` 与共享的 `answer()`，
      验证：`uv run pytest tests/test_baselines.py -q` 全绿
- [x] 8.3 先写测试：结果 JSON 含逐样本记录与 token 用量、失败样本被标记而非丢弃、
      未知基线名报错并列出可用项，
      验证：`uv run pytest tests/test_run_result.py -q` 全绿
- [x] 8.4 实现 `evals/run.py` 命令行入口（`--bench/--baseline/--limit/--out`），
      验证：`uv run python -m evals.run --help` 正常输出

## 9. 集成与交付

- [x] 9.1 跑通三条基线并提交结果与缓存：`uv run python -m evals.run --bench
      factconsolidation --baseline {no-memory,full-context,naive-rag}`，
      验证：`results/` 下三份 JSON 存在，且表格中 naive-rag 优于 no-memory
- [x] 9.2 验证可复现：相同参数连续跑两次，
      验证：两次指标 JSON 逐位相同，且第二次 `network_calls` 为 0
- [x] 9.3 实现 `--check-cache` 子命令（输出条目数、命中率、缺失项，缺失时非零退出），
      验证：`uv run python -m evals.run --check-cache` 在完整缓存下退出码 0，
      手动删一条后退出码非 0
- [x] 9.4 生成基线报告 `docs/reports/c1-baselines.md`（三行结果 + 置信区间 + 样本数 +
      reasoning 浪费比例），
      验证：报告中的数字与 `results/` 下 JSON 一致，可用脚本比对
- [x] 9.5 全量门禁：`uv run pytest -q`、`uv run ruff check`、`uv run mypy src`
      与 `openspec validate eval-harness-baseline`，
      验证：四条命令均以 0 退出并贴出原始输出

## Workflow follow-up

- 审稿通过后归档该变更，确认 `openspec list` 无活动变更。
