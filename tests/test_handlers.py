from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from pyclaudius.handlers import (
    handle_clearbacklog_command,
    handle_document,
    handle_forget_command,
    handle_help_command,
    handle_listbacklog_command,
    handle_listmemory_command,
    handle_photo,
    handle_remember_command,
    handle_replaybacklog_command,
    handle_replayone_command,
    handle_text,
)


def _make_context(
    tmp_path,
    *,
    memory_enabled=False,
    max_memories=100,
    allowed_tools=None,
    cron_enabled=False,
    backlog_enabled=True,
):
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
            cron_enabled=cron_enabled,
            cron_file=tmp_path / "cron.json",
            backlog_enabled=backlog_enabled,
            backlog_file=tmp_path / "backlog.json",
        ),
        "session": {"session_id": None, "last_activity": ""},
        "memory": [],
        "cron_jobs": [],
        "backlog": [],
        "scheduler": MagicMock(),
        "application": MagicMock(),
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
    with patch(
        "pyclaudius.handlers.call_claude", new_callable=AsyncMock
    ) as mock_claude:
        mock_claude.return_value = ("Hi there!", "session-abc")
        await handle_text(update, context)
        mock_claude.assert_called_once()
        kwargs = mock_claude.call_args.kwargs
        assert kwargs["bot_data"] is context.bot_data
        assert kwargs["user_message"] == "hello claude"
        update.message.reply_text.assert_called_once_with("Hi there!")
        assert context.bot_data["session"]["session_id"] == "session-abc"


@pytest.mark.asyncio
async def test_handle_text_no_session_update(tmp_path):
    update = _make_update(text="test")
    context = _make_context(tmp_path)
    with patch(
        "pyclaudius.handlers.call_claude", new_callable=AsyncMock
    ) as mock_claude:
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

    with patch(
        "pyclaudius.handlers.call_claude", new_callable=AsyncMock
    ) as mock_claude:
        mock_claude.return_value = ("Nice photo!", None)
        await handle_photo(update, context)
        mock_claude.assert_called_once()
        kwargs = mock_claude.call_args.kwargs
        assert kwargs["bot_data"] is context.bot_data
        assert kwargs["user_message"] == "Analyze this image."
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

    with patch(
        "pyclaudius.handlers.call_claude", new_callable=AsyncMock
    ) as mock_claude:
        mock_claude.return_value = ("Document analyzed!", None)
        await handle_document(update, context)
        mock_claude.assert_called_once()
        kwargs = mock_claude.call_args.kwargs
        assert kwargs["bot_data"] is context.bot_data
        assert kwargs["user_message"] == "Analyze: test.pdf"
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
    with patch(
        "pyclaudius.handlers.call_claude", new_callable=AsyncMock
    ) as mock_claude:
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
    with patch(
        "pyclaudius.handlers.call_claude", new_callable=AsyncMock
    ) as mock_claude:
        mock_claude.return_value = ("Hi!", None)
        await handle_text(update, context)
        prompt_arg = mock_claude.call_args.kwargs["prompt"]
        assert "## Memory" not in prompt_arg


@pytest.mark.asyncio
async def test_handle_remember_command_adds_fact(tmp_path):
    update = _make_update(text="/remember user likes coffee")
    context = _make_context(tmp_path, memory_enabled=True)
    await handle_remember_command(update, context)
    assert "user likes coffee" in context.bot_data["memory"]
    reply = update.message.reply_text.call_args[0][0]
    assert "Remembered" in reply
    assert "user likes coffee" in reply


@pytest.mark.asyncio
async def test_handle_remember_command_no_text_shows_usage(tmp_path):
    update = _make_update(text="/remember")
    context = _make_context(tmp_path, memory_enabled=True)
    await handle_remember_command(update, context)
    update.message.reply_text.assert_called_once_with("Usage: /remember <fact>")


