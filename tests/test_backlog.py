import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from pyclaudius.backlog import (
    BacklogItem,
    format_backlog_list,
    load_backlog,
    save_backlog,
    with_backlog,
)
from pyclaudius.opencode_events import OpencodeResult


def _result(
    *,
    error_name: str | None = None,
    status_code: int | None = None,
    is_retryable: bool | None = None,
    text: str = "",
) -> OpencodeResult:
    return OpencodeResult(
        text=text,
        session_id="ses_x",
        error_name=error_name,
        error_message="detail",
        status_code=status_code,
        is_retryable=is_retryable,
        finished=True,
        tokens=None,
        cost=None,
    )


def _bot_data(*, backlog_file, backlog=None) -> dict:
    return {
        "settings": MagicMock(backlog_enabled=True, backlog_file=backlog_file),
        "backlog": [] if backlog is None else list(backlog),
    }


AUTH_401 = _result(error_name="APIError", status_code=401, is_retryable=False)
RATE_429 = _result(error_name="APIError", status_code=429, is_retryable=False)
SERVER_500 = _result(error_name="APIError", status_code=500, is_retryable=True)


def test_load_backlog_empty(tmp_path):
    backlog_file = tmp_path / "backlog.json"
    backlog_file.write_text("[]")
    result = load_backlog(backlog_file=backlog_file)
    assert result == []


def test_load_backlog_missing_file(tmp_path):
    backlog_file = tmp_path / "backlog.json"
    result = load_backlog(backlog_file=backlog_file)
    assert result == []


def test_save_and_load_backlog(tmp_path):
    backlog_file = tmp_path / "backlog.json"
    items: list[BacklogItem] = [
        {"prompt": "hello", "created_at": "2026-01-01T00:00:00"},
        {"prompt": "world", "created_at": "2026-01-02T00:00:00"},
    ]
    save_backlog(backlog_file=backlog_file, items=items)
    loaded = load_backlog(backlog_file=backlog_file)
    assert loaded == items


def test_load_backlog_invalid_json(tmp_path):
    backlog_file = tmp_path / "backlog.json"
    backlog_file.write_text("not json")
    result = load_backlog(backlog_file=backlog_file)
    assert result == []


def test_load_backlog_not_a_list(tmp_path):
    backlog_file = tmp_path / "backlog.json"
    backlog_file.write_text('{"key": "value"}')
    result = load_backlog(backlog_file=backlog_file)
    assert result == []


def test_format_backlog_list_empty():
    result = format_backlog_list(items=[])
    assert result == "Backlog is empty."


def test_format_backlog_list_items():
    items: list[BacklogItem] = [
        {"prompt": "hello world", "created_at": "2026-01-01T00:00:00"},
        {"prompt": "test message", "created_at": "2026-01-02T12:30:00"},
    ]
    result = format_backlog_list(items=items)
    assert "2" in result
    assert "hello world" in result
    assert "test message" in result
    assert "2026-01-01T00:00:00" in result
    assert "2026-01-02T12:30:00" in result


@pytest.mark.asyncio
async def test_with_backlog_normal_response():
    @with_backlog
    async def fake_run(*, prompt: str, run_info: dict) -> tuple[str, str | None]:
        run_info["result"] = _result(text="Hello")
        return "Hello", "ses_1"

    bot_data = _bot_data(backlog_file="/tmp/bl.json")
    result, session_id = await fake_run(
        prompt="hi", run_info={}, bot_data=bot_data, user_message="hi"
    )
    assert result == "Hello"
    assert session_id == "ses_1"
    assert bot_data["backlog"] == []


@pytest.mark.asyncio
async def test_with_backlog_auth_error_saves_prompt(tmp_path):
    """A 401 never self-heals, so it goes straight to the backlog without a retry."""
    calls = 0

    @with_backlog
    async def fake_run(*, prompt: str, run_info: dict) -> tuple[str, str | None]:
        nonlocal calls
        calls += 1
        run_info["result"] = AUTH_401
        return "Error: APIError (401): detail", None

    backlog_file = tmp_path / "backlog.json"
    bot_data = _bot_data(backlog_file=backlog_file)
    result, _ = await fake_run(
        prompt="hi", run_info={}, bot_data=bot_data, user_message="my question"
    )
    assert calls == 1
    assert "Authentication error" in result
    assert "TENSORX_API_KEY" in result
    assert json.loads(backlog_file.read_text())[0]["prompt"] == "my question"


