from unittest.mock import AsyncMock, MagicMock

import pytest

from pyclaudius.opencode_events import OpencodeResult
from pyclaudius.tooling import (
    authorized,
    check_authorized,
    is_api_error,
    is_auth_error,
    is_empty_response,
    is_rate_limit_error,
)


def _result(
    *,
    error_name: str | None = None,
    status_code: int | None = None,
    is_retryable: bool | None = None,
    text: str = "",
) -> OpencodeResult:
    """Build the parsed result of one run, with only the fields under test set."""
    return OpencodeResult(
        text=text,
        session_id="ses_x",
        error_name=error_name,
        error_message=None,
        status_code=status_code,
        is_retryable=is_retryable,
        finished=True,
        tokens=None,
        cost=None,
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


@pytest.mark.parametrize("status", [401, 403])
def test_is_auth_error_matches_status(status: int):
    """A missing or wrong TENSORX_API_KEY surfaces as an HTTP status, not prose."""
    assert (
        is_auth_error(result=_result(error_name="APIError", status_code=status)) is True
    )


def test_is_auth_error_matches_error_name():
    assert is_auth_error(result=_result(error_name="ProviderAuthError")) is True


@pytest.mark.parametrize("status", [None, 429, 500, 400])
def test_is_auth_error_no_match(status):
    assert (
        is_auth_error(result=_result(error_name="APIError", status_code=status))
        is False
    )


def test_is_auth_error_no_match_on_success():
    assert is_auth_error(result=_result(text="Hello")) is False


def test_is_rate_limit_error_matches_status():
    assert (
        is_rate_limit_error(result=_result(error_name="APIError", status_code=429))
        is True
    )


@pytest.mark.parametrize(
    "name", ["RateLimitError", "rate_limit", "rate-limit", "Rate Limit Exceeded"]
)
def test_is_rate_limit_error_matches_error_name(name: str):
    assert is_rate_limit_error(result=_result(error_name=name)) is True


@pytest.mark.parametrize("status", [None, 401, 500])
def test_is_rate_limit_error_no_match(status):
    assert (
        is_rate_limit_error(result=_result(error_name="APIError", status_code=status))
        is False
    )


def test_is_api_error_matches_any_error_event():
    assert is_api_error(result=_result(error_name="APIError", status_code=500)) is True


def test_is_api_error_no_match_on_success():
    assert is_api_error(result=_result(text="Hello")) is False


@pytest.mark.parametrize("text", ["", "   ", "\n\t  \n"])
def test_is_empty_response_matches(text: str):
    assert is_empty_response(response=text) is True


@pytest.mark.parametrize("text", ["Hello", "[SILENT]", "Error: Session not found"])
def test_is_empty_response_no_match(text: str):
    assert is_empty_response(response=text) is False
