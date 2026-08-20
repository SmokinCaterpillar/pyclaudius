from pathlib import Path

import pytest
from pydantic import ValidationError
from pydantic_settings import SettingsConfigDict

from pyclaudius.config import Settings, ensure_dirs


def test_settings_defaults(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test-token")
    monkeypatch.setenv("TELEGRAM_USER_ID", "12345")
    s = Settings()
    assert s.telegram_bot_token == "test-token"
    assert s.telegram_user_id == "12345"
    assert s.opencode_path == "opencode"
    assert s.relay_dir == Path.home() / ".pyclaudius-relay"


def test_settings_derived_paths(tmp_path, monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "t")
    monkeypatch.setenv("TELEGRAM_USER_ID", "1")
    relay = tmp_path / "test-relay"
    monkeypatch.setenv("RELAY_DIR", str(relay))
    s = Settings()
    assert s.temp_dir == relay / "temp"
    assert s.uploads_dir == relay / "work" / "uploads"
    assert s.session_file == relay / "session.json"
    assert s.lock_file == relay / "bot.lock"
    assert s.backlog_file == relay / "backlog.json"
    assert s.opencode_work_dir == relay / "work"
    assert s.opencode_config_file == relay / "opencode.json"


def test_settings_missing_required_vars(monkeypatch):
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("TELEGRAM_USER_ID", raising=False)
    monkeypatch.setattr(Settings, "model_config", SettingsConfigDict(env_file=None))
    with pytest.raises(ValidationError):
        Settings()


def test_ensure_dirs_creates_directories(tmp_path, monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "t")
    monkeypatch.setenv("TELEGRAM_USER_ID", "1")
    monkeypatch.setenv("RELAY_DIR", str(tmp_path / "relay"))
    s = Settings()
    ensure_dirs(settings=s)
    assert s.temp_dir.is_dir()
    assert s.uploads_dir.is_dir()
    assert s.opencode_work_dir.is_dir()


def test_settings_allowed_tools_default(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test-token")
    monkeypatch.setenv("TELEGRAM_USER_ID", "12345")
    monkeypatch.setenv("ALLOWED_TOOLS", "[]")
    s = Settings()
    assert s.allowed_tools == []


def test_settings_allowed_tools_from_env(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test-token")
    monkeypatch.setenv("TELEGRAM_USER_ID", "12345")
    monkeypatch.setenv("ALLOWED_TOOLS", '["WebSearch","WebFetch"]')
    s = Settings()
    assert s.allowed_tools == ["WebSearch", "WebFetch"]


def test_settings_str_masks_token(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "secret-token-123")
    monkeypatch.setenv("TELEGRAM_USER_ID", "12345")
    s = Settings()
    result = str(s)
    assert "secret-token-123" not in result
    assert "xxx" in result
    assert "12345" in result


def test_settings_backlog_enabled_default(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test-token")
    monkeypatch.setenv("TELEGRAM_USER_ID", "12345")
    s = Settings()
    assert s.backlog_enabled is True


def test_settings_timezone_file(tmp_path, monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "t")
    monkeypatch.setenv("TELEGRAM_USER_ID", "1")
    relay = tmp_path / "test-relay"
    monkeypatch.setenv("RELAY_DIR", str(relay))
    s = Settings()
    assert s.timezone_file == relay / "timezone.json"


def test_settings_opencode_timeout_default(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test-token")
    monkeypatch.setenv("TELEGRAM_USER_ID", "12345")
    s = Settings()
    assert s.opencode_timeout == 300


def test_settings_opencode_timeout_from_env(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test-token")
    monkeypatch.setenv("TELEGRAM_USER_ID", "12345")
    monkeypatch.setenv("OPENCODE_TIMEOUT", "60")
    s = Settings()
    assert s.opencode_timeout == 60


def test_settings_opencode_model_default(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test-token")
    monkeypatch.setenv("TELEGRAM_USER_ID", "12345")
    monkeypatch.delenv("OPENCODE_MODEL", raising=False)
    s = Settings()
    assert s.opencode_model == "tensorx/moonshotai/kimi-k3"


def test_settings_opencode_model_from_env(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test-token")
    monkeypatch.setenv("TELEGRAM_USER_ID", "12345")
    monkeypatch.setenv("OPENCODE_MODEL", "tensorx/z-ai/glm-5")
    s = Settings()
    assert s.opencode_model == "tensorx/z-ai/glm-5"


def test_settings_splits_provider_and_model(monkeypatch):
    """The summarize endpoint needs them separately, and the model half has slashes."""
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "t")
    monkeypatch.setenv("TELEGRAM_USER_ID", "1")
    monkeypatch.setenv("OPENCODE_MODEL", "tensorx/moonshotai/kimi-k3")
    s = Settings()
    assert s.provider_id == "tensorx"
    assert s.model_id == "moonshotai/kimi-k3"


def test_settings_model_without_provider(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "t")
    monkeypatch.setenv("TELEGRAM_USER_ID", "1")
    monkeypatch.setenv("OPENCODE_MODEL", "bare-model")
    s = Settings()
    assert s.provider_id == "bare-model"
    assert s.model_id == ""


def test_settings_api_key_default_empty(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test-token")
    monkeypatch.setenv("TELEGRAM_USER_ID", "12345")
    monkeypatch.delenv("TENSORX_API_KEY", raising=False)
    s = Settings()
    assert s.tensorx_api_key == ""


def test_settings_api_key_from_env(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test-token")
    monkeypatch.setenv("TELEGRAM_USER_ID", "12345")
    monkeypatch.setenv("TENSORX_API_KEY", "sk-abc")
    s = Settings()
    assert s.tensorx_api_key == "sk-abc"


def test_settings_str_masks_api_key(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "t")
    monkeypatch.setenv("TELEGRAM_USER_ID", "1")
    monkeypatch.setenv("TENSORX_API_KEY", "sk-super-secret")
    s = Settings()
    assert "sk-super-secret" not in str(s)


def test_settings_context_limit_default(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "t")
    monkeypatch.setenv("TELEGRAM_USER_ID", "1")
    s = Settings()
    assert s.opencode_context_limit == 1_048_576


def test_settings_auto_approve_default_false(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "t")
    monkeypatch.setenv("TELEGRAM_USER_ID", "1")
    s = Settings()
    assert s.opencode_auto_approve is False


def test_ensure_dirs_idempotent(tmp_path, monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "t")
    monkeypatch.setenv("TELEGRAM_USER_ID", "1")
    monkeypatch.setenv("RELAY_DIR", str(tmp_path / "relay"))
    s = Settings()
    ensure_dirs(settings=s)
    ensure_dirs(settings=s)
    assert s.temp_dir.is_dir()