@pytest.mark.asyncio
async def test_with_backlog_rate_limit_saves_prompt(tmp_path):
    @with_backlog
    async def fake_run(*, prompt: str, run_info: dict) -> tuple[str, str | None]:
        run_info["result"] = RATE_429
        return "Error: APIError (429): detail", None

    backlog_file = tmp_path / "backlog.json"
    bot_data = _bot_data(backlog_file=backlog_file)
    result, _ = await fake_run(
        prompt="hi", run_info={}, bot_data=bot_data, user_message="q"
    )
    assert "rate limit" in result.lower()
    assert len(bot_data["backlog"]) == 1


@pytest.mark.asyncio
@patch("pyclaudius.backlog.asyncio.sleep", new_callable=AsyncMock)
async def test_with_backlog_never_retries_auth_even_if_marked_retryable(
    mock_sleep: AsyncMock, tmp_path
):
    """A bad key cannot self-heal, whatever the provider claims about retrying."""
    calls = 0

    @with_backlog
    async def fake_run(*, prompt: str, run_info: dict) -> tuple[str, str | None]:
        nonlocal calls
        calls += 1
        run_info["result"] = _result(
            error_name="APIError", status_code=401, is_retryable=True
        )
        return "Error: APIError (401): detail", None

    bot_data = _bot_data(backlog_file=tmp_path / "backlog.json")
    result, _ = await fake_run(
        prompt="hi", run_info={}, bot_data=bot_data, user_message="q"
    )
    assert calls == 1
    mock_sleep.assert_not_awaited()
    assert "Authentication error" in result


@pytest.mark.asyncio
@patch("pyclaudius.backlog.asyncio.sleep", new_callable=AsyncMock)
async def test_with_backlog_retries_when_provider_says_retryable(mock_sleep: AsyncMock):
    """The provider's own isRetryable flag decides — trust it for one retry."""
    calls = 0

    @with_backlog
    async def fake_run(*, prompt: str, run_info: dict) -> tuple[str, str | None]:
        nonlocal calls
        calls += 1
        if calls == 1:
            run_info["result"] = SERVER_500
            return "Error: APIError (500): detail", None
        run_info["result"] = _result(text="Hello")
        return "Hello", "ses_2"

    bot_data = _bot_data(backlog_file="/tmp/bl.json")
    result, session_id = await fake_run(
        prompt="hi", run_info={}, bot_data=bot_data, user_message="q"
    )
    assert calls == 2
    assert result == "Hello"
    assert session_id == "ses_2"
    assert bot_data["backlog"] == []
    mock_sleep.assert_awaited_once_with(5)


@pytest.mark.asyncio
@patch("pyclaudius.backlog.asyncio.sleep", new_callable=AsyncMock)
async def test_with_backlog_retry_failure_still_saves(mock_sleep: AsyncMock, tmp_path):
    @with_backlog
    async def fake_run(*, prompt: str, run_info: dict) -> tuple[str, str | None]:
        run_info["result"] = SERVER_500
        return "Error: APIError (500): detail", None

    backlog_file = tmp_path / "backlog.json"
    bot_data = _bot_data(backlog_file=backlog_file)
    result, _ = await fake_run(
        prompt="hi", run_info={}, bot_data=bot_data, user_message="q"
    )
    assert "Provider error" in result
    assert len(bot_data["backlog"]) == 1


@pytest.mark.asyncio
@patch("pyclaudius.backlog.asyncio.sleep", new_callable=AsyncMock)
async def test_with_backlog_empty_response_is_always_retried(mock_sleep: AsyncMock):
    """An empty stream is the shape of opencode's dropped-event bug."""
    calls = 0

    @with_backlog
    async def fake_run(*, prompt: str, run_info: dict) -> tuple[str, str | None]:
        nonlocal calls
        calls += 1
        if calls == 1:
            run_info["result"] = _result()
            return "", None
        run_info["result"] = _result(text="Hello")
        return "Hello", "ses_2"

    bot_data = _bot_data(backlog_file="/tmp/bl.json")
    result, _ = await fake_run(
        prompt="hi", run_info={}, bot_data=bot_data, user_message="q"
    )
    assert calls == 2
    assert result == "Hello"


