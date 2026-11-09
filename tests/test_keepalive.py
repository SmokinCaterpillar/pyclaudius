import asyncio
import logging
from unittest.mock import AsyncMock, MagicMock, call, patch

import pytest

from pyclaudius.keepalive import (
    _tmux_capture,
    _tmux_send,
    is_trust_dialog,
    send_tmux_keepalive,
)

# Screen captured from a real claude 2.1.318 start in an untrusted folder.
# \u276f is claude's selection marker, escaped to keep ruff's RUF001 quiet.
TRUST_DIALOG_SCREEN = """\
 Accessing workspace:

 /home/claude

 Quick safety check: Is this a project you created or one you trust?

 Claude Code'll be able to read, edit, and execute files here.

 \u276f No, exit
   Yes, I trust this folder

 Enter to confirm · Esc to cancel
"""

PROMPT_SCREEN = """\
────────────────────────────────────────────────────────────────────────────────
\u276f Try "fix lint errors"
────────────────────────────────────────────────────────────────────────────────
  ⏵⏵ auto mode on (shift+tab to cycle)
"""


def _make_proc(
    *, returncode: int, stdout: bytes = b"", stderr: bytes = b""
) -> MagicMock:
    proc = MagicMock()
    proc.returncode = returncode
    proc.communicate = AsyncMock(return_value=(stdout, stderr))
    return proc


def _send_call(*, text: str) -> object:
    return call(
        "tmux",
        "send-keys",
        "-t",
        "claude",
        text,
        "Enter",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )


CAPTURE_CALL = call(
    "tmux",
    "capture-pane",
    "-p",
    "-t",
    "claude",
    stdout=asyncio.subprocess.PIPE,
    stderr=asyncio.subprocess.PIPE,
)


def test_is_trust_dialog_true() -> None:
    assert is_trust_dialog(screen=TRUST_DIALOG_SCREEN) is True


def test_is_trust_dialog_false_on_prompt() -> None:
    assert is_trust_dialog(screen=PROMPT_SCREEN) is False


def test_is_trust_dialog_false_on_chat_mention() -> None:
    screen = "● You can choose 'Yes, I trust this folder' next time."
    assert is_trust_dialog(screen=screen) is False


def test_is_trust_dialog_false_on_empty() -> None:
    assert is_trust_dialog(screen="") is False


@pytest.mark.asyncio()
async def test_tmux_capture_success() -> None:
    proc = _make_proc(returncode=0, stdout=PROMPT_SCREEN.encode())
    with patch(
        "pyclaudius.keepalive.asyncio.create_subprocess_exec", return_value=proc
    ) as mock_exec:
        result = await _tmux_capture(session_name="claude")
    assert result == PROMPT_SCREEN
    assert mock_exec.call_args == CAPTURE_CALL


@pytest.mark.asyncio()
async def test_tmux_capture_failure(caplog: pytest.LogCaptureFixture) -> None:
    proc = _make_proc(returncode=1, stderr=b"no server running")
    with (
        patch("pyclaudius.keepalive.asyncio.create_subprocess_exec", return_value=proc),
        caplog.at_level(logging.WARNING, logger="pyclaudius.keepalive"),
    ):
        result = await _tmux_capture(session_name="claude")
    assert result is None
    assert "no server running" in caplog.text


@pytest.mark.asyncio()
async def test_tmux_send_success() -> None:
    proc = _make_proc(returncode=0)
    with patch(
        "pyclaudius.keepalive.asyncio.create_subprocess_exec", return_value=proc
    ) as mock_exec:
        result = await _tmux_send(session_name="claude", text="hello")
    assert result is True
    assert mock_exec.call_args == _send_call(text="hello")


@pytest.mark.asyncio()
async def test_tmux_send_failure(caplog: pytest.LogCaptureFixture) -> None:
    proc = _make_proc(returncode=1, stderr=b"session not found")
    with (
        patch("pyclaudius.keepalive.asyncio.create_subprocess_exec", return_value=proc),
        caplog.at_level(logging.WARNING, logger="pyclaudius.keepalive"),
    ):
        result = await _tmux_send(session_name="nosession", text="hello")
    assert result is False
    assert "session not found" in caplog.text


