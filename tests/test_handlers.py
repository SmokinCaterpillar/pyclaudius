from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from pyclaudius.handlers import (
    check_authorized,
    handle_document,
    handle_forget_command,
    handle_remember_command,
    handle_photo,
    handle_text,
)


def test_check_authorized_match():
    assert check_authorized(12345, allowed_user_id="12345") is True


def test_check_authorized_mismatch():
    assert check_authorized(12345, allowed_user_id="99999") is False


def test_check_authorized_string_conversion():
    assert check_authorized(12345, allowed_user_id="12345") is True


def _make_context(tmp_path, *, memory_enabled=False, max_memories=100, allowed_tools=None):
    context = MagicMock()
    context.bot_data = {
        "settings": MagicMock(
            telegram_user_id="12345",
            claude_path="claude",
            session_file=tmp_path / "session.json",
            uploads_dir=tmp_path / "uploads",
            memory_enabled=memory_enabled,
            max_memories=max_memories,
            memory_file=tmp_path / "memory.json",
            allowed_tools=allowed_tools or [],
            claude_work_dir=tmp_path / "claude-work",
        ),
        "session": {"session_id": None, "last_activity": ""},
        "memory": [],
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


@pytest.mark.asyncio
async def test_handle_text_memory_injected_into_prompt(tmp_path):
    update = _make_update(text="hello")
    context = _make_context(tmp_path, memory_enabled=True)
    context.bot_data["memory"] = ["user likes coffee"]
    with patch("pyclaudius.handlers.call_claude", new_callable=AsyncMock) as mock_claude:
        mock_claude.return_value = ("Hi!", None)
        await handle_text(update, context)
        prompt_arg = mock_claude.call_args.kwargs["prompt"]
        assert "## Memory" in prompt_arg
        assert "- user likes coffee" in prompt_arg


@pytest.mark.asyncio
async def test_handle_text_memory_not_injected_when_disabled(tmp_path):
    update = _make_update(text="hello")
    context = _make_context(tmp_path, memory_enabled=False)
    context.bot_data["memory"] = ["user likes coffee"]
    with patch("pyclaudius.handlers.call_claude", new_callable=AsyncMock) as mock_claude:
        mock_claude.return_value = ("Hi!", None)
        await handle_text(update, context)
        prompt_arg = mock_claude.call_args.kwargs["prompt"]
        assert "## Memory" not in prompt_arg


@pytest.mark.asyncio
async def test_handle_text_remember_tags_extracted_and_stored(tmp_path):
    update = _make_update(text="hello")
    context = _make_context(tmp_path, memory_enabled=True)
    with patch("pyclaudius.handlers.call_claude", new_callable=AsyncMock) as mock_claude:
        mock_claude.return_value = ("Got it [REMEMBER: user likes tea]", None)
        await handle_text(update, context)
        assert "user likes tea" in context.bot_data["memory"]


@pytest.mark.asyncio
async def test_handle_text_remember_tags_stripped_from_response(tmp_path):
    update = _make_update(text="hello")
    context = _make_context(tmp_path, memory_enabled=True)
    with patch("pyclaudius.handlers.call_claude", new_callable=AsyncMock) as mock_claude:
        mock_claude.return_value = ("Got it [REMEMBER: user likes tea] bye", None)
        await handle_text(update, context)
        update.message.reply_text.assert_called_once_with("Got it  bye")


@pytest.mark.asyncio
async def test_handle_text_remember_tags_not_processed_when_disabled(tmp_path):
    update = _make_update(text="hello")
    context = _make_context(tmp_path, memory_enabled=False)
    with patch("pyclaudius.handlers.call_claude", new_callable=AsyncMock) as mock_claude:
        mock_claude.return_value = ("Got it [REMEMBER: user likes tea]", None)
        await handle_text(update, context)
        assert context.bot_data["memory"] == []
        update.message.reply_text.assert_called_once_with(
            "Got it [REMEMBER: user likes tea]"
        )


@pytest.mark.asyncio
async def test_handle_text_forget_tags_remove_memories(tmp_path):
    update = _make_update(text="I no longer like coffee")
    context = _make_context(tmp_path, memory_enabled=True)
    context.bot_data["memory"] = ["user likes coffee", "user likes tea"]
    with patch("pyclaudius.handlers.call_claude", new_callable=AsyncMock) as mock_claude:
        mock_claude.return_value = ("OK [FORGET: coffee] noted", None)
        await handle_text(update, context)
        assert "user likes coffee" not in context.bot_data["memory"]
        assert "user likes tea" in context.bot_data["memory"]


@pytest.mark.asyncio
async def test_handle_text_forget_tags_stripped_from_response(tmp_path):
    update = _make_update(text="forget coffee")
    context = _make_context(tmp_path, memory_enabled=True)
    context.bot_data["memory"] = ["user likes coffee"]
    with patch("pyclaudius.handlers.call_claude", new_callable=AsyncMock) as mock_claude:
        mock_claude.return_value = ("Done [FORGET: coffee] bye", None)
        await handle_text(update, context)
        update.message.reply_text.assert_called_once_with("Done  bye")


@pytest.mark.asyncio
async def test_handle_remember_command_lists_facts(tmp_path):
    update = _make_update()
    context = _make_context(tmp_path, memory_enabled=True)
    context.bot_data["memory"] = ["likes coffee", "likes tea"]
    await handle_remember_command(update, context)
    reply = update.message.reply_text.call_args[0][0]
    assert "likes coffee" in reply
    assert "likes tea" in reply
    assert "2" in reply


@pytest.mark.asyncio
async def test_handle_remember_command_empty(tmp_path):
    update = _make_update()
    context = _make_context(tmp_path, memory_enabled=True)
    await handle_remember_command(update, context)
    update.message.reply_text.assert_called_once_with("No memories stored.")


@pytest.mark.asyncio
async def test_handle_remember_command_disabled(tmp_path):
    update = _make_update()
    context = _make_context(tmp_path, memory_enabled=False)
    await handle_remember_command(update, context)
    update.message.reply_text.assert_called_once_with("Memory is disabled.")


@pytest.mark.asyncio
async def test_handle_forget_command_removes_matching(tmp_path):
    update = _make_update(text="/forget coffee")
    context = _make_context(tmp_path, memory_enabled=True)
    context.bot_data["memory"] = ["likes coffee", "likes tea"]
    await handle_forget_command(update, context)
    assert context.bot_data["memory"] == ["likes tea"]
    reply = update.message.reply_text.call_args[0][0]
    assert "Removed 1" in reply


@pytest.mark.asyncio
async def test_handle_forget_command_no_match(tmp_path):
    update = _make_update(text="/forget python")
    context = _make_context(tmp_path, memory_enabled=True)
    context.bot_data["memory"] = ["likes coffee"]
    await handle_forget_command(update, context)
    assert context.bot_data["memory"] == ["likes coffee"]
    reply = update.message.reply_text.call_args[0][0]
    assert "No memories matching" in reply


@pytest.mark.asyncio
async def test_handle_forget_command_no_keyword(tmp_path):
    update = _make_update(text="/forget")
    context = _make_context(tmp_path, memory_enabled=True)
    await handle_forget_command(update, context)
    update.message.reply_text.assert_called_once_with("Usage: /forget <keyword>")