@pytest.mark.asyncio
async def test_handle_remember_command_disabled(tmp_path):
    update = _make_update(text="/remember something")
    context = _make_context(tmp_path, memory_enabled=False)
    await handle_remember_command(update, context)
    update.message.reply_text.assert_called_once_with("Memory is disabled.")


@pytest.mark.asyncio
async def test_handle_remember_command_unauthorized(tmp_path):
    update = _make_update(user_id=99999, text="/remember something")
    context = _make_context(tmp_path, memory_enabled=True)
    await handle_remember_command(update, context)
    update.message.reply_text.assert_called_once_with("This bot is private.")


@pytest.mark.asyncio
async def test_handle_listmemory_command_lists_facts(tmp_path):
    update = _make_update()
    context = _make_context(tmp_path, memory_enabled=True)
    context.bot_data["memory"] = ["likes coffee", "likes tea"]
    await handle_listmemory_command(update, context)
    reply = update.message.reply_text.call_args[0][0]
    assert "likes coffee" in reply
    assert "likes tea" in reply
    assert "2" in reply


@pytest.mark.asyncio
async def test_handle_listmemory_command_empty(tmp_path):
    update = _make_update()
    context = _make_context(tmp_path, memory_enabled=True)
    await handle_listmemory_command(update, context)
    update.message.reply_text.assert_called_once_with("No memories stored.")


@pytest.mark.asyncio
async def test_handle_listmemory_command_disabled(tmp_path):
    update = _make_update()
    context = _make_context(tmp_path, memory_enabled=False)
    await handle_listmemory_command(update, context)
    update.message.reply_text.assert_called_once_with("Memory is disabled.")


@pytest.mark.asyncio
async def test_handle_listmemory_command_unauthorized(tmp_path):
    update = _make_update(user_id=99999)
    context = _make_context(tmp_path, memory_enabled=True)
    await handle_listmemory_command(update, context)
    update.message.reply_text.assert_called_once_with("This bot is private.")


@pytest.mark.asyncio
async def test_handle_help_command_shows_commands(tmp_path):
    update = _make_update()
    context = _make_context(tmp_path)
    await handle_help_command(update, context)
    reply = update.message.reply_text.call_args[0][0]
    assert "/help" in reply
    assert "/remember" in reply
    assert "/listmemory" in reply
    assert "/forget" in reply


@pytest.mark.asyncio
async def test_handle_help_command_unauthorized(tmp_path):
    update = _make_update(user_id=99999)
    context = _make_context(tmp_path)
    await handle_help_command(update, context)
    update.message.reply_text.assert_called_once_with("This bot is private.")


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
    update.message.reply_text.assert_called_once_with(
        "Usage: /forget <keyword or number>"
    )


@pytest.mark.asyncio
async def test_handle_forget_command_by_index(tmp_path):
    update = _make_update(text="/forget 2")
    context = _make_context(tmp_path, memory_enabled=True)
    context.bot_data["memory"] = ["likes coffee", "likes tea", "likes water"]
    await handle_forget_command(update, context)
    assert context.bot_data["memory"] == ["likes coffee", "likes water"]
    reply = update.message.reply_text.call_args[0][0]
    assert reply == 'Removed memory 2: "likes tea"'


@pytest.mark.asyncio
async def test_handle_forget_command_index_out_of_range(tmp_path):
    update = _make_update(text="/forget 5")
    context = _make_context(tmp_path, memory_enabled=True)
    context.bot_data["memory"] = ["likes coffee", "likes tea"]
    await handle_forget_command(update, context)
    reply = update.message.reply_text.call_args[0][0]
    assert "Invalid index 5" in reply
    assert context.bot_data["memory"] == ["likes coffee", "likes tea"]