@pytest.mark.asyncio()
async def test_send_tmux_keepalive_success(caplog: pytest.LogCaptureFixture) -> None:
    procs = [
        _make_proc(returncode=0, stdout=PROMPT_SCREEN.encode()),
        _make_proc(returncode=0),
        _make_proc(returncode=0),
    ]
    with (
        patch(
            "pyclaudius.keepalive.asyncio.create_subprocess_exec", side_effect=procs
        ) as mock_exec,
        patch(
            "pyclaudius.keepalive.asyncio.sleep", new_callable=AsyncMock
        ) as mock_sleep,
        caplog.at_level(logging.INFO, logger="pyclaudius.keepalive"),
    ):
        await send_tmux_keepalive(session_name="claude")

    assert mock_exec.call_args_list == [
        CAPTURE_CALL,
        _send_call(text="/clear"),
        _send_call(text="Hello from pyclaudius"),
    ]
    mock_sleep.assert_called_once_with(2)
    assert "Sent keepalive to tmux session 'claude'" in caplog.text


@pytest.mark.asyncio()
async def test_send_tmux_keepalive_trust_dialog(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """In the trust dialog, Enter would pick 'No, exit': send nothing."""
    procs = [_make_proc(returncode=0, stdout=TRUST_DIALOG_SCREEN.encode())]
    with (
        patch(
            "pyclaudius.keepalive.asyncio.create_subprocess_exec", side_effect=procs
        ) as mock_exec,
        patch(
            "pyclaudius.keepalive.asyncio.sleep", new_callable=AsyncMock
        ) as mock_sleep,
        caplog.at_level(logging.ERROR, logger="pyclaudius.keepalive"),
    ):
        await send_tmux_keepalive(session_name="claude")

    assert mock_exec.call_args_list == [CAPTURE_CALL]
    mock_sleep.assert_not_called()
    assert "trust dialog" in caplog.text
    assert "tmux attach -t claude" in caplog.text


@pytest.mark.asyncio()
async def test_send_tmux_keepalive_capture_fails(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """No session or no server: nothing to send to."""
    procs = [_make_proc(returncode=1, stderr=b"no server running")]
    with (
        patch(
            "pyclaudius.keepalive.asyncio.create_subprocess_exec", side_effect=procs
        ) as mock_exec,
        patch(
            "pyclaudius.keepalive.asyncio.sleep", new_callable=AsyncMock
        ) as mock_sleep,
        caplog.at_level(logging.WARNING, logger="pyclaudius.keepalive"),
    ):
        await send_tmux_keepalive(session_name="claude")

    assert mock_exec.call_args_list == [CAPTURE_CALL]
    mock_sleep.assert_not_called()
    assert "no server running" in caplog.text
    assert "Tmux keepalive failed for 'claude'" in caplog.text


@pytest.mark.asyncio()
async def test_send_tmux_keepalive_clear_fails(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """If /clear fails, don't send the keepalive message."""
    procs = [
        _make_proc(returncode=0, stdout=PROMPT_SCREEN.encode()),
        _make_proc(returncode=1, stderr=b"session not found"),
    ]
    with (
        patch(
            "pyclaudius.keepalive.asyncio.create_subprocess_exec", side_effect=procs
        ) as mock_exec,
        patch(
            "pyclaudius.keepalive.asyncio.sleep", new_callable=AsyncMock
        ) as mock_sleep,
        caplog.at_level(logging.WARNING, logger="pyclaudius.keepalive"),
    ):
        await send_tmux_keepalive(session_name="claude")

    assert mock_exec.call_args_list == [CAPTURE_CALL, _send_call(text="/clear")]
    mock_sleep.assert_not_called()
    assert "session not found" in caplog.text


@pytest.mark.asyncio()
async def test_send_tmux_keepalive_hello_fails(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """If /clear succeeds but hello fails, log warning."""
    procs = [
        _make_proc(returncode=0, stdout=PROMPT_SCREEN.encode()),
        _make_proc(returncode=0),
        _make_proc(returncode=1, stderr=b"error"),
    ]
    with (
        patch("pyclaudius.keepalive.asyncio.create_subprocess_exec", side_effect=procs),
        patch("pyclaudius.keepalive.asyncio.sleep", new_callable=AsyncMock),
        caplog.at_level(logging.WARNING, logger="pyclaudius.keepalive"),
    ):
        await send_tmux_keepalive(session_name="claude")

    assert "Tmux keepalive failed for 'claude'" in caplog.text
