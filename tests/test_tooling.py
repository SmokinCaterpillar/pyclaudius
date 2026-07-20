from unittest.mock import AsyncMock, MagicMock

import pytest

from pyclaudius.tooling import (
    authorized,
    check_authorized,
    is_auth_error,
    is_empty_response,
    is_session_limit_error,
    is_usage_credits_error,
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


@pytest.mark.parametrize(
    "text",
    [
        "You've hit your session limit · resets 5pm (UTC)",
        "You've hit your session limit",
    ],
)
def test_is_session_limit_error_matches(text: str):
    assert is_session_limit_error(response=text) is True


@pytest.mark.parametrize(
    "text",
    [
        "Hello from Claude",
        "Error: something went wrong",
        "API Error: 429 rate limit exceeded",
    ],
)
def test_is_session_limit_error_no_match(text: str):
    assert is_session_limit_error(response=text) is False


@pytest.mark.parametrize(
    "text",
    [
        "API Error: Usage credits required for 1M context · turn on usage credits "
        "at claude.ai/settings/usage, or use --model to switch to standard context",
        "Usage credits required for 1M context",
    ],
)
def test_is_usage_credits_error_matches(text: str):
    assert is_usage_credits_error(response=text) is True


@pytest.mark.parametrize(
    "text",
    [
        "Hello from Claude",
        "Error: something went wrong",
        "You've hit your session limit · resets 5pm (UTC)",
    ],
)
def test_is_usage_credits_error_no_match(text: str):
    assert is_usage_credits_error(response=text) is False


@pytest.mark.parametrize("text", ["", "   ", "\n\t  \n"])
def test_is_empty_response_matches(text: str):
    assert is_empty_response(response=text) is True


@pytest.mark.parametrize(
    "text",
    [
        "Hello",
        "[SILENT]",
        "Error: No conversation found with session ID: abc",
    ],
)
def test_is_empty_response_no_match(text: str):
    assert is_empty_response(response=text) is False