@pytest.mark.asyncio
async def test_handle_forget_command_index_zero(tmp_path):
    update = _make_update(text="/forget 0")
    context = _make_context(tmp_path, memory_enabled=True)
    context.bot_data["memory"] = ["likes coffee"]
    await handle_forget_command(update, context)
    reply = update.message.reply_text.call_args[0][0]
    assert "Invalid index 0" in reply
    assert context.bot_data["memory"] == ["likes coffee"]


@pytest.mark.asyncio
async def test_handle_remember_command_warns_on_overflow(tmp_path):
    update = _make_update(text="/remember likes water")
    context = _make_context(tmp_path, memory_enabled=True, max_memories=2)
    context.bot_data["memory"] = ["likes coffee", "likes tea"]
    await handle_remember_command(update, context)
    reply = update.message.reply_text.call_args[0][0]
    assert 'Remembered: "likes water"' in reply
    assert "Warning: memory full (2)" in reply
    assert 'Oldest fact forgotten: "likes coffee"' in reply


@pytest.mark.asyncio
async def test_handle_remember_command_no_warning_under_max(tmp_path):
    update = _make_update(text="/remember likes water")
    context = _make_context(tmp_path, memory_enabled=True, max_memories=10)
    context.bot_data["memory"] = ["likes coffee"]
    await handle_remember_command(update, context)
    reply = update.message.reply_text.call_args[0][0]
    assert 'Remembered: "likes water"' in reply
    assert "Warning" not in reply


@pytest.mark.asyncio
async def test_handle_text_cron_count_in_prompt(tmp_path):
    update = _make_update(text="hello")
    context = _make_context(tmp_path, cron_enabled=True)
    context.bot_data["cron_jobs"] = [
        {
            "id": "a",
            "job_type": "cron",
            "expression": "*/5 * * * *",
            "prompt": "test",
            "created_at": "2026-01-01T00:00:00",
        }
    ]
    with patch(
        "pyclaudius.handlers.call_claude", new_callable=AsyncMock
    ) as mock_claude:
        mock_claude.return_value = ("Hi!", None)
        await handle_text(update, context)
        prompt_arg = mock_claude.call_args.kwargs["prompt"]
        assert "1 scheduled task(s)" in prompt_arg


@pytest.mark.asyncio
async def test_handle_text_scheduled_silent_suppresses_reply(tmp_path):
    update = _make_update(text="check weather")
    update.update_id = 42
    context = _make_context(tmp_path, cron_enabled=True)
    context.bot_data["_scheduled_update_ids"] = {42}
    with patch(
        "pyclaudius.handlers.call_claude", new_callable=AsyncMock
    ) as mock_claude:
        mock_claude.return_value = ("[SILENT]", None)
        await handle_text(update, context)
        update.message.reply_text.assert_not_called()
        assert 42 not in context.bot_data.get("_scheduled_update_ids", set())


@pytest.mark.asyncio
async def test_handle_text_scheduled_without_silent_sends_reply(tmp_path):
    update = _make_update(text="check weather")
    update.update_id = 43
    context = _make_context(tmp_path, cron_enabled=True)
    context.bot_data["_scheduled_update_ids"] = {43}
    with patch(
        "pyclaudius.handlers.call_claude", new_callable=AsyncMock
    ) as mock_claude:
        mock_claude.return_value = ("It's sunny today!", None)
        await handle_text(update, context)
        update.message.reply_text.assert_called_once_with("It's sunny today!")
        assert 43 not in context.bot_data.get("_scheduled_update_ids", set())


@pytest.mark.asyncio
async def test_handle_help_command_shows_cron_commands(tmp_path):
    update = _make_update()
    context = _make_context(tmp_path)
    await handle_help_command(update, context)
    reply = update.message.reply_text.call_args[0][0]
    assert "/addcron" in reply
    assert "/schedule" in reply
    assert "/listcron" in reply
    assert "/removecron" in reply
    assert "/testcron" in reply


