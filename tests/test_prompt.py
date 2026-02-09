from pyclaudius.prompt import build_prompt


def test_build_prompt_contains_user_message():
    result = build_prompt(user_message="hello world")
    assert "User: hello world" in result


def test_build_prompt_contains_instruction():
    result = build_prompt(user_message="test")
    assert "You are responding via Telegram" in result
    assert "Keep responses concise" in result


def test_build_prompt_contains_time():
    result = build_prompt(user_message="test")
    assert "Current time:" in result


def test_build_prompt_with_cron_count():
    result = build_prompt(user_message="test", cron_count=3)
    assert "3 scheduled task(s)" in result
    assert "CRON_ADD" in result
    assert "SCHEDULE" in result
    assert "CRON_REMOVE" in result
    assert "CRON_LIST" in result


def test_build_prompt_without_cron_count():
    result = build_prompt(user_message="test")
    assert "scheduled task" not in result
    assert "CRON_ADD" not in result


def test_build_prompt_is_scheduled_includes_silent_instruction():
    result = build_prompt(user_message="test", cron_count=1, is_scheduled=True)
    assert "[SILENT]" in result
    assert "automated scheduled task" in result


def test_build_prompt_not_scheduled_no_silent_instruction():
    result = build_prompt(user_message="test", cron_count=1, is_scheduled=False)
    assert "[SILENT]" not in result
    assert "automated scheduled task" not in result


def test_build_prompt_with_timezone():
    result = build_prompt(user_message="test", timezone="Europe/Berlin")
    assert "(Europe/Berlin)" in result


def test_build_prompt_with_timezone_none():
    result = build_prompt(user_message="test", timezone=None)
    assert "(UTC)" in result
