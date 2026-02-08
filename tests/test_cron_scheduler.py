from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from pyclaudius.cron.scheduler import (
    create_scheduler,
    execute_scheduled_job,
    parse_schedule_datetime,
    register_job,
    unregister_job,
    validate_cron_expression,
)


def test_create_scheduler():
    scheduler = create_scheduler()
    assert scheduler is not None


def test_validate_cron_expression_valid():
    assert validate_cron_expression(expression="*/5 * * * *") is True
    assert validate_cron_expression(expression="0 9 * * 1-5") is True
    assert validate_cron_expression(expression="0 0 1 * *") is True


def test_validate_cron_expression_invalid():
    assert validate_cron_expression(expression="not a cron") is False
    assert validate_cron_expression(expression="") is False
    assert validate_cron_expression(expression="* * *") is False


def test_parse_schedule_datetime_ymd_hm():
    result = parse_schedule_datetime(text="2026-02-10 14:30")
    assert result == datetime(2026, 2, 10, 14, 30, tzinfo=UTC)


def test_parse_schedule_datetime_iso_with_seconds():
    result = parse_schedule_datetime(text="2026-02-10T14:30:00")
    assert result == datetime(2026, 2, 10, 14, 30, tzinfo=UTC)


def test_parse_schedule_datetime_iso_without_seconds():
    result = parse_schedule_datetime(text="2026-02-10T14:30")
    assert result == datetime(2026, 2, 10, 14, 30, tzinfo=UTC)


def test_parse_schedule_datetime_ymd_hms():
    result = parse_schedule_datetime(text="2026-02-10 14:30:00")
    assert result == datetime(2026, 2, 10, 14, 30, tzinfo=UTC)


def test_parse_schedule_datetime_invalid():
    assert parse_schedule_datetime(text="not a date") is None
    assert parse_schedule_datetime(text="") is None
    assert parse_schedule_datetime(text="2026-13-40 99:99") is None


def test_parse_schedule_datetime_strips_whitespace():
    result = parse_schedule_datetime(text="  2026-02-10 14:30  ")
    assert result is not None


def test_register_job_cron():
    scheduler = MagicMock()
    job = {
        "id": "abc",
        "job_type": "cron",
        "expression": "*/5 * * * *",
        "prompt": "test",
        "created_at": "2026-01-01T00:00:00",
    }
    register_job(
        scheduler=scheduler,
        job=job,
        callback=MagicMock(),
        callback_kwargs={"chat_id": "123"},
    )
    scheduler.add_job.assert_called_once()
    call_kwargs = scheduler.add_job.call_args
    assert call_kwargs.kwargs["id"] == "abc"


def test_register_job_once():
    scheduler = MagicMock()
    job = {
        "id": "xyz",
        "job_type": "once",
        "expression": "2026-02-10 14:30",
        "prompt": "reminder",
        "created_at": "2026-01-01T00:00:00",
    }
    register_job(
        scheduler=scheduler,
        job=job,
        callback=MagicMock(),
        callback_kwargs={"chat_id": "123"},
    )
    scheduler.add_job.assert_called_once()


def test_register_job_invalid_datetime():
    scheduler = MagicMock()
    job = {
        "id": "bad",
        "job_type": "once",
        "expression": "not a date",
        "prompt": "test",
        "created_at": "2026-01-01T00:00:00",
    }
    register_job(
        scheduler=scheduler,
        job=job,
        callback=MagicMock(),
        callback_kwargs={"chat_id": "123"},
    )
    scheduler.add_job.assert_not_called()


def test_unregister_job_exists():
    scheduler = MagicMock()
    unregister_job(scheduler=scheduler, job_id="abc")
    scheduler.remove_job.assert_called_once_with("abc")


def test_unregister_job_not_found():
    scheduler = MagicMock()
    scheduler.remove_job.side_effect = Exception("not found")
    unregister_job(scheduler=scheduler, job_id="missing")
    scheduler.remove_job.assert_called_once_with("missing")


@pytest.mark.asyncio
async def test_execute_scheduled_job_stores_update_id():
    application = MagicMock()
    application.bot_data = {
        "cron_jobs": [],
        "settings": MagicMock(cron_file="cron.json"),
    }
    application.bot = MagicMock()
    application.process_update = AsyncMock()

    await execute_scheduled_job(
        application=application,
        chat_id="12345",
        prompt_text="test prompt",
        job_id="job1",
        job_type="cron",
    )

    assert "_scheduled_update_ids" in application.bot_data
    # After process_update the ID should still be in the set
    # (it's only removed by handle_text)
    scheduled_ids = application.bot_data["_scheduled_update_ids"]
    assert len(scheduled_ids) == 1


@pytest.mark.asyncio
async def test_execute_scheduled_job_is_test_does_not_remove_once_job():
    job_data = {
        "id": "once-job-1",
        "job_type": "once",
        "expression": "2026-03-01 10:00",
        "prompt": "reminder",
        "created_at": "2026-01-01T00:00:00",
    }
    application = MagicMock()
    application.bot_data = {
        "cron_jobs": [job_data],
        "settings": MagicMock(cron_file="cron.json"),
    }
    application.bot = MagicMock()
    application.process_update = AsyncMock()

    await execute_scheduled_job(
        application=application,
        chat_id="12345",
        prompt_text="reminder",
        job_id="once-job-1",
        job_type="once",
        is_test=True,
    )

    # Job should still be in the list (not removed because is_test=True)
    assert len(application.bot_data["cron_jobs"]) == 1
    assert application.bot_data["cron_jobs"][0]["id"] == "once-job-1"


@pytest.mark.asyncio
async def test_execute_scheduled_job_sets_bot_on_chat():
    application = MagicMock()
    application.bot_data = {
        "cron_jobs": [],
        "settings": MagicMock(cron_file="cron.json"),
    }
    application.bot = MagicMock()
    application.process_update = AsyncMock()

    await execute_scheduled_job(
        application=application,
        chat_id="12345",
        prompt_text="test prompt",
        job_id="job1",
        job_type="cron",
    )

    # Verify the synthetic Chat object had set_bot called with the application bot
    update_arg = application.process_update.call_args[0][0]
    assert update_arg.message.chat._bot is application.bot  # noqa: SLF001
