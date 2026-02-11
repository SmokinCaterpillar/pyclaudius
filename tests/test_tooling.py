from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from pyclaudius.tooling import (
    authorized,
    check_authorized,
    is_auth_error,
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
async def test_with_auth_retry_skips_when_disabled():
    """Auth error response returned as-is when auto_refresh_auth=False."""

    @with_auth_retry
    async def fake_claude(*, prompt: str) -> tuple[str, str | None]:
        return "authentication_error", "sess-1"

    result, session_id = await fake_claude(prompt="hi", auto_refresh_auth=False)
    assert result == "authentication_error"
    assert session_id == "sess-1"


@pytest.mark.asyncio
async def test_with_auth_retry_uses_interactive_login():
    """Calls interactive_login and retries when callbacks are provided."""
    call_count = 0

    @with_auth_retry
    async def fake_claude(*, prompt: str) -> tuple[str, str | None]:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return "authentication_error", "sess-1"
        return "Hello from Claude", "sess-1"

    send_msg = AsyncMock()
    wait_reply = AsyncMock()

    with patch(
        "pyclaudius.login.interactive_login", return_value=True,
    ) as mock_login:
        result, _session_id = await fake_claude(
            prompt="hi",
            auto_refresh_auth=True,
            auth_send_message=send_msg,
            auth_wait_for_reply=wait_reply,
        )
        assert result == "Hello from Claude"
        assert call_count == 2
        mock_login.assert_called_once()


@pytest.mark.asyncio
async def test_with_auth_retry_skips_interactive_without_callbacks():
    """No login attempt and auth error returned when callbacks are missing."""

    @with_auth_retry
    async def fake_claude(*, prompt: str) -> tuple[str, str | None]:
        return "authentication_error", "sess-1"

    result, session_id = await fake_claude(prompt="hi", auto_refresh_auth=True)
    assert result == "authentication_error"
    assert session_id == "sess-1"


@pytest.mark.asyncio
async def test_with_auth_retry_no_retry_on_login_failure():
    """Returns original error when interactive_login fails."""
    call_count = 0

    @with_auth_retry
    async def fake_claude(*, prompt: str) -> tuple[str, str | None]:
        nonlocal call_count
        call_count += 1
        return "authentication_error", "sess-1"

    send_msg = AsyncMock()
    wait_reply = AsyncMock()

    with patch(
        "pyclaudius.login.interactive_login", return_value=False,
    ):
        result, _session_id = await fake_claude(
            prompt="hi",
            auto_refresh_auth=True,
            auth_send_message=send_msg,
            auth_wait_for_reply=wait_reply,
        )
        assert result == "authentication_error"
        assert call_count == 1
