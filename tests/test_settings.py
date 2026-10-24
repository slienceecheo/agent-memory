"""Settings 的行为契约。

每个测试都对应一个具体的破坏：如果生产代码删掉对应分支，该测试必须失败。
"""

from __future__ import annotations

import pytest

from memory.config import MissingSettingError, Settings


def _env(**overrides: str) -> dict[str, str]:
    """一份最小可用的环境变量，测试按需覆盖。"""
    base = {
        "DASHSCOPE_API_KEY": "sk-test",
        "LLM_BASE_URL": "http://127.0.0.1:3211/api/open-platform-model/v1",
        "LLM_API_KEY": "local",
        "LLM_MODEL": "deepseek-v4.1-flash",
        "EMBEDDING_BASE_URL": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "EMBEDDING_MODEL": "qwen3.7-text-embedding-flash",
        "EMBEDDING_DIMS": "1024",
    }
    base.update(overrides)
    return base


def test_missing_dashscope_key_raises_actionable_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """删掉必填校验，此测试失败。错误信息必须点名缺失的变量与补救动作。"""
    env = _env()
    del env["DASHSCOPE_API_KEY"]
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    monkeypatch.delenv("DASHSCOPE_API_KEY", raising=False)

    with pytest.raises(MissingSettingError) as excinfo:
        Settings.from_env()

    message = str(excinfo.value)
    assert "DASHSCOPE_API_KEY" in message
    assert ".env" in message


def test_dims_must_be_positive_integer(monkeypatch: pytest.MonkeyPatch) -> None:
    """把 dims 校验去掉，此测试失败。"""
    for key, value in _env(EMBEDDING_DIMS="0").items():
        monkeypatch.setenv(key, value)

    with pytest.raises(MissingSettingError, match="EMBEDDING_DIMS"):
        Settings.from_env()


def test_dims_rejects_non_numeric(monkeypatch: pytest.MonkeyPatch) -> None:
    """把 int() 的异常吞掉或改成默认值，此测试失败。"""
    for key, value in _env(EMBEDDING_DIMS="big").items():
        monkeypatch.setenv(key, value)

    with pytest.raises(MissingSettingError, match="EMBEDDING_DIMS"):
        Settings.from_env()


def test_loopback_hosts_never_use_proxy(monkeypatch: pytest.MonkeyPatch) -> None:
    """若实现把用户给的 NO_PROXY 覆盖掉，本地网关请求会被绕进代理而失败。"""
    env = _env(HTTPS_PROXY="http://127.0.0.1:7897")
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setenv("NO_PROXY", "example.com")

    settings = Settings.from_env()

    assert "127.0.0.1" in settings.no_proxy
    assert "localhost" in settings.no_proxy
    assert "example.com" in settings.no_proxy


def test_blank_proxy_is_treated_as_direct(monkeypatch: pytest.MonkeyPatch) -> None:
    """空字符串若被当成有效代理，httpx 会收到非法 URL 而崩溃。"""
    env = _env(HTTPS_PROXY="", HTTP_PROXY="   ")
    for key, value in env.items():
        monkeypatch.setenv(key, value)

    settings = Settings.from_env()

    assert settings.https_proxy is None
    assert settings.http_proxy is None


def test_cache_dir_defaults_under_project(monkeypatch: pytest.MonkeyPatch) -> None:
    """把缓存目录指到临时目录会让提交进仓库的缓存失效，A2 无法成立。"""
    for key, value in _env().items():
        monkeypatch.setenv(key, value)
    monkeypatch.delenv("MEMORY_CACHE_DIR", raising=False)

    settings = Settings.from_env()

    assert settings.cache_dir.name == "cache"
    assert settings.cache_dir.parent.name == "data"


def test_agent_memory_cache_dir_override(monkeypatch: pytest.MonkeyPatch) -> None:
    """忽略环境变量覆盖会让测试之间互相污染缓存。"""
    for key, value in _env().items():
        monkeypatch.setenv(key, value)
    monkeypatch.setenv("MEMORY_CACHE_DIR", "/tmp/other-cache")

    settings = Settings.from_env()

    assert settings.cache_dir.name == "other-cache"
