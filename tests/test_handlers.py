from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from pyclaudius.handlers import (
    format_context_usage,
    handle_clear_command,
    handle_clearbacklog_command,
    handle_compact_command,
    handle_context_command,
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
    opencode_model="tensorx/moonshotai/kimi-k3",
    opencode_context_limit=1_048_576,
):
    context = MagicMock()
    opencode_work_dir = tmp_path / "work"
    context.bot_data = {
        "settings": MagicMock(
            telegram_user_id="12345",
            opencode_path="opencode",
            tensorx_api_key="sk-test",
            session_file=tmp_path / "session.json",
            uploads_dir=opencode_work_dir / "uploads",
            memory_enabled=memory_enabled,
            max_memories=max_memories,
            memory_file=tmp_path / "memory.json",
            allowed_tools=allowed_tools or [],
            opencode_work_dir=opencode_work_dir,
            opencode_config_file=tmp_path / "opencode.json",
            cron_enabled=cron_enabled,
            cron_file=tmp_path / "cron.json",
            backlog_enabled=backlog_enabled,
            backlog_file=tmp_path / "backlog.json",
            opencode_timeout=300,
            opencode_scheduled_timeout=600,
            opencode_model=opencode_model,
            opencode_auto_approve=False,
            opencode_context_limit=opencode_context_limit,
        ),
        "session": {"session_id": None, "last_activity": ""},
        "memory": [],
        "mcp_tool_names": [],
        "last_run": {},
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
        "pyclaudius.handlers.call_opencode", new_callable=AsyncMock
    ) as mock_opencode:
        mock_opencode.return_value = ("Hi there!", "session-abc")
        await handle_text(update, context)
        mock_opencode.assert_called_once()
        kwargs = mock_opencode.call_args.kwargs
        assert kwargs["bot_data"] is context.bot_data
        assert kwargs["user_message"] == "hello claude"
        update.message.reply_text.assert_called_once_with("Hi there!")
        assert context.bot_data["session"]["session_id"] == "session-abc"


@pytest.mark.asyncio
async def test_handle_text_forwards_model(tmp_path):
    update = _make_update(text="hello opencode")
    context = _make_context(tmp_path, opencode_model="tensorx/z-ai/glm-5")
    with patch(
        "pyclaudius.handlers.call_opencode", new_callable=AsyncMock
    ) as mock_opencode:
        mock_opencode.return_value = ("Hi there!", "session-abc")
        await handle_text(update, context)
        kwargs = mock_opencode.call_args.kwargs
        assert kwargs["model"] == "tensorx/z-ai/glm-5"
        assert "effort" not in kwargs


@pytest.mark.asyncio
async def test_handle_text_model_defaults_to_settings(tmp_path):
    update = _make_update(text="hello claude")
    context = _make_context(tmp_path)
    with patch(
        "pyclaudius.handlers.call_opencode", new_callable=AsyncMock
    ) as mock_opencode:
        mock_opencode.return_value = ("Hi there!", "session-abc")
        await handle_text(update, context)
        kwargs = mock_opencode.call_args.kwargs
        assert kwargs["model"] == "tensorx/moonshotai/kimi-k3"
        assert kwargs["opencode_path"] == "opencode"
        assert kwargs["api_key"] == "sk-test"
        assert kwargs["auto_approve"] is False


@pytest.mark.asyncio
async def test_handle_text_no_session_update(tmp_path):
    update = _make_update(text="test")
    context = _make_context(tmp_path)
    with patch(
        "pyclaudius.handlers.call_opencode", new_callable=AsyncMock
    ) as mock_opencode:
        mock_opencode.return_value = ("response", None)
        await handle_text(update, context)
        assert context.bot_data["session"]["session_id"] is None


@pytest.mark.asyncio
async def test_handle_photo_success(tmp_path):
    uploads = tmp_path / "work" / "uploads"
    uploads.mkdir(parents=True)

    update = _make_update()
    photo_mock = MagicMock()
    photo_mock.file_id = "photo123"
    update.message.photo = [MagicMock(), photo_mock]

    context = _make_context(tmp_path)
    file_mock = AsyncMock()
    context.bot.get_file.return_value = file_mock

    with patch(
        "pyclaudius.handlers.call_opencode", new_callable=AsyncMock
    ) as mock_opencode:
        mock_opencode.return_value = ("Nice photo!", None)
        await handle_photo(update, context)
        mock_opencode.assert_called_once()
        kwargs = mock_opencode.call_args.kwargs
        assert kwargs["bot_data"] is context.bot_data
        assert kwargs["user_message"] == "Analyze this image."
        # uploads_dir sits inside opencode_work_dir (the cwd), so no extra
        # directory has to be granted — the file is attached instead.
        assert "add_dirs" not in kwargs
        assert kwargs["cwd"] == str(context.bot_data["settings"].opencode_work_dir)
        assert len(kwargs["files"]) == 1
        assert str(uploads) in kwargs["files"][0]
        assert "[Image: uploads/image_1.jpg]" in kwargs["prompt"]
        update.message.reply_text.assert_called_once_with("Nice photo!")
        context.bot.get_file.assert_called_once_with("photo123")


