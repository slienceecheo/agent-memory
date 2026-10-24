# LLM 网关：DeepSeek V4.1 Flash

本地网关 `http://127.0.0.1:3211/api/open-platform-model/v1` 是 OpenAI 兼容的，
但有三处与官方不一致，必须适配。

## 事实 1：强制返回 SSE，无视 `stream=false`

```bash
curl -s http://127.0.0.1:3211/api/open-platform-model/v1/chat/completions \
  -H "Authorization: Bearer local" -H "Content-Type: application/json" \
  -d '{"model":"deepseek-v4.1-flash","stream":false,
       "messages":[{"role":"user","content":"Reply: PONG"}]}' | head -3
```

即便 `stream` 显式设为 `false`，返回的仍是：

```
data:{"id":"chatcmpl-...","choices":[{"index":0,"delta":{}}]}
data:{"id":"chatcmpl-...","choices":[{"index":0,"delta":{"content":"P"}}]}
```

**后果**：用 OpenAI SDK 的普通（非流式）调用会拿到空正文。这是最容易踩且最难查的坑——
不报错，只是结果为空。

**对策**：`memory/llm/client.py` 一律以 `stream: true` 请求，交给
`memory/llm/sse.py` 收拢。收拢器只依赖两个约定：`data:` 前缀与 `[DONE]` 标记。

如果 `[DONE]` 没出现，**必须抛错**而不是返回已收到的部分正文。截断正文会让抽取层
静默产出半句话并写进记忆库，那种脏数据比直接失败难查一个数量级。

## 事实 2：每次都会先输出 `reasoning_content`

实测一次"提取事实"的调用：推理 98 token，正文只有 14 token。
思考过程以 `delta.reasoning_content` 分片下发，正文在 `delta.content`。

**决策：丢弃推理内容，只统计其 token 数。**

理由：
- 推理内容不稳定，同样输入两次可能给出不同思考路径
- 把它纳入任何决策路径都会让"缓存后重跑逐位一致"失效
- 但"浪费比例"本身是有价值的成本分析数据

`LLMResult.reasoning_waste_ratio = reasoning_tokens / completion_tokens`。
若 `completion_tokens` 为 0 返回 0，而不是抛零除。

**边界：只有推理、没有正文时抛 `ReasoningOnlyError`**，并把推理内容前 200 字符
带在错误信息里，否则无从排查模型到底在想什么。

## 事实 3：`tool_calls` 可用

抽取层计划用 function calling 而不是"让模型输出 JSON 再解析"。实测通过：

```python
tools = [{"type": "function", "function": {
    "name": "record_memory",
    "description": "记录一条记忆事实",
    "parameters": {"type": "object", "properties": {
        "subject": {"type": "string"},
        "relation": {"type": "string"},
        "value": {"type": "string"},
    }, "required": ["subject", "relation", "value"]},
}}]
```

工具调用的 `arguments` 是**分片下发**的，必须按 `index` 累积拼接，
否则会拿到残缺 JSON。

## 错误处理策略

| 状态 | 是否重试 | 理由 |
|---|---|---|
| 408 / 409 / 425 / 429 | 是 | 瞬时 |
| 500 / 502 / 503 / 504 | 是 | 服务端故障 |
| 400 / 401 / 403 / 404 | 否 | 参数或配置错误，重试只是浪费配额 |
| 传输错误（连接失败、超时） | 是 | 网络抖动 |

重试退避为指数（`backoff * 2**attempt`），默认最多 3 次。
耗尽后抛 `RetryExhaustedError`，消息里带总尝试次数与最后一次的原始错误。

## 代理注意

访问 `127.0.0.1` 时必须绕过代理，否则请求会被送到 Clash 然后失败。
`memory/config.py` 会把 `127.0.0.1`、`localhost`、`::1` 强制并入 `NO_PROXY`，
即使用户自己配置的 `NO_PROXY` 没写它们。

## 已验证

```bash
# 假传输层的单元测试（13 条，覆盖重试/推理/工具调用）
uv run pytest tests/test_llm_client.py tests/test_sse.py -q

# 真实网关冒烟（默认跳过）
uv run pytest tests/test_llm_live.py -q -m network
```
