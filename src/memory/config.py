"""集中式配置。

设计要点：
- `from_env()` 只读 `os.environ`，不碰 `.env`，让测试完全隔离。
- `load()` 负责先加载 `.env` 再委托给 `from_env()`。
- 关键项缺失时立即失败，而不是跑到一半 401。
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[2]

_LOOPBACK_HOSTS = ("127.0.0.1", "localhost", "::1")


class MissingSettingError(RuntimeError):
    """配置缺失或非法。消息必须点名变量并给出补救动作。"""


def _require(env: Mapping[str, str], name: str, hint: str) -> str:
    value = (env.get(name) or "").strip()
    if not value:
        raise MissingSettingError(f"缺少环境变量 {name}。{hint}")
    return value


def _optional(env: Mapping[str, str], name: str) -> str | None:
    value = (env.get(name) or "").strip()
    return value or None


def _positive_int(env: Mapping[str, str], name: str, default: str) -> int:
    raw = (env.get(name) or default).strip()
    try:
        value = int(raw)
    except ValueError as exc:
        raise MissingSettingError(f"环境变量 {name} 必须是正整数，当前为 {raw!r}。") from exc
    if value <= 0:
        raise MissingSettingError(f"环境变量 {name} 必须是正整数，当前为 {raw!r}。")
    return value


def _no_proxy(env: Mapping[str, str]) -> str:
    """用户配置与回环地址合并：本地网关永远不能被绕进代理。"""
    configured = [item.strip() for item in (env.get("NO_PROXY") or "").split(",") if item.strip()]
    merged: list[str] = []
    for item in [*configured, *_LOOPBACK_HOSTS]:
        if item not in merged:
            merged.append(item)
    return ",".join(merged)


@dataclass(frozen=True, slots=True)
class Settings:
    llm_base_url: str
    llm_api_key: str
    llm_model: str
    dashscope_api_key: str
    embedding_base_url: str
    embedding_model: str
    embedding_dims: int
    http_proxy: str | None
    https_proxy: str | None
    no_proxy: str
    cache_dir: Path

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> Settings:
        source: Mapping[str, str] = os.environ if env is None else env
        cache_env = _optional(source, "MEMORY_CACHE_DIR")

        return cls(
            llm_base_url=_require(
                source,
                "LLM_BASE_URL",
                "参考 .env.example 配置本地网关地址。",
            ),
            llm_api_key=_require(source, "LLM_API_KEY", "本地网关通常填 local。"),
            llm_model=_require(source, "LLM_MODEL", "例如 deepseek-v4.1-flash。"),
            dashscope_api_key=_require(
                source,
                "DASHSCOPE_API_KEY",
                "请在 .env 中填写阿里云百炼 API Key（仅北京端点可用）。",
            ),
            embedding_base_url=_require(
                source,
                "EMBEDDING_BASE_URL",
                "必须使用 https://dashscope.aliyuncs.com/compatible-mode/v1。",
            ),
            embedding_model=_require(
                source,
                "EMBEDDING_MODEL",
                "例如 qwen3.7-text-embedding-flash。",
            ),
            embedding_dims=_positive_int(source, "EMBEDDING_DIMS", "1024"),
            http_proxy=_optional(source, "HTTP_PROXY"),
            https_proxy=_optional(source, "HTTPS_PROXY"),
            no_proxy=_no_proxy(source),
            cache_dir=Path(cache_env) if cache_env else PROJECT_ROOT / "data" / "cache",
        )

    @classmethod
    def load(cls, dotenv_path: Path | None = None) -> Settings:
        load_dotenv(dotenv_path or PROJECT_ROOT / ".env", override=False)
        return cls.from_env()


def configure_directories(settings: Settings) -> None:
    """确保缓存目录存在。创建失败时立刻报错，而不是等到写缓存时。"""
    settings.cache_dir.mkdir(parents=True, exist_ok=True)