@pytest.mark.asyncio
async def test_handle_text_passes_allowed_tools(tmp_path):
    """Settings allowed_tools are passed to call_claude."""
    update = _make_update(text="hello")
    context = _make_context(tmp_path, allowed_tools=["WebSearch", "WebFetch"])
    with patch(
        "pyclaudius.handlers.call_claude", new_callable=AsyncMock
    ) as mock_claude:
        mock_claude.return_value = ("Hi!", None)
        await handle_text(update, context)
        tools_arg = mock_claude.call_args.kwargs["allowed_tools"]
        assert tools_arg == ["WebSearch", "WebFetch"]


@pytest.mark.asyncio
async def test_handle_text_includes_mcp_allowed_tools(tmp_path):
    """MCP tool names from bot_data are appended to allowed_tools."""
    update = _make_update(text="hello")
    context = _make_context(tmp_path, allowed_tools=["WebSearch"])
    context.bot_data["mcp_allowed_tools"] = ["mcp__pyclaudius__*"]
    with patch(
        "pyclaudius.handlers.call_claude", new_callable=AsyncMock
    ) as mock_claude:
        mock_claude.return_value = ("Hi!", None)
        await handle_text(update, context)
        tools_arg = mock_claude.call_args.kwargs["allowed_tools"]
        assert tools_arg == ["WebSearch", "mcp__pyclaudius__*"]


# --- Backlog command tests ---


@pytest.mark.asyncio
async def test_handle_help_command_shows_backlog_commands(tmp_path):
    update = _make_update()
    context = _make_context(tmp_path)
    await handle_help_command(update, context)
    reply = update.message.reply_text.call_args[0][0]
    assert "/listbacklog" in reply
    assert "/clearbacklog" in reply
    assert "/replaybacklog" in reply
    assert "/replayone" in reply


@pytest.mark.asyncio
async def test_handle_listbacklog_command_empty(tmp_path):
    update = _make_update()
    context = _make_context(tmp_path)
    await handle_listbacklog_command(update, context)
    reply = update.message.reply_text.call_args[0][0]
    assert "empty" in reply.lower()


@pytest.mark.asyncio
async def test_handle_listbacklog_command_with_items(tmp_path):
    update = _make_update()
    context = _make_context(tmp_path)
    context.bot_data["backlog"] = [
        {"prompt": "hello world", "created_at": "2026-01-01T00:00:00"},
    ]
    await handle_listbacklog_command(update, context)
    reply = update.message.reply_text.call_args[0][0]
    assert "hello world" in reply
    assert "1" in reply


@pytest.mark.asyncio
async def test_handle_listbacklog_command_disabled(tmp_path):
    update = _make_update()
    context = _make_context(tmp_path, backlog_enabled=False)
    await handle_listbacklog_command(update, context)
    update.message.reply_text.assert_called_once_with("Backlog is disabled.")


@pytest.mark.asyncio
async def test_handle_listbacklog_command_unauthorized(tmp_path):
    update = _make_update(user_id=99999)
    context = _make_context(tmp_path)
    await handle_listbacklog_command(update, context)
    update.message.reply_text.assert_called_once_with("This bot is private.")


@pytest.mark.asyncio
async def test_handle_clearbacklog_command(tmp_path):
    update = _make_update()
    context = _make_context(tmp_path)
    context.bot_data["backlog"] = [
        {"prompt": "hello", "created_at": "2026-01-01T00:00:00"},
    ]
    await handle_clearbacklog_command(update, context)
    assert context.bot_data["backlog"] == []
    reply = update.message.reply_text.call_args[0][0]
    assert "cleared" in reply.lower()


@pytest.mark.asyncio
async def test_handle_clearbacklog_command_disabled(tmp_path):
    update = _make_update()
    context = _make_context(tmp_path, backlog_enabled=False)
    await handle_clearbacklog_command(update, context)
    update.message.reply_text.assert_called_once_with("Backlog is disabled.")


