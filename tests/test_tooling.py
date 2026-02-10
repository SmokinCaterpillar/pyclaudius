from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from pyclaudius.tooling import (
    authorized,
    check_authorized,
    is_auth_error,
    refresh_auth,
    with_auth_retry,
)


def test_check_authorized_match():
    assert check_authorized(12345, allowed_user_id="12345") is True


def test_check_authorized_mismatch():
    assert check_authorized(12345, allowed_user_id="99999") is False


def test_check_authorized_string_conversion():
    assert check_authorized(12345, allowed_user_id="12345") is True


@pytest.mark.asyncio
async def test_authorized_decorator_rejects_unauthorized():
    @authorized
    async def dummy_handler(update, context):
        pass

    update = MagicMock()
    update.effective_user.id = 99999
    update.message.reply_text = AsyncMock()
    context = MagicMock()
    context.bot_data = {"settings": MagicMock(telegram_user_id="12345")}

    await dummy_handler(update, context)
    update.message.reply_text.assert_called_once_with("This bot is private.")


@pytest.mark.asyncio
async def test_authorized_decorator_allows_authorized():
    called = []

    @authorized
    async def dummy_handler(update, context):
        called.append(True)

    update = MagicMock()
    update.effective_user.id = 12345
    update.message.reply_text = AsyncMock()
    context = MagicMock()
    context.bot_data = {"settings": MagicMock(telegram_user_id="12345")}

    await dummy_handler(update, context)
    assert called == [True]
    update.message.reply_text.assert_not_called()


@pytest.mark.asyncio
async def test_authorized_decorator_no_effective_user():
    called = []

    @authorized
    async def dummy_handler(update, context):
        called.append(True)

    update = MagicMock()
    update.effective_user = None
    context = MagicMock()

    await dummy_handler(update, context)
    assert called == []


@pytest.mark.asyncio
async def test_authorized_decorator_no_message():
    called = []

    @authorized
    async def dummy_handler(update, context):
        called.append(True)

    update = MagicMock()
    update.effective_user.id = 12345
    update.message = None
    context = MagicMock()

    await dummy_handler(update, context)
    assert called == []


@pytest.mark.asyncio
async def test_authorized_decorator_preserves_function_name():
    @authorized
    async def my_handler(update, context):
        pass

    assert my_handler.__name__ == "my_handler"


@pytest.mark.parametrize(
    "text",
    [
        'Error: {"type":"error","error":{"type":"authentication_error"}}',
        "OAuth token has expired. Please re-authenticate.",
        "API Error: 401 Unauthorized",
    ],
)
def test_is_auth_error_matches(text: str):
    assert is_auth_error(response=text) is True


@pytest.mark.parametrize(
    "text",
    [
        "Hello from Claude",
        "Error: something went wrong",
        "API Error: 500 Internal Server Error",
    ],
)
def test_is_auth_error_no_match(text: str):
    assert is_auth_error(response=text) is False


@pytest.mark.asyncio
async def test_refresh_auth_success():
    proc = AsyncMock()
    proc.returncode = 0
    proc.communicate.return_value = (None, b"")
    mock_drain = MagicMock(return_value=b"pty output")
    with (
        patch("pyclaudius.tooling.pty.openpty", return_value=(10, 11)),
        patch("pyclaudius.tooling.os.close") as mock_close,
        patch("pyclaudius.tooling.os.write"),
        patch("pyclaudius.tooling.fcntl.ioctl"),
        patch("pyclaudius.tooling._drain_pty_blocking", mock_drain),
        patch(
            "pyclaudius.tooling.asyncio.create_subprocess_exec",
            return_value=proc,
        ) as mock_exec,
        patch("pyclaudius.tooling.asyncio.sleep", new_callable=AsyncMock),
        patch(
            "pyclaudius.tooling.asyncio.get_running_loop",
            return_value=MagicMock(run_in_executor=AsyncMock(return_value=b"")),
        ),
    ):
        result = await refresh_auth(claude_path="/usr/bin/claude", cwd="/tmp/work")
        assert result is True
        mock_exec.assert_called_once()
        assert mock_exec.call_args[0] == ("/usr/bin/claude",)
        assert mock_exec.call_args.kwargs["stdin"] == 11
        assert mock_exec.call_args.kwargs["stdout"] == 11
        assert mock_exec.call_args.kwargs["cwd"] == "/tmp/work"
        # Env includes TERM for PTY operation.
        assert mock_exec.call_args.kwargs["env"]["TERM"] == "xterm-256color"
        # Slave fd closed in parent after subprocess spawn.
        mock_close.assert_any_call(11)
        proc.communicate.assert_called_once_with()


@pytest.mark.asyncio
async def test_refresh_auth_failure():
    proc = AsyncMock()
    proc.returncode = 1
    proc.communicate.return_value = (None, b"error")
    with (
        patch("pyclaudius.tooling.pty.openpty", return_value=(10, 11)),
        patch("pyclaudius.tooling.os.close"),
        patch("pyclaudius.tooling.os.write"),
        patch("pyclaudius.tooling.fcntl.ioctl"),
        patch("pyclaudius.tooling._drain_pty_blocking", return_value=b""),
        patch(
            "pyclaudius.tooling.asyncio.create_subprocess_exec",
            return_value=proc,
        ),
        patch("pyclaudius.tooling.asyncio.sleep", new_callable=AsyncMock),
        patch(
            "pyclaudius.tooling.asyncio.get_running_loop",
            return_value=MagicMock(run_in_executor=AsyncMock(return_value=b"")),
        ),
    ):
        result = await refresh_auth(claude_path="claude")
        assert result is False


