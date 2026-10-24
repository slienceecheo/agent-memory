"""A2 的可执行版本：热缓存下重跑必须逐位一致。

这个测试真的会跑一遍评测（用假传输层，不打网络），
然后检查两次结果 JSON 的每个字段都相同。

它守护的破坏：任何人改动 prompt 模板、缓存键、或结果序列化方式，
只要破坏了"重跑一致"，这里就会失败。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx
import pytest
from evals.datasets.factconsolidation import FactConsolidationAdapter

from memory.config import Settings
from memory.llm.cache import ResponseCache
from memory.llm.client import LLMClient
from memory.tracing.jsonl import JsonlTracer

BASE = "http://127.0.0.1:3211/api/open-platform-model/v1"


def _settings(cache_dir: Path) -> Settings:
    return Settings(
        llm_base_url=BASE,
        llm_api_key="local",
        llm_model="deepseek-v4.1-flash",
        dashscope_api_key="sk-test",
        embedding_base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        embedding_model="qwen3.7-text-embedding-flash",
        embedding_dims=4,
        http_proxy=None,
        https_proxy=None,
        no_proxy="127.0.0.1,localhost",
        cache_dir=cache_dir,
    )


class _DeterministicServer:
    """按请求内容返回固定答案，模拟一个"可复现的模型"。"""

    def __init__(self) -> None:
        self.count = 0

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.count += 1
        payload = json.loads(request.content)
        # 对**完整消息列表**算哈希：这样 system prompt 变化也会改变答案，
        # 才能验证缓存键是否真的包含 prompt。
        full = json.dumps(payload["messages"], sort_keys=True, ensure_ascii=False)
        answer = f"A{abs(hash(full)) % 1000}"
        event = {"choices": [{"index": 0, "delta": {"content": answer}}]}
        usage = {
            "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
            "usage": {
                "prompt_tokens": 10,
                "completion_tokens": 5,
                "total_tokens": 15,
                "completion_tokens_details": {"reasoning_tokens": 2},
            },
        }
        body = (
            f"data:{json.dumps(event, ensure_ascii=False)}\n\n"
            f"data:{json.dumps(usage, ensure_ascii=False)}\n\ndata:[DONE]\n\n"
        )
        return httpx.Response(200, content=body.encode())


def _run_once(
    *,
    settings: Settings,
    dataset: Path,
    server: _DeterministicServer,
    out: Path,
    run_id: str,
) -> dict[str, Any]:
    from evals.baselines import build_baseline

    adapter = FactConsolidationAdapter(dataset)
    samples = adapter.load(length="6k", hop="sh")[:2]
    tracer = JsonlTracer(out / f"events-{run_id}.jsonl", run_id=run_id)
    llm = LLMClient(
        settings=settings,
        client=httpx.Client(transport=httpx.MockTransport(server)),
        response_cache=ResponseCache(settings.cache_dir / "responses.db"),
        max_retries=0,
        backoff_seconds=0.0,
    )
    baseline = build_baseline("naive-rag", llm=llm, tracer=tracer, top_k=3)

    results = []
    for sample in samples:
        for question in sample.questions:
            results.append(
                baseline.run(
                    question=question.question,
                    facts=[fact.text for fact in sample.facts],
                    sample_id=question.id,
                    gold=question.answers[0] if question.answers else "",
                )
            )
    payload = {
        "baseline": "naive-rag",
        "samples": [json.loads(item.model_dump_json()) for item in results],
    }
    return payload


@pytest.fixture
def tiny_dataset(tmp_path: Path) -> Path:
    import pyarrow as pa
    import pyarrow.parquet as pq

    context = (
        "Here is a list of facts:\n"
        "0. Amy Winehouse died in the city of Camden Town.\n"
        "1. Hines Ward plays the position of wide receiver.\n"
        "2. Amy Winehouse died in the city of London.\n"
    )
    rows = [
        {
            "context": context,
            "questions": ["Where did Amy Winehouse die?", "Which sport is Hines Ward?"],
            "answers": [["London"], ["wide receiver"]],
            "metadata": {
                "qa_pair_ids": ["factconsolidation_sh_6k_no0", "factconsolidation_sh_6k_no1"],
                "source": "factconsolidation_sh_6k",
                "question_types": None,
            },
        }
    ]
    path = tmp_path / "tiny.parquet"
    pq.write_table(pa.Table.from_pylist(rows), path)
    return path


def test_second_run_is_bitwise_identical_and_offline(
    tmp_path: Path, tiny_dataset: Path
) -> None:
    """热缓存下第二次运行必须：结果完全相同 + 零网络请求。"""
    settings = _settings(tmp_path / "cache")
    server = _DeterministicServer()
    out = tmp_path / "results"
    out.mkdir()

    first = _run_once(
        settings=settings, dataset=tiny_dataset, server=server, out=out, run_id="r1"
    )
    calls_after_first = server.count
    second = _run_once(
        settings=settings, dataset=tiny_dataset, server=server, out=out, run_id="r2"
    )

    assert calls_after_first > 0, "第一次运行应当真的发过请求"
    assert server.count == calls_after_first, "第二次运行不应发起任何网络请求"
    assert second == first, "两次运行的结果必须完全一致"


def test_changing_prompt_breaks_reproducibility_on_purpose(
    tmp_path: Path, tiny_dataset: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """反证：改动 prompt 后必须产生不同缓存键、不同结果。

    如果这条测试通过得"太好"（即改 prompt 后结果仍相同），
    说明缓存键没有包含 prompt，缓存会返回错配的答案。
    """
    import evals.baselines.base as base_module

    settings = _settings(tmp_path / "cache")
    server = _DeterministicServer()
    out = tmp_path / "results"
    out.mkdir()

    before = _run_once(
        settings=settings, dataset=tiny_dataset, server=server, out=out, run_id="r1"
    )

    monkeypatch.setattr(base_module, "SYSTEM_PROMPT", "A completely different instruction.")
    after = _run_once(
        settings=settings, dataset=tiny_dataset, server=server, out=out, run_id="r2"
    )

    assert after != before, "prompt 变了但结果没变，说明缓存键漏掉了 prompt"
    assert server.count > len(before["samples"]), "prompt 变化应当触发新的网络请求"
