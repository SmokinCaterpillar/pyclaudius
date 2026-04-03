import asyncio
import logging
from unittest.mock import AsyncMock, patch

import pytest

from pyclaudius.keepalive import _tmux_send, send_tmux_keepalive


@pytest.mark.asyncio()
async def test_tmux_send_success():
    mock_proc = AsyncMock()
    mock_proc.returncode = 0
    mock_proc.communicate = AsyncMock(return_value=(b"", b""))
    with patch(
        "pyclaudius.keepalive.asyncio.create_subprocess_exec", return_value=mock_proc
    ) as mock_exec:
        result = await _tmux_send(session_name="claude", text="hello")
    assert result is True
    mock_exec.assert_called_once_with(
        "tmux",
        "send-keys",
        "-t",
        "claude",
        "hello",
        "Enter",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )


@pytest.mark.asyncio()
async def test_tmux_send_failure(caplog):
    mock_proc = AsyncMock()
    mock_proc.returncode = 1
    mock_proc.communicate = AsyncMock(return_value=(b"", b"session not found"))
    with patch(
        "pyclaudius.keepalive.asyncio.create_subprocess_exec", return_value=mock_proc
    ), caplog.at_level(logging.WARNING, logger="pyclaudius.keepalive"):
        result = await _tmux_send(session_name="nosession", text="hello")
    assert result is False
    assert "session not found" in caplog.text


@pytest.mark.asyncio()
async def test_send_tmux_keepalive_success(caplog):
    mock_proc = AsyncMock()
    mock_proc.returncode = 0
    mock_proc.communicate = AsyncMock(return_value=(b"", b""))
    with (
        patch(
            "pyclaudius.keepalive.asyncio.create_subprocess_exec",
            return_value=mock_proc,
        ) as mock_exec,
        patch(
            "pyclaudius.keepalive.asyncio.sleep", new_callable=AsyncMock
        ) as mock_sleep,
        caplog.at_level(logging.INFO, logger="pyclaudius.keepalive"),
    ):
        await send_tmux_keepalive(session_name="claude")

    assert mock_exec.call_count == 2
    mock_exec.assert_any_call(
        "tmux",
        "send-keys",
        "-t",
        "claude",
        "/clear",
        "Enter",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    mock_exec.assert_any_call(
        "tmux",
        "send-keys",
        "-t",
        "claude",
        "Hello from pyclaudius",
        "Enter",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    mock_sleep.assert_called_once_with(2)
    assert "Sent keepalive to tmux session 'claude'" in caplog.text


@pytest.mark.asyncio()
async def test_send_tmux_keepalive_clear_fails(caplog):
    """If /clear fails, don't send the keepalive message."""
    mock_proc = AsyncMock()
    mock_proc.returncode = 1
    mock_proc.communicate = AsyncMock(return_value=(b"", b"session not found"))
    with (
        patch(
            "pyclaudius.keepalive.asyncio.create_subprocess_exec",
            return_value=mock_proc,
        ) as mock_exec,
        patch(
            "pyclaudius.keepalive.asyncio.sleep", new_callable=AsyncMock
        ) as mock_sleep,
        caplog.at_level(logging.WARNING, logger="pyclaudius.keepalive"),
    ):
        await send_tmux_keepalive(session_name="nosession")

    mock_exec.assert_called_once()  # Only the /clear call, not the hello
    mock_sleep.assert_not_called()
    assert "session not found" in caplog.text


@pytest.mark.asyncio()
async def test_send_tmux_keepalive_hello_fails(caplog):
    """If /clear succeeds but hello fails, log warning."""
    call_count = 0

    async def make_proc(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        proc = AsyncMock()
        proc.returncode = 0 if call_count == 1 else 1
        proc.communicate = AsyncMock(
            return_value=(b"", b"" if call_count == 1 else b"error")
        )
        return proc

    with (
        patch(
            "pyclaudius.keepalive.asyncio.create_subprocess_exec",
            side_effect=make_proc,
        ),
        patch("pyclaudius.keepalive.asyncio.sleep", new_callable=AsyncMock),
        caplog.at_level(logging.WARNING, logger="pyclaudius.keepalive"),
    ):
        await send_tmux_keepalive(session_name="claude")

    assert "Tmux keepalive failed for 'claude'" in caplog.text
