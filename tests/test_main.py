import logging
from unittest.mock import AsyncMock, MagicMock

import pytest
from telegram import Update

from pyclaudius.main import _error_handler, _on_mcp_task_done


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
