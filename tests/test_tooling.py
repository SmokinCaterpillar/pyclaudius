from unittest.mock import AsyncMock, MagicMock

import pytest

from pyclaudius.tooling import authorized, check_authorized


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
