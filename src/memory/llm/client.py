"""LLM 客户端。

关键行为：
1. 总是以流式请求，交给 SSE 收拢器拼装——因为本地网关无视 `stream=false`。
2. 丢弃推理内容，但统计其 token 数，用于报告"推理浪费比例"。
3. 只对可重试错误（429 / 5xx / 传输错误）重试。
"""

from __future__ import annotations

import time
from collections.abc import Sequence
from dataclasses import dataclass, field

import httpx

from memory.config import Settings
from memory.llm.sse import ToolCall, Usage, collect

_RETRYABLE_STATUS = frozenset({408, 409, 425, 429, 500, 502, 503, 504})


class LLMError(RuntimeError):
    """LLM 调用失败的基类。"""


class ReasoningOnlyError(LLMError):
    """模型只输出了推理内容，没有正文。"""


class RetryExhaustedError(LLMError):
    """重试次数耗尽。"""


@dataclass(frozen=True, slots=True)
class Message:
    role: str
    content: str


@dataclass(frozen=True, slots=True)
class LLMResult:
    content: str
    usage: Usage
    finish_reason: str | None
    tool_calls: list[ToolCall] = field(default_factory=list)
    retries: int = 0

    @property
    def reasoning_waste_ratio(self) -> float:
        """推理 token 占全部生成 token 的比例。分母为 0 时返回 0。"""
        if self.usage.completion_tokens <= 0:
            return 0.0
        return self.usage.reasoning_tokens / self.usage.completion_tokens


class LLMClient:
    def __init__(
        self,
        *,
        settings: Settings,
        client: httpx.Client | None = None,
        max_retries: int = 3,
        backoff_seconds: float = 1.0,
    ) -> None:
        self._settings = settings
        self._client = client or httpx.Client(
            timeout=120.0,
            proxy=settings.https_proxy or settings.http_proxy or None,
        )
        self._max_retries = max_retries
        self._backoff_seconds = backoff_seconds
        self.network_calls = 0

    def complete(
        self,
        messages: Sequence[Message | dict[str, str]],
        *,
        tools: Sequence[dict[str, object]] | None = None,
        temperature: float = 0.0,
        response_format: dict[str, object] | None = None,
    ) -> LLMResult:
        payload: dict[str, object] = {
            "model": self._settings.llm_model,
            "messages": [self._normalize(message) for message in messages],
            "temperature": temperature,
            "stream": True,
        }
        if tools:
            payload["tools"] = list(tools)
            payload["tool_choice"] = "auto"
        if response_format is not None:
            payload["response_format"] = response_format

        last_error: Exception | None = None
        attempts = self._max_retries + 1

        for attempt in range(attempts):
            try:
                return self._attempt(payload, retries=attempt)
            except httpx.HTTPStatusError as exc:
                last_error = exc
                if exc.response.status_code not in _RETRYABLE_STATUS:
                    raise
                if attempt == attempts - 1:
                    raise RetryExhaustedError(
                        f"重试 {attempts} 次后仍失败（最后一次：HTTP "
                        f"{exc.response.status_code}），请检查网关是否可用。"
                    ) from exc
            except httpx.TransportError as exc:
                last_error = exc
                if attempt == attempts - 1:
                    raise RetryExhaustedError(
                        f"重试 {attempts} 次后仍失败（最后一次：{exc}），请检查网关是否可用。"
                    ) from exc
            if self._backoff_seconds:
                time.sleep(self._backoff_seconds * (2**attempt))

        raise RetryExhaustedError(f"重试 {attempts} 次后仍失败：{last_error}")

    def _attempt(self, payload: dict[str, object], *, retries: int) -> LLMResult:
        self.network_calls += 1
        response = self._client.post(
            f"{self._settings.llm_base_url.rstrip('/')}/chat/completions",
            headers={
                "Authorization": f"Bearer {self._settings.llm_api_key}",
                "Content-Type": "application/json",
                "Accept": "text/event-stream",
            },
            json=payload,
        )
        if response.status_code >= 400:
            response.raise_for_status()

        collected = collect(response.text)
        if not collected.content.strip() and not collected.tool_calls:
            raise ReasoningOnlyError(
                f"模型只输出推理内容，正文为空（推理 {collected.usage.reasoning_tokens} "
                f"token）。原始推理：{collected.reasoning[:200]!r}"
            )

        return LLMResult(
            content=collected.content,
            usage=collected.usage,
            finish_reason=collected.finish_reason,
            tool_calls=collected.tool_calls,
            retries=retries,
        )

    @staticmethod
    def _normalize(message: Message | dict[str, str]) -> dict[str, str]:
        if isinstance(message, Message):
            return {"role": message.role, "content": message.content}
        return {"role": message["role"], "content": message["content"]}
