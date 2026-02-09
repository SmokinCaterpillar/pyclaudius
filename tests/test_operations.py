from unittest.mock import MagicMock

import pytest

from pyclaudius.operations import (
    add_cron_job,
    forget_memory,
    list_cron_jobs,
    list_memories,
    remember_fact,
    remove_cron_job,
    schedule_once,
)


def _make_bot_data(
    tmp_path,
    *,
    cron_enabled=True,
    memory_enabled=True,
    max_memories=100,
    user_timezone=None,
):
    return {
        "settings": MagicMock(
            telegram_user_id="12345",
            cron_enabled=cron_enabled,
            memory_enabled=memory_enabled,
            max_memories=max_memories,
            cron_file=tmp_path / "cron.json",
            memory_file=tmp_path / "memory.json",
        ),
        "cron_jobs": [],
        "memory": [],
        "scheduler": MagicMock(),
        "application": MagicMock(),
        "user_timezone": user_timezone,
    }


# --- add_cron_job ---


def test_add_cron_job_success(tmp_path):
    bot_data = _make_bot_data(tmp_path)
    result = add_cron_job(
        expression="*/5 * * * *", prompt_text="check weather", bot_data=bot_data
    )
    assert "Cron job added" in result
    assert "*/5 * * * *" in result
    assert "check weather" in result
    assert len(bot_data["cron_jobs"]) == 1
    assert bot_data["cron_jobs"][0]["job_type"] == "cron"
    bot_data["scheduler"].add_job.assert_called_once()


def test_add_cron_job_invalid_expression(tmp_path):
    bot_data = _make_bot_data(tmp_path)
    with pytest.raises(ValueError, match="Invalid cron expression"):
        add_cron_job(
            expression="bad bad bad bad bad",
            prompt_text="test",
            bot_data=bot_data,
        )


def test_add_cron_job_stores_timezone(tmp_path):
    bot_data = _make_bot_data(tmp_path, user_timezone="Europe/Berlin")
    add_cron_job(expression="*/5 * * * *", prompt_text="test", bot_data=bot_data)
    assert bot_data["cron_jobs"][0]["timezone"] == "Europe/Berlin"


def test_add_cron_job_no_timezone_when_none(tmp_path):
    bot_data = _make_bot_data(tmp_path, user_timezone=None)
    add_cron_job(expression="*/5 * * * *", prompt_text="test", bot_data=bot_data)
    assert "timezone" not in bot_data["cron_jobs"][0]


# --- schedule_once ---


def test_schedule_once_success(tmp_path):
    bot_data = _make_bot_data(tmp_path)
    result = schedule_once(
        datetime_str="2030-12-31 23:59",
        prompt_text="new year reminder",
        bot_data=bot_data,
    )
    assert "Scheduled one-time task" in result
    assert "new year reminder" in result
    assert len(bot_data["cron_jobs"]) == 1
    assert bot_data["cron_jobs"][0]["job_type"] == "once"


def test_schedule_once_invalid_datetime(tmp_path):
    bot_data = _make_bot_data(tmp_path)
    with pytest.raises(ValueError, match="Invalid datetime"):
        schedule_once(
            datetime_str="not-a-date",
            prompt_text="test",
            bot_data=bot_data,
        )


def test_schedule_once_past_datetime(tmp_path):
    bot_data = _make_bot_data(tmp_path)
    with pytest.raises(ValueError, match="future"):
        schedule_once(
            datetime_str="2020-01-01 00:00",
            prompt_text="test",
            bot_data=bot_data,
        )


def test_schedule_once_stores_timezone(tmp_path):
    bot_data = _make_bot_data(tmp_path, user_timezone="Asia/Tokyo")
    schedule_once(
        datetime_str="2030-12-31 23:59",
        prompt_text="test",
        bot_data=bot_data,
    )
    assert bot_data["cron_jobs"][0]["timezone"] == "Asia/Tokyo"


# --- remove_cron_job ---


def test_remove_cron_job_success(tmp_path):
    bot_data = _make_bot_data(tmp_path)
    bot_data["cron_jobs"] = [
        {
            "id": "abc",
            "job_type": "cron",
            "expression": "*/5 * * * *",
            "prompt": "check weather",
            "created_at": "2026-01-01T00:00:00",
        }
    ]
    result = remove_cron_job(index=1, bot_data=bot_data)
    assert "Removed job 1" in result
    assert "check weather" in result
    assert len(bot_data["cron_jobs"]) == 0
    bot_data["scheduler"].remove_job.assert_called_once_with("abc")


def test_remove_cron_job_invalid_index(tmp_path):
    bot_data = _make_bot_data(tmp_path)
    bot_data["cron_jobs"] = [
        {
            "id": "a",
            "job_type": "cron",
            "expression": "*/5 * * * *",
            "prompt": "test",
            "created_at": "2026-01-01T00:00:00",
        }
    ]
    with pytest.raises(ValueError, match="Invalid index 5"):
        remove_cron_job(index=5, bot_data=bot_data)


