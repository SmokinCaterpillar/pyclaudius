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
