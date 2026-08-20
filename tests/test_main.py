import logging
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic import ValidationError
from telegram import Update

from pyclaudius.main import (
    _error_handler,
    _load_settings,
    _on_mcp_task_done,
    _post_shutdown,
    configure_logging,
)


@pytest.mark.asyncio
async def test_error_handler_sends_reply():
    update = MagicMock(spec=Update)
    update.message.reply_text = AsyncMock()

    context = MagicMock()
    context.error = RuntimeError("something broke")

    await _error_handler(update, context)

    update.message.reply_text.assert_called_once_with("Error: something broke")


@pytest.mark.asyncio
async def test_error_handler_no_message():
    """When update has no message, handler should not crash."""
    update = MagicMock()
    update.message = None

    context = MagicMock()
    context.error = RuntimeError("no message")

    await _error_handler(update, context)


@pytest.mark.asyncio
async def test_error_handler_non_update_object():
    """When update is not an Update instance, handler should not crash."""
    context = MagicMock()
    context.error = RuntimeError("weird update")

    await _error_handler("not an update", context)


def test_on_mcp_task_done_logs_exception(caplog):
    task = MagicMock()
    task.cancelled.return_value = False
    task.exception.return_value = RuntimeError("MCP died")
    with caplog.at_level(logging.ERROR, logger="pyclaudius.main"):
        _on_mcp_task_done(task)
    assert "MCP server task crashed" in caplog.text
    assert "MCP died" in caplog.text


def test_on_mcp_task_done_logs_unexpected_clean_exit(caplog):
    task = MagicMock()
    task.cancelled.return_value = False
    task.exception.return_value = None
    with caplog.at_level(logging.WARNING, logger="pyclaudius.main"):
        _on_mcp_task_done(task)
    assert "exited unexpectedly" in caplog.text


def test_on_mcp_task_done_silent_on_cancellation(caplog):
    task = MagicMock()
    task.cancelled.return_value = True
    with caplog.at_level(logging.INFO, logger="pyclaudius.main"):
        _on_mcp_task_done(task)
    assert "cancelled" in caplog.text


def _write_env(tmp_path, monkeypatch, body: str) -> None:
    """Point Settings at a throwaway .env with no interfering process env."""
    for name in (
        "TELEGRAM_BOT_TOKEN",
        "TELEGRAM_USER_ID",
        "TENSORX_API_KEY",
        "CLAUDE_MODEL",
        "CLAUDE_EFFORT",
        "CLAUDE_PATH",
        "CLAUDE_TIMEOUT",
        "TMUX_SESSION",
        "RELAY_DIR",
    ):
        monkeypatch.delenv(name, raising=False)
    (tmp_path / ".env").write_text(body)
    monkeypatch.chdir(tmp_path)


def test_load_settings_reads_a_migrated_env(tmp_path, monkeypatch):
    _write_env(
        tmp_path,
        monkeypatch,
        "TELEGRAM_BOT_TOKEN=t\nTELEGRAM_USER_ID=1\nTENSORX_API_KEY=k\n",
    )
    assert _load_settings().tensorx_api_key == "k"


def test_load_settings_exits_on_retired_claude_vars(tmp_path, monkeypatch, caplog):
    """An un-migrated .env must say what to change, not raise a pydantic traceback."""
    _write_env(
        tmp_path,
        monkeypatch,
        "TELEGRAM_BOT_TOKEN=t\nTELEGRAM_USER_ID=1\nTENSORX_API_KEY=k\n"
        "CLAUDE_MODEL=claude-sonnet-4-6\nTMUX_SESSION=claude\n",
    )
    with caplog.at_level(logging.ERROR), pytest.raises(SystemExit) as exc:
        _load_settings()
    assert exc.value.code == 1
    assert "CLAUDE_MODEL is no longer supported" in caplog.text
    assert "OPENCODE_MODEL" in caplog.text
    assert "TMUX_SESSION is no longer supported" in caplog.text


def test_load_settings_reraises_other_validation_errors(tmp_path, monkeypatch):
    """A genuinely unknown key is still a hard error — typos must not pass silently."""
    _write_env(
        tmp_path,
        monkeypatch,
        "TELEGRAM_BOT_TOKEN=t\nTELEGRAM_USER_ID=1\nTENSORX_API_KEY=k\n"
        "OPENCODE_MODLE=typo\n",
    )
    with pytest.raises(ValidationError):
        _load_settings()


def test_configure_logging_silences_httpx():
    """Request URLs are logged by httpx, and the token lives in the URL path."""
    logging.getLogger("httpx").setLevel(logging.INFO)
    configure_logging()
    assert logging.getLogger("httpx").level == logging.WARNING


async def test_post_shutdown_awaits_the_mcp_task():
    """Cancelling without awaiting leaves uvicorn's tasks pending at loop close."""
    import asyncio

    async def never_ending():
        await asyncio.sleep(3600)

    task = asyncio.create_task(never_ending())
    await asyncio.sleep(0)
    application = MagicMock()
    application.bot_data = {"mcp_task": task}

    await _post_shutdown(application)

    assert task.done()
    assert task.cancelled()


async def test_post_shutdown_survives_a_stuck_mcp_task():
    """A server that refuses to unwind must not block the bot's shutdown."""
    import asyncio

    async def swallows_cancellation():
        try:
            await asyncio.sleep(3600)
        except asyncio.CancelledError:
            await asyncio.sleep(3600)

    task = asyncio.create_task(swallows_cancellation())
    await asyncio.sleep(0)
    application = MagicMock()
    application.bot_data = {"mcp_task": task}

    with patch("pyclaudius.main.asyncio.wait_for", side_effect=TimeoutError):
        await _post_shutdown(application)

    task.cancel()


async def test_post_shutdown_without_an_mcp_task():
    application = MagicMock()
    application.bot_data = {}
    await _post_shutdown(application)
