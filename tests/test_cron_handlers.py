from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from pyclaudius.cron.handlers import (
    handle_addcron_command,
    handle_listcron_command,
    handle_removecron_command,
    handle_schedule_command,
    handle_testcron_command,
    process_cron_response,
)


def _make_context(tmp_path, *, cron_enabled=True):
    context = MagicMock()
    context.bot_data = {
        "settings": MagicMock(
            telegram_user_id="12345",
            cron_enabled=cron_enabled,
            cron_file=tmp_path / "cron.json",
            telegram_user_id_str="12345",
        ),
        "cron_jobs": [],
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


# --- handle_addcron_command ---


@pytest.mark.asyncio
async def test_addcron_unauthorized(tmp_path):
    update = _make_update(user_id=99999, text="/addcron */5 * * * * test")
    context = _make_context(tmp_path)
    await handle_addcron_command(update, context)
    update.message.reply_text.assert_called_once_with("This bot is private.")


@pytest.mark.asyncio
async def test_addcron_disabled(tmp_path):
    update = _make_update(text="/addcron */5 * * * * test")
    context = _make_context(tmp_path, cron_enabled=False)
    await handle_addcron_command(update, context)
    update.message.reply_text.assert_called_once_with("Cron scheduling is disabled.")


@pytest.mark.asyncio
async def test_addcron_missing_args(tmp_path):
    update = _make_update(text="/addcron */5 * *")
    context = _make_context(tmp_path)
    await handle_addcron_command(update, context)
    reply = update.message.reply_text.call_args[0][0]
    assert "Usage" in reply


@pytest.mark.asyncio
async def test_addcron_invalid_expression(tmp_path):
    update = _make_update(text="/addcron bad bad bad bad bad test")
    context = _make_context(tmp_path)
    await handle_addcron_command(update, context)
    reply = update.message.reply_text.call_args[0][0]
    assert "Invalid cron expression" in reply


@pytest.mark.asyncio
async def test_addcron_success(tmp_path):
    update = _make_update(text="/addcron */5 * * * * check weather")
    context = _make_context(tmp_path)
    await handle_addcron_command(update, context)
    reply = update.message.reply_text.call_args[0][0]
    assert "Cron job added" in reply
    assert "*/5 * * * *" in reply
    assert "check weather" in reply
    assert len(context.bot_data["cron_jobs"]) == 1
    context.bot_data["scheduler"].add_job.assert_called_once()


# --- handle_schedule_command ---


@pytest.mark.asyncio
async def test_schedule_unauthorized(tmp_path):
    update = _make_update(user_id=99999, text="/schedule 2026-02-10 14:30 | test")
    context = _make_context(tmp_path)
    await handle_schedule_command(update, context)
    update.message.reply_text.assert_called_once_with("This bot is private.")


@pytest.mark.asyncio
async def test_schedule_disabled(tmp_path):
    update = _make_update(text="/schedule 2026-02-10 14:30 | test")
    context = _make_context(tmp_path, cron_enabled=False)
    await handle_schedule_command(update, context)
    update.message.reply_text.assert_called_once_with("Cron scheduling is disabled.")


@pytest.mark.asyncio
async def test_schedule_no_pipe(tmp_path):
    update = _make_update(text="/schedule 2026-02-10 14:30 test")
    context = _make_context(tmp_path)
    await handle_schedule_command(update, context)
    reply = update.message.reply_text.call_args[0][0]
    assert "Usage" in reply


@pytest.mark.asyncio
async def test_schedule_invalid_datetime(tmp_path):
    update = _make_update(text="/schedule not-a-date | test")
    context = _make_context(tmp_path)
    await handle_schedule_command(update, context)
    reply = update.message.reply_text.call_args[0][0]
    assert "Invalid datetime" in reply


@pytest.mark.asyncio
async def test_schedule_past_datetime(tmp_path):
    update = _make_update(text="/schedule 2020-01-01 00:00 | test")
    context = _make_context(tmp_path)
    await handle_schedule_command(update, context)
    update.message.reply_text.assert_called_once_with("Datetime must be in the future.")


@pytest.mark.asyncio
async def test_schedule_success(tmp_path):
    update = _make_update(text="/schedule 2030-12-31 23:59 | new year reminder")
    context = _make_context(tmp_path)
    await handle_schedule_command(update, context)
    reply = update.message.reply_text.call_args[0][0]
    assert "Scheduled one-time task" in reply
    assert "new year reminder" in reply
    assert len(context.bot_data["cron_jobs"]) == 1
    assert context.bot_data["cron_jobs"][0]["job_type"] == "once"


# --- handle_removecron_command ---


@pytest.mark.asyncio
async def test_removecron_unauthorized(tmp_path):
    update = _make_update(user_id=99999, text="/removecron 1")
    context = _make_context(tmp_path)
    await handle_removecron_command(update, context)
    update.message.reply_text.assert_called_once_with("This bot is private.")


@pytest.mark.asyncio
async def test_removecron_disabled(tmp_path):
    update = _make_update(text="/removecron 1")
    context = _make_context(tmp_path, cron_enabled=False)
    await handle_removecron_command(update, context)
    update.message.reply_text.assert_called_once_with("Cron scheduling is disabled.")


@pytest.mark.asyncio
async def test_removecron_not_a_number(tmp_path):
    update = _make_update(text="/removecron abc")
    context = _make_context(tmp_path)
    await handle_removecron_command(update, context)
    update.message.reply_text.assert_called_once_with("Usage: /removecron <number>")


@pytest.mark.asyncio
async def test_removecron_out_of_range(tmp_path):
    update = _make_update(text="/removecron 5")
    context = _make_context(tmp_path)
    context.bot_data["cron_jobs"] = [
        {
            "id": "a",
            "job_type": "cron",
            "expression": "*/5 * * * *",
            "prompt": "test",
            "created_at": "2026-01-01T00:00:00",
        }
    ]
    await handle_removecron_command(update, context)
    reply = update.message.reply_text.call_args[0][0]
    assert "Invalid index 5" in reply


@pytest.mark.asyncio
async def test_removecron_success(tmp_path):
    update = _make_update(text="/removecron 1")
    context = _make_context(tmp_path)
    context.bot_data["cron_jobs"] = [
        {
            "id": "abc",
            "job_type": "cron",
            "expression": "*/5 * * * *",
            "prompt": "check weather",
            "created_at": "2026-01-01T00:00:00",
        }
    ]
    await handle_removecron_command(update, context)
    reply = update.message.reply_text.call_args[0][0]
    assert "Removed job 1" in reply
    assert "check weather" in reply
    assert len(context.bot_data["cron_jobs"]) == 0
    context.bot_data["scheduler"].remove_job.assert_called_once_with("abc")


# --- handle_listcron_command ---


@pytest.mark.asyncio
async def test_listcron_unauthorized(tmp_path):
    update = _make_update(user_id=99999)
    context = _make_context(tmp_path)
    await handle_listcron_command(update, context)
    update.message.reply_text.assert_called_once_with("This bot is private.")


@pytest.mark.asyncio
async def test_listcron_disabled(tmp_path):
    update = _make_update()
    context = _make_context(tmp_path, cron_enabled=False)
    await handle_listcron_command(update, context)
    update.message.reply_text.assert_called_once_with("Cron scheduling is disabled.")


@pytest.mark.asyncio
async def test_listcron_empty(tmp_path):
    update = _make_update()
    context = _make_context(tmp_path)
    await handle_listcron_command(update, context)
    update.message.reply_text.assert_called_once_with("No scheduled jobs.")


@pytest.mark.asyncio
async def test_listcron_with_jobs(tmp_path):
    update = _make_update()
    context = _make_context(tmp_path)
    context.bot_data["cron_jobs"] = [
        {
            "id": "a",
            "job_type": "cron",
            "expression": "*/5 * * * *",
            "prompt": "check weather",
            "created_at": "2026-01-01T00:00:00",
        },
        {
            "id": "b",
            "job_type": "once",
            "expression": "2026-03-01T10:00:00",
            "prompt": "reminder",
            "created_at": "2026-01-02T00:00:00",
        },
    ]
    await handle_listcron_command(update, context)
    reply = update.message.reply_text.call_args[0][0]
    assert "[CRON]" in reply
    assert "[ONCE]" in reply


# --- process_cron_response ---


def test_process_cron_response_disabled(tmp_path):
    context = _make_context(tmp_path, cron_enabled=False)
    result = process_cron_response(
        response="test [CRON_ADD: */5 * * * * | check]",
        settings=context.bot_data["settings"],
        context=context,
    )
    assert result == "test [CRON_ADD: */5 * * * * | check]"


def test_process_cron_response_cron_add(tmp_path):
    context = _make_context(tmp_path)
    result = process_cron_response(
        response="Done [CRON_ADD: */5 * * * * | check weather]",
        settings=context.bot_data["settings"],
        context=context,
    )
    assert "[CRON_ADD" not in result
    assert "Done" in result
    assert len(context.bot_data["cron_jobs"]) == 1
    assert context.bot_data["cron_jobs"][0]["job_type"] == "cron"


def test_process_cron_response_schedule(tmp_path):
    context = _make_context(tmp_path)
    result = process_cron_response(
        response="OK [SCHEDULE: 2030-12-31 23:59 | new year]",
        settings=context.bot_data["settings"],
        context=context,
    )
    assert "[SCHEDULE" not in result
    assert len(context.bot_data["cron_jobs"]) == 1
    assert context.bot_data["cron_jobs"][0]["job_type"] == "once"


def test_process_cron_response_cron_remove(tmp_path):
    context = _make_context(tmp_path)
    context.bot_data["cron_jobs"] = [
        {
            "id": "abc",
            "job_type": "cron",
            "expression": "*/5 * * * *",
            "prompt": "test",
            "created_at": "2026-01-01T00:00:00",
        }
    ]
    result = process_cron_response(
        response="Removed [CRON_REMOVE: 1]",
        settings=context.bot_data["settings"],
        context=context,
    )
    assert "[CRON_REMOVE" not in result
    assert len(context.bot_data["cron_jobs"]) == 0
    context.bot_data["scheduler"].remove_job.assert_called_once_with("abc")


def test_process_cron_response_cron_list(tmp_path):
    context = _make_context(tmp_path)
    context.bot_data["cron_jobs"] = [
        {
            "id": "a",
            "job_type": "cron",
            "expression": "*/5 * * * *",
            "prompt": "check weather",
            "created_at": "2026-01-01T00:00:00",
        }
    ]
    result = process_cron_response(
        response="Here are your jobs [CRON_LIST]",
        settings=context.bot_data["settings"],
        context=context,
    )
    assert "[CRON_LIST]" not in result
    assert "[CRON]" in result
    assert "check weather" in result


def test_process_cron_response_strips_all_tags(tmp_path):
    context = _make_context(tmp_path)
    result = process_cron_response(
        response="Hello [CRON_ADD: */5 * * * * | test] [CRON_LIST] bye",
        settings=context.bot_data["settings"],
        context=context,
    )
    assert "[CRON_ADD" not in result
    assert "[CRON_LIST]" not in result
    assert "Hello" in result
    assert "bye" in result


def test_process_cron_response_invalid_cron_add_ignored(tmp_path):
    context = _make_context(tmp_path)
    process_cron_response(
        response="Done [CRON_ADD: bad expression | test]",
        settings=context.bot_data["settings"],
        context=context,
    )
    assert len(context.bot_data["cron_jobs"]) == 0


def test_process_cron_response_past_schedule_ignored(tmp_path):
    context = _make_context(tmp_path)
    process_cron_response(
        response="Done [SCHEDULE: 2020-01-01 00:00 | old task]",
        settings=context.bot_data["settings"],
        context=context,
    )
    assert len(context.bot_data["cron_jobs"]) == 0


# --- handle_testcron_command ---


@pytest.mark.asyncio
async def test_testcron_unauthorized(tmp_path):
    update = _make_update(user_id=99999, text="/testcron 1")
    context = _make_context(tmp_path)
    await handle_testcron_command(update, context)
    update.message.reply_text.assert_called_once_with("This bot is private.")


@pytest.mark.asyncio
async def test_testcron_disabled(tmp_path):
    update = _make_update(text="/testcron 1")
    context = _make_context(tmp_path, cron_enabled=False)
    await handle_testcron_command(update, context)
    update.message.reply_text.assert_called_once_with("Cron scheduling is disabled.")


@pytest.mark.asyncio
async def test_testcron_invalid_index(tmp_path):
    update = _make_update(text="/testcron 5")
    context = _make_context(tmp_path)
    context.bot_data["cron_jobs"] = [
        {
            "id": "a",
            "job_type": "cron",
            "expression": "*/5 * * * *",
            "prompt": "test",
            "created_at": "2026-01-01T00:00:00",
        }
    ]
    await handle_testcron_command(update, context)
    reply = update.message.reply_text.call_args[0][0]
    assert "Invalid index 5" in reply


@pytest.mark.asyncio
async def test_testcron_success(tmp_path):
    update = _make_update(text="/testcron 1")
    context = _make_context(tmp_path)
    context.bot_data["cron_jobs"] = [
        {
            "id": "abc",
            "job_type": "cron",
            "expression": "*/5 * * * *",
            "prompt": "check weather",
            "created_at": "2026-01-01T00:00:00",
        }
    ]

    with patch(
        "pyclaudius.cron.handlers.execute_scheduled_job", new_callable=AsyncMock
    ) as mock_execute:
        await handle_testcron_command(update, context)

    # First call is the confirmation message, second would be from execute
    first_reply = update.message.reply_text.call_args_list[0][0][0]
    assert "Testing job 1" in first_reply
    assert "*/5 * * * *" in first_reply
    assert "check weather" in first_reply

    mock_execute.assert_called_once_with(
        application=context.bot_data["application"],
        chat_id="12345",
        prompt_text="check weather",
        job_id="abc",
        job_type="cron",
        is_test=True,
    )
