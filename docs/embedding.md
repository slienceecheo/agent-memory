# Embedding：`qwen3.7-text-embedding-flash`

本文记录的是**实测结论**，不是文档抄录。所有数字都可以用文末命令复现。

## 配置

```env
DASHSCOPE_API_KEY=sk-...
EMBEDDING_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
EMBEDDING_MODEL=qwen3.7-text-embedding-flash
EMBEDDING_DIMS=1024
```

## 四个必须知道的实测事实

### 1. 只有北京端点可用

```bash
# 通
curl -s -o /dev/null -w "%{http_code}\n" https://dashscope.aliyuncs.com/compatible-mode/v1/embeddings
# 401（同一个 key 也不行）
curl -s -o /dev/null -w "%{http_code}\n" https://dashscope-intl.aliyuncs.com/compatible-mode/v1/embeddings
```

`dashscope-intl` 会返回 `invalid_api_key`，即使 key 本身有效。**不要照抄网上基于
国际站的示例。**

### 2. `text_type` 显著影响向量，必须分开用

同一段文本，分别以 `document` 和 `query` 编码，余弦相似度只有 **0.842**。

```bash
uv run python - <<'PY'
import os, numpy as np, httpx
base = "https://dashscope.aliyuncs.com/compatible-mode/v1/embeddings"
key = os.environ["DASHSCOPE_API_KEY"]
def emb(text_type):
    r = httpx.post(base, headers={"Authorization": f"Bearer {key}"}, json={
        "model": "qwen3.7-text-embedding-flash",
        "input": ["怎么配置项目"], "dimensions": 1024, "text_type": text_type,
    }, timeout=60).json()
    return np.asarray(r["data"][0]["embedding"], dtype=np.float32)
q, d = emb("query"), emb("document")
print("cos =", float(q @ d / (np.linalg.norm(q) * np.linalg.norm(d))))
PY
# cos = 0.842074
```

所以入库一律 `document`，检索一律 `query`，缓存键里也必须包含 `text_type`
（否则查询向量会污染文档向量，且完全不可见）。

### 3. 同一文本重复调用不保证逐位一致

连续 6 次编码同一句话，出现了 **3 个不同的向量变体**：

```
run1 vs run2: 0.997622
run2 vs run3: 1.000000
run2 vs run6: 0.997959
```

同变体完全一致（余弦 1.0），跨变体 **0.9976**。推测是网关后面挂着多个后端节点，
量化实现略有差异。

**这条直接决定了架构**：缓存不是性能优化，而是可复现性的前提。没有缓存，
重跑评测会得到略微不同的分数，"同一 seed 指标逐位一致"就不成立。

### 4. 批大小比文档宽

官方标称单批最多 20 条；实测 21 条可通过。实现按 **10 条**一批保守分片，
留出余量给服务端调整。

## 实现要点

| 位置 | 约定 |
|---|---|
| `memory/embedding/cache_keys.py` | 键 = `sha256(model \| dims \| text_type \| text)`，字段间用 `\x1f` 分隔防串味 |
| `memory/embedding/cache.py` | SQLite 存 float32 裸字节；长度不符视为损坏，返回未命中并记账 |
| `memory/embedding/dashscope.py` | 分片自动；按 `index` 归位；任一分片失败整体失败；失败不写缓存 |

## 已验证的行为

```bash
# 单元测试（用假传输层，不打网络）
uv run pytest tests/test_embedder.py tests/test_cache.py tests/test_cache_key.py -q

# 真实网络冒烟（默认跳过）
uv run pytest tests/test_embedder_live.py -q -m network
```

第二条会验证：维度等于配置值、`query` 与 `document` 编码确实不同（余弦 < 0.999）。
后者是防回归的关键——如果哪天服务端忽略 `text_type`，这条测试会失败。
