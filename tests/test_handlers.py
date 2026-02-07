from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from pyclaudius.handlers import (
    check_authorized,
    handle_document,
    handle_photo,
    handle_text,
)


def test_check_authorized_match():
    assert check_authorized(12345, allowed_user_id="12345") is True


def test_check_authorized_mismatch():
    assert check_authorized(12345, allowed_user_id="99999") is False


def test_check_authorized_string_conversion():
    assert check_authorized(12345, allowed_user_id="12345") is True


def _make_context(tmp_path):
    context = MagicMock()
    context.bot_data = {
        "settings": MagicMock(
            telegram_user_id="12345",
            claude_path="claude",
            session_file=tmp_path / "session.json",
            uploads_dir=tmp_path / "uploads",
        ),
        "session": {"session_id": None, "last_activity": ""},
    }
    context.bot = AsyncMock()
    return context


def _make_update(*, user_id=12345, text="hello"):
    update = MagicMock()
    update.effective_user.id = user_id
    update.message.text = text
    update.message.caption = None
    update.message.message_id = 1
    update.message.reply_text = AsyncMock()
    update.message.chat.send_action = AsyncMock()
    return update


@pytest.mark.asyncio
async def test_handle_text_unauthorized(tmp_path):
    update = _make_update(user_id=99999)
    context = _make_context(tmp_path)
    await handle_text(update, context)
    update.message.reply_text.assert_called_once_with("This bot is private.")


@pytest.mark.asyncio
async def test_handle_text_success(tmp_path):
    update = _make_update(text="hello claude")
    context = _make_context(tmp_path)
    with patch("pyclaudius.handlers.call_claude", new_callable=AsyncMock) as mock_claude:
        mock_claude.return_value = ("Hi there!", "session-abc")
        await handle_text(update, context)
        mock_claude.assert_called_once()
        update.message.reply_text.assert_called_once_with("Hi there!")
        assert context.bot_data["session"]["session_id"] == "session-abc"


@pytest.mark.asyncio
async def test_handle_text_no_session_update(tmp_path):
    update = _make_update(text="test")
    context = _make_context(tmp_path)
    with patch("pyclaudius.handlers.call_claude", new_callable=AsyncMock) as mock_claude:
        mock_claude.return_value = ("response", None)
        await handle_text(update, context)
        assert context.bot_data["session"]["session_id"] is None


@pytest.mark.asyncio
async def test_handle_photo_success(tmp_path):
    uploads = tmp_path / "uploads"
    uploads.mkdir()

    update = _make_update()
    photo_mock = MagicMock()
    photo_mock.file_id = "photo123"
    update.message.photo = [MagicMock(), photo_mock]

    context = _make_context(tmp_path)
    file_mock = AsyncMock()
    context.bot.get_file.return_value = file_mock

    with patch("pyclaudius.handlers.call_claude", new_callable=AsyncMock) as mock_claude:
        mock_claude.return_value = ("Nice photo!", None)
        await handle_photo(update, context)
        mock_claude.assert_called_once()
        update.message.reply_text.assert_called_once_with("Nice photo!")
        context.bot.get_file.assert_called_once_with("photo123")


@pytest.mark.asyncio
async def test_handle_document_success(tmp_path):
    uploads = tmp_path / "uploads"
    uploads.mkdir()

    update = _make_update()
    update.message.document = MagicMock()
    update.message.document.file_id = "doc123"
    update.message.document.file_name = "test.pdf"

    context = _make_context(tmp_path)
    file_mock = AsyncMock()
    context.bot.get_file.return_value = file_mock

    with patch("pyclaudius.handlers.call_claude", new_callable=AsyncMock) as mock_claude:
        mock_claude.return_value = ("Document analyzed!", None)
        await handle_document(update, context)
        mock_claude.assert_called_once()
        update.message.reply_text.assert_called_once_with("Document analyzed!")


@pytest.mark.asyncio
async def test_handle_photo_unauthorized(tmp_path):
    update = _make_update(user_id=99999)
    update.message.photo = [MagicMock()]
    context = _make_context(tmp_path)
    await handle_photo(update, context)
    update.message.reply_text.assert_called_once_with("This bot is private.")


@pytest.mark.asyncio
async def test_handle_document_unauthorized(tmp_path):
    update = _make_update(user_id=99999)
    update.message.document = MagicMock()
    context = _make_context(tmp_path)
    await handle_document(update, context)
    update.message.reply_text.assert_called_once_with("This bot is private.")