@pytest.mark.asyncio
async def test_handle_document_success(tmp_path):
    uploads = tmp_path / "work" / "uploads"
    uploads.mkdir(parents=True)

    update = _make_update()
    update.message.document = MagicMock()
    update.message.document.file_id = "doc123"
    update.message.document.file_name = "test.pdf"

    context = _make_context(tmp_path)
    file_mock = AsyncMock()
    context.bot.get_file.return_value = file_mock

    with patch(
        "pyclaudius.handlers.call_opencode", new_callable=AsyncMock
    ) as mock_opencode:
        mock_opencode.return_value = ("Document analyzed!", None)
        await handle_document(update, context)
        mock_opencode.assert_called_once()
        kwargs = mock_opencode.call_args.kwargs
        assert kwargs["bot_data"] is context.bot_data
        assert kwargs["user_message"] == "Analyze: test.pdf"
        # uploads_dir sits inside opencode_work_dir (the cwd), so no extra
        # directory has to be granted — the file is attached instead.
        assert "add_dirs" not in kwargs
        assert kwargs["cwd"] == str(context.bot_data["settings"].opencode_work_dir)
        assert len(kwargs["files"]) == 1
        assert str(uploads) in kwargs["files"][0]
        assert "[File: uploads/1_test.pdf]" in kwargs["prompt"]
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
        "pyclaudius.handlers.call_opencode", new_callable=AsyncMock
    ) as mock_opencode:
        mock_opencode.return_value = ("Hi!", None)
        await handle_text(update, context)
        prompt_arg = mock_opencode.call_args.kwargs["prompt"]
        assert "## Memory" in prompt_arg
        assert "- user likes coffee" in prompt_arg


@pytest.mark.asyncio
async def test_handle_text_memory_not_injected_when_disabled(tmp_path):
    update = _make_update(text="hello")
    context = _make_context(tmp_path, memory_enabled=False)
    context.bot_data["memory"] = ["user likes coffee"]
    with patch(
        "pyclaudius.handlers.call_opencode", new_callable=AsyncMock
    ) as mock_opencode:
        mock_opencode.return_value = ("Hi!", None)
        await handle_text(update, context)
        prompt_arg = mock_opencode.call_args.kwargs["prompt"]
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
        "pyclaudius.handlers.call_opencode", new_callable=AsyncMock
    ) as mock_opencode:
        mock_opencode.return_value = ("Hi!", None)
        await handle_text(update, context)
        prompt_arg = mock_opencode.call_args.kwargs["prompt"]
        assert "1 scheduled task(s)" in prompt_arg


@pytest.mark.asyncio
async def test_handle_text_scheduled_silent_suppresses_reply(tmp_path):
    update = _make_update(text="check weather")
    update.update_id = 42
    context = _make_context(tmp_path, cron_enabled=True)
    context.bot_data["_scheduled_update_ids"] = {42}
    with patch(
        "pyclaudius.handlers.call_opencode", new_callable=AsyncMock
    ) as mock_opencode:
        mock_opencode.return_value = ("[SILENT]", None)
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
        "pyclaudius.handlers.call_opencode", new_callable=AsyncMock
    ) as mock_opencode:
        mock_opencode.return_value = ("It's sunny today!", None)
        await handle_text(update, context)
        update.message.reply_text.assert_called_once_with("It's sunny today!")
        assert 43 not in context.bot_data.get("_scheduled_update_ids", set())


@pytest.mark.asyncio
async def test_handle_text_scheduled_uses_scheduled_timeout(tmp_path):
    update = _make_update(text="check weather")
    update.update_id = 44
    context = _make_context(tmp_path, cron_enabled=True)
    context.bot_data["_scheduled_update_ids"] = {44}
    with patch(
        "pyclaudius.handlers.call_opencode", new_callable=AsyncMock
    ) as mock_opencode:
        mock_opencode.return_value = ("done", None)
        await handle_text(update, context)
        assert mock_opencode.call_args.kwargs["timeout"] == 600


