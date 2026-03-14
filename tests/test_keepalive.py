import asyncio
import logging
from unittest.mock import AsyncMock, patch

import pytest

from pyclaudius.keepalive import send_tmux_keepalive


@pytest.fixture()
def _mock_subprocess():
    """Yield a mock for asyncio.create_subprocess_exec with configurable returncode."""
    mock_proc = AsyncMock()
    mock_proc.returncode = 0
    mock_proc.communicate = AsyncMock(return_value=(b"", b""))
    with patch(
        "pyclaudius.keepalive.asyncio.create_subprocess_exec", return_value=mock_proc
    ) as mock_exec:
        yield mock_exec, mock_proc


@pytest.mark.asyncio()
async def test_send_tmux_keepalive_success(_mock_subprocess, caplog):
    _mock_exec, mock_proc = _mock_subprocess
    mock_proc.returncode = 0

    with caplog.at_level(logging.INFO, logger="pyclaudius.keepalive"):
        await send_tmux_keepalive(session_name="claude")

    assert "Sent keepalive to tmux session 'claude'" in caplog.text


@pytest.mark.asyncio()
async def test_send_tmux_keepalive_failure(_mock_subprocess, caplog):
    _mock_exec, mock_proc = _mock_subprocess
    mock_proc.returncode = 1
    mock_proc.communicate = AsyncMock(return_value=(b"", b"session not found"))

    with caplog.at_level(logging.WARNING, logger="pyclaudius.keepalive"):
        await send_tmux_keepalive(session_name="nosession")

    assert "Tmux keepalive failed for 'nosession'" in caplog.text
    assert "session not found" in caplog.text


@pytest.mark.asyncio()
async def test_send_tmux_keepalive_calls_correct_command(_mock_subprocess):
    mock_exec, _mock_proc = _mock_subprocess

    await send_tmux_keepalive(session_name="mysession")

    mock_exec.assert_called_once_with(
        "tmux",
        "send-keys",
        "-t",
        "mysession",
        "hello from pyclaudius",
        "Enter",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