@pytest.mark.asyncio
@patch("pyclaudius.backlog.asyncio.sleep", new_callable=AsyncMock)
async def test_with_backlog_no_retry_on_non_retryable_provider_error(
    mock_sleep: AsyncMock, tmp_path
):
    calls = 0

    @with_backlog
    async def fake_run(*, prompt: str, run_info: dict) -> tuple[str, str | None]:
        nonlocal calls
        calls += 1
        run_info["result"] = RATE_429
        return "Error: APIError (429): detail", None

    bot_data = _bot_data(backlog_file=tmp_path / "backlog.json")
    await fake_run(prompt="hi", run_info={}, bot_data=bot_data, user_message="q")
    assert calls == 1
    mock_sleep.assert_not_awaited()


@pytest.mark.asyncio
async def test_with_backlog_disabled():
    @with_backlog
    async def fake_run(*, prompt: str, run_info: dict) -> tuple[str, str | None]:
        run_info["result"] = AUTH_401
        return "Error: APIError (401): detail", None

    bot_data = {
        "settings": MagicMock(backlog_enabled=False, backlog_file="/tmp/bl.json"),
        "backlog": [],
    }
    result, _ = await fake_run(
        prompt="hi", run_info={}, bot_data=bot_data, user_message="q"
    )
    assert result == "Error: APIError (401): detail"
    assert bot_data["backlog"] == []


@pytest.mark.asyncio
async def test_with_backlog_no_bot_data():
    @with_backlog
    async def fake_run(*, prompt: str, run_info: dict) -> tuple[str, str | None]:
        run_info["result"] = AUTH_401
        return "Error: APIError (401): detail", None

    result, _ = await fake_run(prompt="hi", run_info={})
    assert result == "Error: APIError (401): detail"


@pytest.mark.asyncio
async def test_with_backlog_preserves_function_name():
    @with_backlog
    async def my_call(*, prompt: str) -> tuple[str, str | None]:
        return "ok", None

    assert my_call.__name__ == "my_call"


@pytest.mark.asyncio
async def test_with_backlog_empty_user_message_not_saved(tmp_path):
    @with_backlog
    async def fake_run(*, prompt: str, run_info: dict) -> tuple[str, str | None]:
        run_info["result"] = AUTH_401
        return "Error: APIError (401): detail", None

    bot_data = _bot_data(backlog_file=tmp_path / "backlog.json")
    result, _ = await fake_run(
        prompt="hi", run_info={}, bot_data=bot_data, user_message="   "
    )
    assert bot_data["backlog"] == []
    assert result == "Error: APIError (401): detail"


@pytest.mark.asyncio
async def test_with_backlog_appends_to_existing(tmp_path):
    @with_backlog
    async def fake_run(*, prompt: str, run_info: dict) -> tuple[str, str | None]:
        run_info["result"] = AUTH_401
        return "Error: APIError (401): detail", None

    backlog_file = tmp_path / "backlog.json"
    existing: list[BacklogItem] = [
        {"prompt": "first", "created_at": "2026-01-01T00:00:00"}
    ]
    bot_data = _bot_data(backlog_file=backlog_file, backlog=existing)
    result, _ = await fake_run(
        prompt="hi", run_info={}, bot_data=bot_data, user_message="second"
    )
    assert "2 pending" in result
    assert bot_data["backlog"][1]["prompt"] == "second"


@pytest.mark.asyncio
async def test_with_backlog_without_run_info_falls_back_to_empty_check(tmp_path):
    """Without a run_info dict only the empty-response check can fire."""

    @with_backlog
    async def fake_run(*, prompt: str) -> tuple[str, str | None]:
        return "", None

    bot_data = _bot_data(backlog_file=tmp_path / "backlog.json")
    with patch("pyclaudius.backlog.asyncio.sleep", new_callable=AsyncMock):
        result, _ = await fake_run(prompt="hi", bot_data=bot_data, user_message="q")
    assert "no output" in result
    assert len(bot_data["backlog"]) == 1