@pytest.mark.asyncio
async def test_handle_clearbacklog_command_unauthorized(tmp_path):
    update = _make_update(user_id=99999)
    context = _make_context(tmp_path)
    await handle_clearbacklog_command(update, context)
    update.message.reply_text.assert_called_once_with("This bot is private.")


@pytest.mark.asyncio
async def test_handle_replaybacklog_command_empty(tmp_path):
    update = _make_update()
    context = _make_context(tmp_path)
    await handle_replaybacklog_command(update, context)
    update.message.reply_text.assert_called_once_with("Backlog is empty.")


@pytest.mark.asyncio
async def test_handle_replaybacklog_command_replays(tmp_path):
    update = _make_update()
    context = _make_context(tmp_path)
    context.bot_data["backlog"] = [
        {"prompt": "first question", "created_at": "2026-01-01T00:00:00"},
        {"prompt": "second question", "created_at": "2026-01-02T00:00:00"},
    ]
    with patch(
        "pyclaudius.handlers.call_claude", new_callable=AsyncMock
    ) as mock_claude:
        mock_claude.return_value = ("Answer!", "sess-1")
        await handle_replaybacklog_command(update, context)
        assert mock_claude.call_count == 2
        assert context.bot_data["backlog"] == []


@pytest.mark.asyncio
async def test_handle_replaybacklog_command_disabled(tmp_path):
    update = _make_update()
    context = _make_context(tmp_path, backlog_enabled=False)
    await handle_replaybacklog_command(update, context)
    update.message.reply_text.assert_called_once_with("Backlog is disabled.")


@pytest.mark.asyncio
async def test_handle_replaybacklog_command_unauthorized(tmp_path):
    update = _make_update(user_id=99999)
    context = _make_context(tmp_path)
    await handle_replaybacklog_command(update, context)
    update.message.reply_text.assert_called_once_with("This bot is private.")


@pytest.mark.asyncio
async def test_handle_replayone_command_success(tmp_path):
    update = _make_update(text="/replayone 1")
    context = _make_context(tmp_path)
    context.bot_data["backlog"] = [
        {"prompt": "hello world", "created_at": "2026-01-01T00:00:00"},
    ]
    with patch(
        "pyclaudius.handlers.call_claude", new_callable=AsyncMock
    ) as mock_claude:
        mock_claude.return_value = ("Answer!", "sess-1")
        await handle_replayone_command(update, context)
        mock_claude.assert_called_once()
        kwargs = mock_claude.call_args.kwargs
        assert kwargs["user_message"] == "hello world"
        assert context.bot_data["backlog"] == []


@pytest.mark.asyncio
async def test_handle_replayone_command_no_arg(tmp_path):
    update = _make_update(text="/replayone")
    context = _make_context(tmp_path)
    await handle_replayone_command(update, context)
    update.message.reply_text.assert_called_once_with("Usage: /replayone <number>")


@pytest.mark.asyncio
async def test_handle_replayone_command_invalid_index(tmp_path):
    update = _make_update(text="/replayone 5")
    context = _make_context(tmp_path)
    context.bot_data["backlog"] = [
        {"prompt": "hello", "created_at": "2026-01-01T00:00:00"},
    ]
    await handle_replayone_command(update, context)
    reply = update.message.reply_text.call_args[0][0]
    assert "Invalid index 5" in reply


@pytest.mark.asyncio
async def test_handle_replayone_command_disabled(tmp_path):
    update = _make_update(text="/replayone 1")
    context = _make_context(tmp_path, backlog_enabled=False)
    await handle_replayone_command(update, context)
    update.message.reply_text.assert_called_once_with("Backlog is disabled.")


@pytest.mark.asyncio
async def test_handle_replayone_command_unauthorized(tmp_path):
    update = _make_update(user_id=99999, text="/replayone 1")
    context = _make_context(tmp_path)
    await handle_replayone_command(update, context)
    update.message.reply_text.assert_called_once_with("This bot is private.")