@pytest.mark.asyncio
async def test_handle_text_unscheduled_uses_interactive_timeout(tmp_path):
    update = _make_update(text="hello")
    update.update_id = 45
    context = _make_context(tmp_path)
    with patch(
        "pyclaudius.handlers.call_opencode", new_callable=AsyncMock
    ) as mock_opencode:
        mock_opencode.return_value = ("hi", None)
        await handle_text(update, context)
        assert mock_opencode.call_args.kwargs["timeout"] == 300


@pytest.mark.asyncio
async def test_handle_text_suppresses_silent_response(tmp_path):
    update = _make_update(text="hello")
    context = _make_context(tmp_path)
    with patch(
        "pyclaudius.handlers.call_opencode", new_callable=AsyncMock
    ) as mock_opencode:
        mock_opencode.return_value = ("[SILENT]", "session-id")
        await handle_text(update, context)
        update.message.reply_text.assert_not_called()
        assert context.bot_data["session"]["session_id"] == "session-id"


@pytest.mark.asyncio
async def test_handle_text_suppresses_silent_case_insensitive(tmp_path):
    update = _make_update(text="hello")
    context = _make_context(tmp_path)
    with patch(
        "pyclaudius.handlers.call_opencode", new_callable=AsyncMock
    ) as mock_opencode:
        mock_opencode.return_value = ("  [silent]\n", "session-id")
        await handle_text(update, context)
        update.message.reply_text.assert_not_called()


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
async def test_handle_text_passes_config_file(tmp_path):
    """Tool permissions live in the generated config, not in argv."""
    update = _make_update(text="hello")
    context = _make_context(tmp_path, allowed_tools=["patch"])
    with patch(
        "pyclaudius.handlers.call_opencode", new_callable=AsyncMock
    ) as mock_opencode:
        mock_opencode.return_value = ("Hi!", None)
        await handle_text(update, context)
        kwargs = mock_opencode.call_args.kwargs
        assert kwargs["config_file"] == tmp_path / "opencode.json"
        assert "allowed_tools" not in kwargs


@pytest.mark.asyncio
async def test_handle_text_records_usage_for_context_command(tmp_path):
    update = _make_update(text="hello")
    context = _make_context(tmp_path)

    async def fake_call(**kwargs):
        kwargs["run_info"]["tokens"] = 1234
        kwargs["run_info"]["cost"] = 0.05
        return "Hi!", "ses_1"

    with patch("pyclaudius.handlers.call_opencode", side_effect=fake_call):
        await handle_text(update, context)
    assert context.bot_data["last_run"]["tokens"] == 1234
    assert context.bot_data["last_run"]["cost"] == 0.05


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
        "pyclaudius.handlers.call_opencode", new_callable=AsyncMock
    ) as mock_opencode:
        mock_opencode.return_value = ("Answer!", "sess-1")
        await handle_replaybacklog_command(update, context)
        assert mock_opencode.call_count == 2
        assert context.bot_data["backlog"] == []
        # Prompts should contain backlog prefix
        for call in mock_opencode.call_args_list:
            prompt_arg = call.kwargs["prompt"]
            assert "Backlog" in prompt_arg
            assert "originally sent at" in prompt_arg


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
        "pyclaudius.handlers.call_opencode", new_callable=AsyncMock
    ) as mock_opencode:
        mock_opencode.return_value = ("Answer!", "sess-1")
        await handle_replayone_command(update, context)
        mock_opencode.assert_called_once()
        kwargs = mock_opencode.call_args.kwargs
        assert kwargs["user_message"] == "hello world"
        assert context.bot_data["backlog"] == []
        # Prompt should contain backlog prefix
        assert "Backlog" in kwargs["prompt"]
        assert "originally sent at" in kwargs["prompt"]


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


@pytest.mark.asyncio
async def test_handle_text_empty_response(tmp_path):
    """Empty response from opencode triggers fallback message."""
    update = _make_update(text="hello")
    context = _make_context(tmp_path)
    with patch(
        "pyclaudius.handlers.call_opencode", new_callable=AsyncMock
    ) as mock_opencode:
        mock_opencode.return_value = ("", "session-abc")
        await handle_text(update, context)
        update.message.reply_text.assert_called_once_with(
            "(empty response from opencode)"
        )


