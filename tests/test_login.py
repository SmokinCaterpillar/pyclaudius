import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from pyclaudius.login import _URL_RE, _read_until, interactive_login


@pytest.mark.asyncio
async def test_read_until_finds_url():
    """Returns the first URL found in streamed output."""
    reader = AsyncMock(spec=asyncio.StreamReader)
    reader.read = AsyncMock(
        side_effect=[
            b"Some startup text\n",
            b"Visit https://accounts.example.com/auth?code=abc123 to log in\n",
            b"",  # EOF
        ]
    )

    result = await _read_until(stream=reader, pattern=_URL_RE, timeout=5.0)
    assert result == "https://accounts.example.com/auth?code=abc123"


@pytest.mark.asyncio
async def test_read_until_timeout_returns_none():
    """Returns None when timeout expires before a match."""

    async def slow_read(_n: int) -> bytes:
        await asyncio.sleep(10)
        return b""

    reader = AsyncMock(spec=asyncio.StreamReader)
    reader.read = slow_read

    result = await _read_until(stream=reader, pattern=_URL_RE, timeout=0.1)
    assert result is None


@pytest.mark.asyncio
async def test_read_until_strips_ansi():
    """ANSI escape sequences are stripped before pattern matching."""
    reader = AsyncMock(spec=asyncio.StreamReader)
    reader.read = AsyncMock(
        side_effect=[
            b"\x1b[32mVisit \x1b[0mhttps://example.com/login\x1b[0m\n",
            b"",
        ]
    )

    result = await _read_until(stream=reader, pattern=_URL_RE, timeout=5.0)
    assert result == "https://example.com/login"


@pytest.mark.asyncio
async def test_interactive_login_success():
    """Successful login: URL found, code sent, returns True."""
    proc = AsyncMock()
    proc.returncode = None
    proc.stdin = AsyncMock()
    proc.stdout = AsyncMock(spec=asyncio.StreamReader)
    proc.stdout.read = AsyncMock(
        side_effect=[
            b"Claude REPL ready\n",
            b"Visit https://accounts.example.com/oauth?state=xyz to log in\n",
            b"",
        ]
    )
    proc.wait = AsyncMock(return_value=0)

    send_message = AsyncMock()
    wait_for_reply = AsyncMock(return_value="myauthcode123")

    with (
        patch(
            "pyclaudius.login.asyncio.create_subprocess_exec",
            return_value=proc,
        ) as mock_exec,
        patch("pyclaudius.login.asyncio.sleep", new_callable=AsyncMock),
    ):
        result = await interactive_login(
            claude_path="claude",
            send_message=send_message,
            wait_for_reply=wait_for_reply,
        )

    assert result is True
    # URL was relayed to the user.
    send_message.assert_any_call(
        "Please visit this URL to log in:\nhttps://accounts.example.com/oauth?state=xyz"
    )
    # Auth code was written to REPL stdin.
    proc.stdin.write.assert_any_call(b"myauthcode123\r")

    # Env uses minimal _build_subprocess_env() + TERM.
    env = mock_exec.call_args.kwargs["env"]
    assert env["TERM"] == "xterm-256color"
    assert set(env.keys()) <= {"HOME", "PATH", "TERM"}


@pytest.mark.asyncio
async def test_interactive_login_no_url_found():
    """Returns False when no OAuth URL appears in REPL output."""
    proc = AsyncMock()
    proc.returncode = None
    proc.stdin = AsyncMock()
    proc.stdout = AsyncMock(spec=asyncio.StreamReader)
    proc.stdout.read = AsyncMock(
        side_effect=[
            b"Some output without a URL\n",
            b"",
        ]
    )
    proc.wait = AsyncMock(return_value=0)

    send_message = AsyncMock()
    wait_for_reply = AsyncMock()

    with (
        patch(
            "pyclaudius.login.asyncio.create_subprocess_exec",
            return_value=proc,
        ),
        patch("pyclaudius.login.asyncio.sleep", new_callable=AsyncMock),
    ):
        result = await interactive_login(
            claude_path="claude",
            send_message=send_message,
            wait_for_reply=wait_for_reply,
        )

    assert result is False
    send_message.assert_any_call("Login failed: no OAuth URL found in CLI output.")
    wait_for_reply.assert_not_called()


@pytest.mark.asyncio
async def test_interactive_login_timeout_waiting_for_reply():
    """Returns False when user doesn't reply with auth code in time."""
    proc = AsyncMock()
    proc.returncode = None
    proc.stdin = AsyncMock()
    proc.stdout = AsyncMock(spec=asyncio.StreamReader)
    proc.stdout.read = AsyncMock(
        side_effect=[
            b"Visit https://example.com/auth to log in\n",
            b"",
        ]
    )
    proc.wait = AsyncMock(return_value=0)

    send_message = AsyncMock()

    async def never_reply() -> str:
        # Use a Future that never resolves — immune to asyncio.sleep mocking.
        await asyncio.get_running_loop().create_future()
        return "unreachable"

    with (
        patch(
            "pyclaudius.login.asyncio.create_subprocess_exec",
            return_value=proc,
        ),
        patch("pyclaudius.login.asyncio.sleep", new_callable=AsyncMock),
    ):
        result = await interactive_login(
            claude_path="claude",
            send_message=send_message,
            wait_for_reply=never_reply,
            timeout=0.1,
        )

    assert result is False
    send_message.assert_any_call("Login timed out waiting for the auth code.")


@pytest.mark.asyncio
async def test_interactive_login_script_not_found():
    """Returns False when script or Claude CLI is not found."""
    send_message = AsyncMock()
    wait_for_reply = AsyncMock()

    with patch(
        "pyclaudius.login.asyncio.create_subprocess_exec",
        side_effect=FileNotFoundError,
    ):
        result = await interactive_login(
            claude_path="/nonexistent/claude",
            send_message=send_message,
            wait_for_reply=wait_for_reply,
        )

    assert result is False
    send_message.assert_any_call("Login failed: Claude CLI not found.")
