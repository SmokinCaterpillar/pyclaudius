from pathlib import Path

import pytest
from pydantic import ValidationError

from pyclaudius.config import Settings, ensure_dirs


def test_settings_defaults(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test-token")
    monkeypatch.setenv("TELEGRAM_USER_ID", "12345")
    s = Settings()
    assert s.telegram_bot_token == "test-token"
    assert s.telegram_user_id == "12345"
    assert s.claude_path == "claude"
    assert s.relay_dir == Path.home() / ".pyclaudius-relay"


def test_settings_derived_paths(tmp_path, monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "t")
    monkeypatch.setenv("TELEGRAM_USER_ID", "1")
    relay = tmp_path / "test-relay"
    monkeypatch.setenv("RELAY_DIR", str(relay))
    s = Settings()
    assert s.temp_dir == relay / "temp"
    assert s.uploads_dir == relay / "uploads"
    assert s.session_file == relay / "session.json"
    assert s.lock_file == relay / "bot.lock"


def test_settings_missing_required_vars(monkeypatch):
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("TELEGRAM_USER_ID", raising=False)
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


def test_ensure_dirs_idempotent(tmp_path, monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "t")
    monkeypatch.setenv("TELEGRAM_USER_ID", "1")
    monkeypatch.setenv("RELAY_DIR", str(tmp_path / "relay"))
    s = Settings()
    ensure_dirs(settings=s)
    ensure_dirs(settings=s)
    assert s.temp_dir.is_dir()