def test_remove_cron_job_index_zero(tmp_path):
    bot_data = _make_bot_data(tmp_path)
    bot_data["cron_jobs"] = [
        {
            "id": "a",
            "job_type": "cron",
            "expression": "*/5 * * * *",
            "prompt": "test",
            "created_at": "2026-01-01T00:00:00",
        }
    ]
    with pytest.raises(ValueError, match="Invalid index 0"):
        remove_cron_job(index=0, bot_data=bot_data)


# --- list_cron_jobs ---


def test_list_cron_jobs_empty(tmp_path):
    bot_data = _make_bot_data(tmp_path)
    result = list_cron_jobs(bot_data=bot_data)
    assert result == "No scheduled jobs."


def test_list_cron_jobs_with_jobs(tmp_path):
    bot_data = _make_bot_data(tmp_path)
    bot_data["cron_jobs"] = [
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
            "expression": "2026-06-01 10:00",
            "prompt": "reminder",
            "created_at": "2026-01-02T00:00:00",
        },
    ]
    result = list_cron_jobs(bot_data=bot_data)
    assert "[CRON]" in result
    assert "[ONCE]" in result
    assert "check weather" in result
    assert "reminder" in result


# --- remember_fact ---


def test_remember_fact_success(tmp_path):
    bot_data = _make_bot_data(tmp_path)
    result = remember_fact(fact="user likes coffee", bot_data=bot_data)
    assert 'Remembered: "user likes coffee"' in result
    assert "user likes coffee" in bot_data["memory"]


def test_remember_fact_dedup(tmp_path):
    bot_data = _make_bot_data(tmp_path)
    bot_data["memory"] = ["user likes coffee"]
    result = remember_fact(fact="user likes coffee", bot_data=bot_data)
    assert "Remembered" in result
    assert len(bot_data["memory"]) == 1


def test_remember_fact_overflow_warning(tmp_path):
    bot_data = _make_bot_data(tmp_path, max_memories=2)
    bot_data["memory"] = ["likes coffee", "likes tea"]
    result = remember_fact(fact="likes water", bot_data=bot_data)
    assert 'Remembered: "likes water"' in result
    assert "Warning: memory full (2)" in result
    assert 'Oldest fact forgotten: "likes coffee"' in result


def test_remember_fact_no_warning_under_max(tmp_path):
    bot_data = _make_bot_data(tmp_path, max_memories=10)
    bot_data["memory"] = ["likes coffee"]
    result = remember_fact(fact="likes water", bot_data=bot_data)
    assert "Remembered" in result
    assert "Warning" not in result


# --- forget_memory ---


def test_forget_memory_by_keyword(tmp_path):
    bot_data = _make_bot_data(tmp_path)
    bot_data["memory"] = ["likes coffee", "likes tea"]
    result = forget_memory(keyword="coffee", bot_data=bot_data)
    assert "Removed 1" in result
    assert bot_data["memory"] == ["likes tea"]


def test_forget_memory_no_match(tmp_path):
    bot_data = _make_bot_data(tmp_path)
    bot_data["memory"] = ["likes coffee"]
    result = forget_memory(keyword="python", bot_data=bot_data)
    assert "No memories matching" in result


def test_forget_memory_by_index(tmp_path):
    bot_data = _make_bot_data(tmp_path)
    bot_data["memory"] = ["likes coffee", "likes tea", "likes water"]
    result = forget_memory(keyword="2", bot_data=bot_data)
    assert result == 'Removed memory 2: "likes tea"'
    assert bot_data["memory"] == ["likes coffee", "likes water"]


def test_forget_memory_invalid_index(tmp_path):
    bot_data = _make_bot_data(tmp_path)
    bot_data["memory"] = ["likes coffee"]
    with pytest.raises(ValueError, match="Invalid index 5"):
        forget_memory(keyword="5", bot_data=bot_data)


def test_forget_memory_index_zero(tmp_path):
    bot_data = _make_bot_data(tmp_path)
    bot_data["memory"] = ["likes coffee"]
    with pytest.raises(ValueError, match="Invalid index 0"):
        forget_memory(keyword="0", bot_data=bot_data)


# --- list_memories ---


def test_list_memories_empty(tmp_path):
    bot_data = _make_bot_data(tmp_path)
    result = list_memories(bot_data=bot_data)
    assert result == "No memories stored."


def test_list_memories_with_facts(tmp_path):
    bot_data = _make_bot_data(tmp_path)
    bot_data["memory"] = ["likes coffee", "likes tea"]
    result = list_memories(bot_data=bot_data)
    assert "likes coffee" in result
    assert "likes tea" in result
    assert "2" in result