@pytest.mark.asyncio
async def test_refresh_auth_timeout():
    proc = AsyncMock()
    proc.communicate.return_value = (None, b"")
    with (
        patch("pyclaudius.tooling.pty.openpty", return_value=(10, 11)),
        patch("pyclaudius.tooling.os.close"),
        patch("pyclaudius.tooling.os.write"),
        patch("pyclaudius.tooling.fcntl.ioctl"),
        patch("pyclaudius.tooling._drain_pty_blocking", return_value=b""),
        patch(
            "pyclaudius.tooling.asyncio.create_subprocess_exec",
            return_value=proc,
        ),
        patch("pyclaudius.tooling.asyncio.sleep", new_callable=AsyncMock),
        patch(
            "pyclaudius.tooling.asyncio.get_running_loop",
            return_value=MagicMock(run_in_executor=AsyncMock(return_value=b"")),
        ),
        patch(
            "pyclaudius.tooling.asyncio.wait_for",
            side_effect=TimeoutError,
        ),
    ):
        result = await refresh_auth(claude_path="claude")
        assert result is False
        proc.kill.assert_called_once()


@pytest.mark.asyncio
async def test_with_auth_retry_skips_when_disabled():
    """Auth error response returned as-is when auto_refresh_auth=False."""

    @with_auth_retry
    async def fake_claude(*, prompt: str) -> tuple[str, str | None]:
        return "authentication_error", "sess-1"

    result, session_id = await fake_claude(prompt="hi", auto_refresh_auth=False)
    assert result == "authentication_error"
    assert session_id == "sess-1"


@pytest.mark.asyncio
async def test_with_auth_retry_retries_when_enabled():
    """Retries when auto_refresh_auth=True and auth error detected."""
    call_count = 0

    @with_auth_retry
    async def fake_claude(*, prompt: str) -> tuple[str, str | None]:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return "authentication_error", "sess-1"
        return "Hello from Claude", "sess-1"

    with patch("pyclaudius.tooling.refresh_auth", return_value=True) as mock_refresh:
        result, _session_id = await fake_claude(prompt="hi", auto_refresh_auth=True)
        assert result == "Hello from Claude"
        assert call_count == 2
        mock_refresh.assert_called_once()


@pytest.mark.asyncio
async def test_with_auth_retry_retries_even_on_refresh_failure():
    """Retries even when refresh_auth returns False (side-effect refresh)."""
    call_count = 0

    @with_auth_retry
    async def fake_claude(*, prompt: str) -> tuple[str, str | None]:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return "authentication_error", "sess-1"
        return "Hello from Claude", "sess-1"

    with patch("pyclaudius.tooling.refresh_auth", return_value=False) as mock_refresh:
        result, _session_id = await fake_claude(prompt="hi", auto_refresh_auth=True)
        assert result == "Hello from Claude"
        assert call_count == 2
        mock_refresh.assert_called_once()


@pytest.mark.asyncio
async def test_refresh_auth_file_not_found():
    """Returns False when Claude CLI binary is not found."""
    with (
        patch("pyclaudius.tooling.pty.openpty", return_value=(10, 11)),
        patch("pyclaudius.tooling.os.close") as mock_close,
        patch(
            "pyclaudius.tooling.asyncio.create_subprocess_exec",
            side_effect=FileNotFoundError,
        ),
    ):
        result = await refresh_auth(claude_path="/nonexistent/claude")
        assert result is False
        # Both PTY fds should be closed on error.
        mock_close.assert_any_call(10)
        mock_close.assert_any_call(11)


@pytest.mark.asyncio
async def test_refresh_auth_passes_cwd():
    """Verify cwd kwarg reaches create_subprocess_exec."""
    proc = AsyncMock()
    proc.returncode = 0
    proc.communicate.return_value = (None, b"")
    with (
        patch("pyclaudius.tooling.pty.openpty", return_value=(10, 11)),
        patch("pyclaudius.tooling.os.close"),
        patch("pyclaudius.tooling.os.write"),
        patch("pyclaudius.tooling.fcntl.ioctl"),
        patch("pyclaudius.tooling._drain_pty_blocking", return_value=b""),
        patch(
            "pyclaudius.tooling.asyncio.create_subprocess_exec",
            return_value=proc,
        ) as mock_exec,
        patch("pyclaudius.tooling.asyncio.sleep", new_callable=AsyncMock),
        patch(
            "pyclaudius.tooling.asyncio.get_running_loop",
            return_value=MagicMock(run_in_executor=AsyncMock(return_value=b"")),
        ),
    ):
        await refresh_auth(claude_path="claude", cwd="/home/user/project")
        assert mock_exec.call_args.kwargs["cwd"] == "/home/user/project"
