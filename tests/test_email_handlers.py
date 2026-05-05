"""Tests for email Telegram command handlers in pyclaudius.handlers."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from pyclaudius.handlers import (
    handle_deleteallreadmail_command,
    handle_downloadnewmail_command,
)


def _make_context(*, email_enabled: bool = True):
    context = MagicMock()
    context.bot_data = {
        "settings": MagicMock(
            telegram_user_id="12345",
            email_enabled=email_enabled,
            email_imap_host="imap.gmail.com",
            email_imap_port=993,
            email_user="test@gmail.com",
            email_password="secret",
            emails_dir="/tmp/emails",
        ),
    }
    context.bot = AsyncMock()
    return context


def _make_update(*, user_id: int = 12345, text: str = "hello"):
    update = MagicMock()
    update.effective_user.id = user_id
    update.message.text = text
    update.message.caption = None
    update.message.message_id = 1
    update.message.reply_text = AsyncMock()
    update.message.chat.send_action = AsyncMock()
    return update


# --- handle_downloadnewmail_command ---


@pytest.mark.asyncio
async def test_downloadnewmail_unauthorized():
    update = _make_update(user_id=99999, text="/downloadnewmail")
    context = _make_context()
    await handle_downloadnewmail_command(update, context)
    update.message.reply_text.assert_called_once_with("This bot is private.")


@pytest.mark.asyncio
async def test_downloadnewmail_disabled():
    update = _make_update(text="/downloadnewmail")
    context = _make_context(email_enabled=False)
    await handle_downloadnewmail_command(update, context)
    update.message.reply_text.assert_called_once_with("Email integration is disabled.")


@pytest.mark.asyncio
@patch("pyclaudius.handlers.download_new_mail_op")
async def test_downloadnewmail_no_new_mail(mock_download):
    mock_download.return_value = "No new emails."
    update = _make_update(text="/downloadnewmail")
    context = _make_context()
    await handle_downloadnewmail_command(update, context)
    update.message.reply_text.assert_called_once_with("No new emails.")


@pytest.mark.asyncio
@patch("pyclaudius.handlers.download_new_mail_op")
async def test_downloadnewmail_success(mock_download):
    mock_download.return_value = (
        "Downloaded 2 email(s):\n"
        "  - email_Test_2024-01-01.md\n"
        "  - email_Other_2024-01-02.md"
    )
    update = _make_update(text="/downloadnewmail")
    context = _make_context()
    await handle_downloadnewmail_command(update, context)
    reply = update.message.reply_text.call_args[0][0]
    assert "Downloaded 2 email(s)" in reply
    assert "email_Test_2024-01-01.md" in reply
    assert "email_Other_2024-01-02.md" in reply


@pytest.mark.asyncio
@patch("pyclaudius.handlers.download_new_mail_op")
async def test_downloadnewmail_error(mock_download):
    mock_download.side_effect = Exception("IMAP connection failed")
    update = _make_update(text="/downloadnewmail")
    context = _make_context()
    await handle_downloadnewmail_command(update, context)
    update.message.reply_text.assert_called_once_with(
        "Failed to download emails. Check logs."
    )


# --- handle_deleteallreadmail_command ---


@pytest.mark.asyncio
async def test_deleteallreadmail_unauthorized():
    update = _make_update(user_id=99999, text="/deleteallreadmail")
    context = _make_context()
    await handle_deleteallreadmail_command(update, context)
    update.message.reply_text.assert_called_once_with("This bot is private.")


@pytest.mark.asyncio
async def test_deleteallreadmail_disabled():
    update = _make_update(text="/deleteallreadmail")
    context = _make_context(email_enabled=False)
    await handle_deleteallreadmail_command(update, context)
    update.message.reply_text.assert_called_once_with("Email integration is disabled.")


@pytest.mark.asyncio
@patch("pyclaudius.handlers.delete_read_mail_op")
async def test_deleteallreadmail_none_to_delete(mock_delete):
    mock_delete.return_value = "No read emails to delete."
    update = _make_update(text="/deleteallreadmail")
    context = _make_context()
    await handle_deleteallreadmail_command(update, context)
    update.message.reply_text.assert_called_once_with("No read emails to delete.")


@pytest.mark.asyncio
@patch("pyclaudius.handlers.delete_read_mail_op")
async def test_deleteallreadmail_success(mock_delete):
    mock_delete.return_value = "Deleted 5 read email(s) from server."
    update = _make_update(text="/deleteallreadmail")
    context = _make_context()
    await handle_deleteallreadmail_command(update, context)
    update.message.reply_text.assert_called_once_with(
        "Deleted 5 read email(s) from server."
    )


@pytest.mark.asyncio
@patch("pyclaudius.handlers.delete_read_mail_op")
async def test_deleteallreadmail_error(mock_delete):
    mock_delete.side_effect = Exception("IMAP connection failed")
    update = _make_update(text="/deleteallreadmail")
    context = _make_context()
    await handle_deleteallreadmail_command(update, context)
    update.message.reply_text.assert_called_once_with(
        "Failed to delete emails. Check logs."
    )