@pytest.mark.asyncio
async def test_handle_clear_command_with_session(tmp_path):
    """/clear is purely local now: stop resuming, spawn nothing."""
    update = _make_update(text="/clear")
    context = _make_context(tmp_path)
    context.bot_data["session"]["session_id"] = "ses_old"
    context.bot_data["last_run"] = {"tokens": 10}
    with patch(
        "pyclaudius.handlers.call_opencode", new_callable=AsyncMock
    ) as mock_opencode:
        await handle_clear_command(update, context)
        mock_opencode.assert_not_called()
    assert context.bot_data["session"]["session_id"] is None
    assert context.bot_data["last_run"] == {}
    update.message.reply_text.assert_called_once_with("Session cleared.")


@pytest.mark.asyncio
async def test_handle_clear_command_persists_cleared_session(tmp_path):
    update = _make_update(text="/clear")
    context = _make_context(tmp_path)
    context.bot_data["session"]["session_id"] = "ses_old"
    with patch("pyclaudius.handlers.save_session") as mock_save:
        await handle_clear_command(update, context)
    assert mock_save.call_args.kwargs["session_id"] is None


@pytest.mark.asyncio
async def test_handle_clear_command_no_session(tmp_path):
    update = _make_update(text="/clear")
    context = _make_context(tmp_path)
    await handle_clear_command(update, context)
    assert context.bot_data["session"]["session_id"] is None
    update.message.reply_text.assert_called_once_with("Session cleared.")


@pytest.mark.asyncio
async def test_handle_clear_command_unauthorized(tmp_path):
    update = _make_update(user_id=99999, text="/clear")
    context = _make_context(tmp_path)
    await handle_clear_command(update, context)
    update.message.reply_text.assert_called_once_with("This bot is private.")


@pytest.mark.asyncio
async def test_handle_compact_command_success(tmp_path):
    """/compact drives the opencode server's summarize endpoint."""
    update = _make_update(text="/compact")
    context = _make_context(tmp_path)
    context.bot_data["session"]["session_id"] = "ses_mine"
    with patch(
        "pyclaudius.handlers.compact_session", new_callable=AsyncMock
    ) as mock_compact:
        mock_compact.return_value = "Context compacted."
        await handle_compact_command(update, context)
    assert mock_compact.call_args.kwargs["session_id"] == "ses_mine"
    # Compaction keeps the same session, so the stored id must survive.
    assert context.bot_data["session"]["session_id"] == "ses_mine"
    update.message.reply_text.assert_called_once_with("Context compacted.")


@pytest.mark.asyncio
async def test_handle_compact_command_relays_failure(tmp_path):
    update = _make_update(text="/compact")
    context = _make_context(tmp_path)
    context.bot_data["session"]["session_id"] = "ses_mine"
    with patch(
        "pyclaudius.handlers.compact_session", new_callable=AsyncMock
    ) as mock_compact:
        mock_compact.return_value = "Compaction failed — HTTP 500"
        await handle_compact_command(update, context)
    update.message.reply_text.assert_called_once_with("Compaction failed — HTTP 500")


@pytest.mark.asyncio
async def test_handle_compact_command_no_session(tmp_path):
    update = _make_update(text="/compact")
    context = _make_context(tmp_path)
    with patch(
        "pyclaudius.handlers.compact_session", new_callable=AsyncMock
    ) as mock_compact:
        await handle_compact_command(update, context)
        mock_compact.assert_not_called()
    update.message.reply_text.assert_called_once_with("No active session to compact.")


@pytest.mark.asyncio
async def test_handle_compact_command_unauthorized(tmp_path):
    update = _make_update(user_id=99999, text="/compact")
    context = _make_context(tmp_path)
    await handle_compact_command(update, context)
    update.message.reply_text.assert_called_once_with("This bot is private.")


# --- /context ---


@pytest.mark.asyncio
async def test_handle_context_command_success(tmp_path):
    """/context is answered from the last run's token usage, with no subprocess."""
    update = _make_update(text="/context")
    context = _make_context(tmp_path)
    context.bot_data["session"]["session_id"] = "ses_mine"
    context.bot_data["last_run"] = {"tokens": 104_857, "cost": 0.0175}
    with patch(
        "pyclaudius.handlers.call_opencode", new_callable=AsyncMock
    ) as mock_opencode:
        await handle_context_command(update, context)
        mock_opencode.assert_not_called()
    reply = update.message.reply_text.call_args[0][0]
    assert "104,857" in reply
    assert "1,048,576" in reply
    assert "10.0%" in reply
    assert "$0.0175" in reply


@pytest.mark.asyncio
async def test_handle_context_command_without_usage_yet(tmp_path):
    update = _make_update(text="/context")
    context = _make_context(tmp_path)
    context.bot_data["session"]["session_id"] = "ses_mine"
    await handle_context_command(update, context)
    reply = update.message.reply_text.call_args[0][0]
    assert "No usage recorded yet" in reply


