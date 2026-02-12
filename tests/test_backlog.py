import json
from unittest.mock import MagicMock

import pytest

from pyclaudius.backlog import (
    BacklogItem,
    format_backlog_list,
    load_backlog,
    save_backlog,
    with_backlog,
)


def test_load_backlog_empty(tmp_path):
    backlog_file = tmp_path / "backlog.json"
    backlog_file.write_text("[]")
    result = load_backlog(backlog_file=backlog_file)
    assert result == []


def test_load_backlog_missing_file(tmp_path):
    backlog_file = tmp_path / "backlog.json"
    result = load_backlog(backlog_file=backlog_file)
    assert result == []


def test_save_and_load_backlog(tmp_path):
    backlog_file = tmp_path / "backlog.json"
    items: list[BacklogItem] = [
        {"prompt": "hello", "created_at": "2026-01-01T00:00:00"},
        {"prompt": "world", "created_at": "2026-01-02T00:00:00"},
    ]
    save_backlog(backlog_file=backlog_file, items=items)
    loaded = load_backlog(backlog_file=backlog_file)
    assert loaded == items


def test_load_backlog_invalid_json(tmp_path):
    backlog_file = tmp_path / "backlog.json"
    backlog_file.write_text("not json")
    result = load_backlog(backlog_file=backlog_file)
    assert result == []


def test_load_backlog_not_a_list(tmp_path):
    backlog_file = tmp_path / "backlog.json"
    backlog_file.write_text('{"key": "value"}')
    result = load_backlog(backlog_file=backlog_file)
    assert result == []


def test_format_backlog_list_empty():
    result = format_backlog_list(items=[])
    assert result == "Backlog is empty."


def test_format_backlog_list_items():
    items: list[BacklogItem] = [
        {"prompt": "hello world", "created_at": "2026-01-01T00:00:00"},
        {"prompt": "test message", "created_at": "2026-01-02T12:30:00"},
    ]
    result = format_backlog_list(items=items)
    assert "2" in result
    assert "hello world" in result
    assert "test message" in result
    assert "2026-01-01T00:00:00" in result
    assert "2026-01-02T12:30:00" in result


@pytest.mark.asyncio
async def test_with_backlog_normal_response():
    """No auth error — response passes through unchanged."""

    @with_backlog
    async def fake_claude(*, prompt: str) -> tuple[str, str | None]:
        return "Hello from Claude", "sess-1"

    bot_data = {
        "settings": MagicMock(backlog_enabled=True, backlog_file="/tmp/bl.json"),
        "backlog": [],
    }
    result, session_id = await fake_claude(
        prompt="hi", bot_data=bot_data, user_message="hi"
    )
    assert result == "Hello from Claude"
    assert session_id == "sess-1"
    assert bot_data["backlog"] == []


@pytest.mark.asyncio
async def test_with_backlog_auth_error_saves_prompt(tmp_path):
    """Auth error detected — item added to backlog and notification returned."""

    @with_backlog
    async def fake_claude(*, prompt: str) -> tuple[str, str | None]:
        return "authentication_error", "sess-1"

    backlog_file = tmp_path / "backlog.json"
    bot_data = {
        "settings": MagicMock(backlog_enabled=True, backlog_file=backlog_file),
        "backlog": [],
    }
    result, session_id = await fake_claude(
        prompt="hi", bot_data=bot_data, user_message="original question"
    )
    assert "Authentication error" in result
    assert "1 pending" in result
    assert session_id is None
    assert len(bot_data["backlog"]) == 1
    assert bot_data["backlog"][0]["prompt"] == "original question"

    # Check it was persisted to disk
    saved = json.loads(backlog_file.read_text())
    assert len(saved) == 1
    assert saved[0]["prompt"] == "original question"


@pytest.mark.asyncio
async def test_with_backlog_auth_error_disabled():
    """backlog_enabled=False — auth error passes through unchanged."""

    @with_backlog
    async def fake_claude(*, prompt: str) -> tuple[str, str | None]:
        return "authentication_error", "sess-1"

    bot_data = {
        "settings": MagicMock(backlog_enabled=False),
        "backlog": [],
    }
    result, session_id = await fake_claude(
        prompt="hi", bot_data=bot_data, user_message="original question"
    )
    assert result == "authentication_error"
    assert session_id == "sess-1"
    assert bot_data["backlog"] == []


@pytest.mark.asyncio
async def test_with_backlog_no_bot_data():
    """No bot_data kwarg — response passes through unchanged."""

    @with_backlog
    async def fake_claude(*, prompt: str) -> tuple[str, str | None]:
        return "authentication_error", "sess-1"

    result, session_id = await fake_claude(prompt="hi")
    assert result == "authentication_error"
    assert session_id == "sess-1"


@pytest.mark.asyncio
async def test_with_backlog_preserves_function_name():
    @with_backlog
    async def my_func(*, prompt: str) -> tuple[str, str | None]:
        return "ok", None

    assert my_func.__name__ == "my_func"


@pytest.mark.asyncio
async def test_with_backlog_empty_user_message_not_saved(tmp_path):
    """Auth error with empty/blank user_message — skip saving to backlog."""

    @with_backlog
    async def fake_claude(*, prompt: str) -> tuple[str, str | None]:
        return "authentication_error", None

    backlog_file = tmp_path / "backlog.json"
    bot_data = {
        "settings": MagicMock(backlog_enabled=True, backlog_file=backlog_file),
        "backlog": [],
    }

    # None user_message
    result, _ = await fake_claude(
        prompt="hi", bot_data=bot_data, user_message=None
    )
    assert result == "authentication_error"
    assert bot_data["backlog"] == []

    # Empty string
    result, _ = await fake_claude(
        prompt="hi", bot_data=bot_data, user_message=""
    )
    assert result == "authentication_error"
    assert bot_data["backlog"] == []

    # Blank string
    result, _ = await fake_claude(
        prompt="hi", bot_data=bot_data, user_message="   "
    )
    assert result == "authentication_error"
    assert bot_data["backlog"] == []


@pytest.mark.asyncio
async def test_with_backlog_appends_to_existing(tmp_path):
    """Multiple auth errors accumulate in the backlog."""

    @with_backlog
    async def fake_claude(*, prompt: str) -> tuple[str, str | None]:
        return "authentication_error", None

    backlog_file = tmp_path / "backlog.json"
    existing: list[BacklogItem] = [
        {"prompt": "first", "created_at": "2026-01-01T00:00:00"}
    ]
    bot_data = {
        "settings": MagicMock(backlog_enabled=True, backlog_file=backlog_file),
        "backlog": list(existing),
    }
    result, _ = await fake_claude(
        prompt="hi", bot_data=bot_data, user_message="second"
    )
    assert "2 pending" in result
    assert len(bot_data["backlog"]) == 2
    assert bot_data["backlog"][1]["prompt"] == "second"
