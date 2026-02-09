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
    assert "Current time of your user:" in result


def test_build_prompt_with_cron_count():
    result = build_prompt(user_message="test", cron_count=3)
    assert "3 scheduled task(s)" in result
    assert "cron tools" in result


def test_build_prompt_without_cron_count():
    result = build_prompt(user_message="test")
    assert "scheduled task" not in result
    assert "cron tools" not in result


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


def test_build_prompt_with_memory_section_includes_hint():
    result = build_prompt(user_message="test", memory_section="## Memory\n- fact\n\n")
    assert "remember_fact" in result
    assert "forget_memory" in result
    assert "## Memory" in result


def test_build_prompt_without_memory_section_no_hint():
    result = build_prompt(user_message="test", memory_section=None)
    assert "remember_fact" not in result
    assert "forget_memory" not in result