@pytest.mark.asyncio
async def test_handle_context_command_no_session(tmp_path):
    """Context command without active session replies with error."""
    update = _make_update(text="/context")
    context = _make_context(tmp_path)
    await handle_context_command(update, context)
    update.message.reply_text.assert_called_once_with("No active session.")


@pytest.mark.asyncio
async def test_handle_context_command_unauthorized(tmp_path):
    update = _make_update(user_id=99999, text="/context")
    context = _make_context(tmp_path)
    await handle_context_command(update, context)
    update.message.reply_text.assert_called_once_with("This bot is private.")


@pytest.mark.asyncio
async def test_handle_text_resumes_the_stored_session(tmp_path):
    """Continuity is the whole point: every message must resume, not restart."""
    update = _make_update(text="hello")
    context = _make_context(tmp_path)
    context.bot_data["session"]["session_id"] = "ses_existing"
    with patch(
        "pyclaudius.handlers.call_opencode", new_callable=AsyncMock
    ) as mock_opencode:
        mock_opencode.return_value = ("Hi!", "ses_existing")
        await handle_text(update, context)
    kwargs = mock_opencode.call_args.kwargs
    assert kwargs["resume"] is True
    assert kwargs["session_id"] == "ses_existing"


@pytest.mark.asyncio
async def test_handle_photo_resumes_the_stored_session(tmp_path):
    """An image must join the conversation, not start a new one."""
    update = _make_update(text=None)
    update.message.photo = [MagicMock(file_id="f1")]
    update.message.caption = "what is this"
    context = _make_context(tmp_path)
    context.bot_data["session"]["session_id"] = "ses_existing"
    context.bot_data["settings"].uploads_dir.mkdir(parents=True, exist_ok=True)
    with patch(
        "pyclaudius.handlers.call_opencode", new_callable=AsyncMock
    ) as mock_opencode:
        mock_opencode.return_value = ("A cat.", "ses_existing")
        await handle_photo(update, context)
    kwargs = mock_opencode.call_args.kwargs
    assert kwargs["resume"] is True
    assert kwargs["session_id"] == "ses_existing"


@pytest.mark.asyncio
async def test_handle_text_attaches_nothing(tmp_path):
    """Plain text messages must not attach files."""
    update = _make_update(text="hello")
    context = _make_context(tmp_path)
    with patch(
        "pyclaudius.handlers.call_opencode", new_callable=AsyncMock
    ) as mock_opencode:
        mock_opencode.return_value = ("Hi!", None)
        await handle_text(update, context)
    assert mock_opencode.call_args.kwargs["files"] is None


@pytest.mark.asyncio
async def test_replaybacklog_stops_when_an_item_is_requeued(tmp_path):
    """Any failure category must stop the loop, not just auth errors."""
    update = _make_update(text="/replaybacklog")
    context = _make_context(tmp_path)
    context.bot_data["backlog"] = [
        {"prompt": "one", "created_at": "2026-01-01T00:00:00"},
        {"prompt": "two", "created_at": "2026-01-01T00:00:00"},
        {"prompt": "three", "created_at": "2026-01-01T00:00:00"},
    ]
    with patch(
        "pyclaudius.handlers.call_opencode", new_callable=AsyncMock
    ) as mock_opencode:
        mock_opencode.return_value = (
            "Provider rate limit reached. Message saved to backlog (1 pending).\nhint",
            None,
        )
        await handle_replaybacklog_command(update, context)
    assert mock_opencode.call_count == 1


# --- /context formatting ---


def test_format_context_usage_reports_share_of_the_window():
    text = format_context_usage(tokens=104_857, cost=0.0175, context_limit=1_048_576)
    assert "104,857" in text
    assert "1,048,576" in text
    assert "10.0%" in text
    assert "$0.0175" in text


def test_format_context_usage_without_cost():
    text = format_context_usage(tokens=1000, cost=None, context_limit=1_048_576)
    assert "cost" not in text.lower()
    assert "1,000" in text


def test_format_context_usage_without_usage():
    assert "No usage recorded yet" in format_context_usage(
        tokens=None, cost=None, context_limit=1_048_576
    )


def test_format_context_usage_survives_a_zero_limit():
    """A misconfigured limit must not raise ZeroDivisionError in a handler."""
    text = format_context_usage(tokens=10, cost=None, context_limit=0)
    assert "0.0%" in text
