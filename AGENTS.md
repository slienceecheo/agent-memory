# AGENTS.md

## OpenSpec workflow (required)

- 本项目的系统行为以 `openspec/specs/` 为唯一权威；行为文档与实现必须一致。
- **禁止跳过变更流程**：任何行为修改，先 `/openspec-propose` 建变更，再只通过
  `/openspec-apply` 实施。不允许在没有活动变更的情况下改 `src/` 里的产品行为。
- `tasks.md` 是进度的唯一记录。进度只勾它；遇到需要偏离规格的情况，停下来问，不要自行发挥。
- 归档前必须跑 `openspec validate <change>`；只有通过才能 `/openspec-archive`。
- 实现代码时遵循 TDD：先写会失败的测试，再写实现。遇到 bug 先用
  `systematic-debugging` 找根因，不要靠猜改代码。

## 项目约束（agent 无法从代码推断，必须遵守）

- 产物（proposal / specs / design / tasks / 文档）一律用**中文**写；代码、标识符、commit message 用英文。
- 目标平台：Windows 11 开发，代码需在 macOS / Linux 可运行。路径一律用 `pathlib`，不写死 `/` 或 `\`。
- Python 3.12，用 `uv` 管理依赖与环境。不要用 `pip install` 全局安装。
- 测试用 `pytest`；属性测试用 `hypothesis`。
- 所有网络请求必须**显式支持代理配置但默认直连**：读 `HTTPS_PROXY`/`HTTP_PROXY`，
  未设置时直连。不要把 `127.0.0.1:7897` 硬编码进代码。
- 所有 embedding 调用必须**经过缓存**（键为 `sha256(model|dims|text_type|text)`）。
  原因是上游同文本重复调用不保证逐位一致，缓存是实验可复现的前提。

## 本项目已知的环境陷阱（踩过的坑，不要重复）

1. **DeepSeek 网关强制 SSE**：本地网关 `127.0.0.1:3211` 即使传 `stream: false` 也只
   返回 `data: {...}` 分块。客户端必须收拢 SSE 后再解析，否则拿到空响应。
2. **该网关不提供 embeddings**（401）。向量一律走阿里云 DashScope。
3. **DashScope 只有北京端点可用**：`dashscope.aliyuncs.com`；`dashscope-intl.aliyuncs.com` 401。
4. **`text_type=query/document` 显著影响向量**（同文本余弦仅 0.842），入库用
   `document`，查询用 `query`，不要混用。
5. **embedding 非确定性**：同文本重复调用可能出现不同向量（跨变体余弦 0.9976）。
6. **`api.github.com` 走代理会 403 rate limit**，查版本用 `git ls-remote --tags`。
7. **访问本地网关时必须 `NO_PROXY=127.0.0.1,localhost`**，否则请求被绕进代理失败。

## 反目标（写进规格里，防止跑偏）

- 不引入 Milvus / Qdrant / Neo4j 之类独立向量库服务。
- 不让 LLM 直接决定"覆盖还是保留"却不给规则对照实验。
- 不报单点分数：所有主表必须带置信区间，关键结论必须有消融。
