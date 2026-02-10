from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from pyclaudius.tooling import (
    _try_auth_login,
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
async def test_try_auth_login_success():
    """Returns True when 'claude auth login' exits 0."""
    proc = AsyncMock()
    proc.returncode = 0
    proc.communicate.return_value = (b"ok", b"")
    with patch(
        "pyclaudius.tooling.asyncio.create_subprocess_exec",
        return_value=proc,
    ):
        result = await _try_auth_login(
            claude_path="claude", cwd="/tmp", env={"HOME": "/home/x"},
        )
        assert result is True


@pytest.mark.asyncio
async def test_try_auth_login_failure_falls_through():
    """Returns None on any failure so caller can try PTY approach."""
    proc = AsyncMock()
    proc.returncode = 1
    proc.communicate.return_value = (b"", b"auth failed")
    with patch(
        "pyclaudius.tooling.asyncio.create_subprocess_exec",
        return_value=proc,
    ):
        result = await _try_auth_login(
            claude_path="claude", cwd=None, env={},
        )
        assert result is None


@pytest.mark.asyncio
async def test_refresh_auth_pty_success():
    """script-based PTY refresh returns True on exit code 0."""
    proc = AsyncMock()
    proc.returncode = 0
    proc.stdin = AsyncMock()
    proc.communicate.return_value = (b"output", None)
    with (
        patch(
            "pyclaudius.tooling.asyncio.create_subprocess_exec",
            return_value=proc,
        ) as mock_exec,
        patch("pyclaudius.tooling.asyncio.sleep", new_callable=AsyncMock),
    ):
        from pyclaudius.tooling import _refresh_auth_pty

        env = {"HOME": "/home/x", "TERM": "xterm-256color"}
        result = await _refresh_auth_pty(
            claude_path="/usr/bin/claude", cwd="/tmp/work", env=env,
        )
        assert result is True
        mock_exec.assert_called_once()
        # Uses script command to wrap claude.
        assert mock_exec.call_args[0][0] == "script"
        assert "/usr/bin/claude" in mock_exec.call_args[0]
        assert mock_exec.call_args.kwargs["cwd"] == "/tmp/work"


@pytest.mark.asyncio
async def test_refresh_auth_pty_failure():
    """script-based PTY refresh returns False on non-zero exit."""
    proc = AsyncMock()
    proc.returncode = 1
    proc.stdin = AsyncMock()
    proc.communicate.return_value = (b"error", None)
    with (
        patch(
            "pyclaudius.tooling.asyncio.create_subprocess_exec",
            return_value=proc,
        ),
        patch("pyclaudius.tooling.asyncio.sleep", new_callable=AsyncMock),
    ):
        from pyclaudius.tooling import _refresh_auth_pty

        env = {"HOME": "/home/x", "TERM": "xterm-256color"}
        result = await _refresh_auth_pty(claude_path="claude", cwd=None, env=env)
        assert result is False


@pytest.mark.asyncio
async def test_refresh_auth_pty_timeout():
    """script-based PTY refresh returns False and kills on timeout."""
    proc = AsyncMock()
    proc.stdin = AsyncMock()
    with (
        patch(
            "pyclaudius.tooling.asyncio.create_subprocess_exec",
            return_value=proc,
        ),
        patch("pyclaudius.tooling.asyncio.sleep", new_callable=AsyncMock),
        patch(
            "pyclaudius.tooling.asyncio.wait_for",
            side_effect=TimeoutError,
        ),
    ):
        from pyclaudius.tooling import _refresh_auth_pty

        env = {"HOME": "/home/x", "TERM": "xterm-256color"}
        result = await _refresh_auth_pty(claude_path="claude", cwd=None, env=env)
        assert result is False
        proc.kill.assert_called_once()


@pytest.mark.asyncio
async def test_refresh_auth_uses_auth_login_first():
    """refresh_auth tries auth login before falling back to PTY."""
    with (
        patch(
            "pyclaudius.tooling._try_auth_login", return_value=True,
        ) as mock_login,
        patch("pyclaudius.tooling._refresh_auth_pty") as mock_pty,
    ):
        result = await refresh_auth(claude_path="claude", cwd="/tmp")
        assert result is True
        mock_login.assert_called_once()
        mock_pty.assert_not_called()


@pytest.mark.asyncio
async def test_refresh_auth_falls_back_to_pty():
    """refresh_auth falls back to PTY when auth login returns None."""
    with (
        patch("pyclaudius.tooling._try_auth_login", return_value=None),
        patch(
            "pyclaudius.tooling._refresh_auth_pty", return_value=True,
        ) as mock_pty,
    ):
        result = await refresh_auth(claude_path="claude", cwd="/tmp")
        assert result is True
        mock_pty.assert_called_once()


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
async def test_try_auth_login_file_not_found():
    """Returns False when Claude CLI binary is not found."""
    with patch(
        "pyclaudius.tooling.asyncio.create_subprocess_exec",
        side_effect=FileNotFoundError,
    ):
        result = await _try_auth_login(
            claude_path="/nonexistent/claude", cwd=None, env={},
        )
        assert result is False


@pytest.mark.asyncio
async def test_refresh_auth_pty_file_not_found():
    """Returns False when script or CLI binary is not found."""
    with patch(
        "pyclaudius.tooling.asyncio.create_subprocess_exec",
        side_effect=FileNotFoundError,
    ):
        from pyclaudius.tooling import _refresh_auth_pty

        env = {"HOME": "/home/x"}
        result = await _refresh_auth_pty(
            claude_path="/nonexistent/claude", cwd=None, env=env,
        )
        assert result is False
