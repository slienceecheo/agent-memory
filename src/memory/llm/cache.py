"""LLM 响应缓存。

为什么必须缓存 LLM 响应（而不只缓存 embedding）：
- 基线分数是 LLM 生成的，模型有随机性，重跑必然不同
- A2 要求"两次运行逐位一致"，只有缓存能做到
- 缓存同时避免重复计费

与 embedding 缓存的差别：
- 键必须是**完整请求体的规范化哈希**（含 tools、temperature、response_format）
- 值需要保留 usage 与 tool_calls，否则无法重建 LLMResult
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from memory.llm.sse import ToolCall, Usage

_SCHEMA = """
CREATE TABLE IF NOT EXISTS responses (
    key      TEXT PRIMARY KEY,
    content  TEXT NOT NULL,
    usage    TEXT NOT NULL,
    finish   TEXT,
    tool_calls TEXT NOT NULL
);
"""


@dataclass(frozen=True, slots=True)
class CachedResponse:
    content: str
    usage: Usage
    finish_reason: str | None
    tool_calls: tuple[ToolCall, ...]

    def tool_calls_list(self) -> list[ToolCall]:
        return list(self.tool_calls)


def request_key(payload: dict[str, Any]) -> str:
    """对请求体做规范化哈希。

    排除 `stream`：它只影响传输方式，不影响语义结果。
    其余字段（model / messages / temperature / tools / response_format）全部纳入，
    因为任一变化都可能改变输出。
    """
    canonical = {key: value for key, value in payload.items() if key != "stream"}
    serialized = json.dumps(canonical, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


class ResponseCache:
    def __init__(self, path: Path | str) -> None:
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        import sqlite3

        self._conn = sqlite3.connect(str(self._path))
        self._conn.execute(_SCHEMA)
        self._conn.commit()
        self.corrupt_keys: list[str] = []

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> ResponseCache:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    def put(self, key: str, response: CachedResponse) -> None:
        usage = {
            "prompt_tokens": response.usage.prompt_tokens,
            "completion_tokens": response.usage.completion_tokens,
            "total_tokens": response.usage.total_tokens,
            "reasoning_tokens": response.usage.reasoning_tokens,
        }
        tool_calls = [
            {"id": call.id, "name": call.name, "arguments": call.arguments}
            for call in response.tool_calls
        ]
        with self._conn:
            self._conn.execute(
                "INSERT INTO responses (key, content, usage, finish, tool_calls) "
                "VALUES (?, ?, ?, ?, ?) "
                "ON CONFLICT(key) DO UPDATE SET content=excluded.content, "
                "usage=excluded.usage, finish=excluded.finish, "
                "tool_calls=excluded.tool_calls",
                (
                    key,
                    response.content,
                    json.dumps(usage, ensure_ascii=False),
                    response.finish_reason,
                    json.dumps(tool_calls, ensure_ascii=False),
                ),
            )

    def get(self, key: str) -> CachedResponse | None:
        row = self._conn.execute(
            "SELECT content, usage, finish, tool_calls FROM responses WHERE key = ?", (key,)
        ).fetchone()
        if row is None:
            return None
        content, usage_raw, finish, tools_raw = row
        try:
            usage_data = json.loads(usage_raw)
            tools_data = json.loads(tools_raw)
            usage = Usage(
                prompt_tokens=int(usage_data.get("prompt_tokens", 0)),
                completion_tokens=int(usage_data.get("completion_tokens", 0)),
                total_tokens=int(usage_data.get("total_tokens", 0)),
                reasoning_tokens=int(usage_data.get("reasoning_tokens", 0)),
            )
            tool_calls = tuple(
                ToolCall(
                    id=str(item["id"]),
                    name=str(item["name"]),
                    arguments=str(item["arguments"]),
                )
                for item in tools_data
            )
        except (KeyError, TypeError, ValueError, json.JSONDecodeError):
            if key not in self.corrupt_keys:
                self.corrupt_keys.append(key)
            return None
        return CachedResponse(
            content=content,
            usage=usage,
            finish_reason=finish,
            tool_calls=tool_calls,
        )

    def stats(self) -> tuple[int, int]:
        """返回 (条目数, 损坏数)。"""
        (count,) = self._conn.execute("SELECT COUNT(*) FROM responses").fetchone()
        return int(count), len(self.corrupt_keys)

    def verify_all(self) -> tuple[int, list[str]]:
        rows = self._conn.execute("SELECT key FROM responses").fetchall()
        corrupt: list[str] = []
        for (key,) in rows:
            if self.get(key) is None:
                corrupt.append(key)
        return len(rows), corrupt
