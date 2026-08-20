import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from pyclaudius.opencode import (
    API_KEY_ENV,
    LOCAL_FAILURE,
    build_subprocess_env,
    call_opencode,
    is_resumable_session,
)
from pyclaudius.opencode_events import parse_opencode_stream

SESSION = "ses_fe592c0e1ffeTZIh71EY8Wn1Ey"


def _stream(*events: dict) -> bytes:
    return ("\n".join(json.dumps(e) for e in events) + "\n").encode()


def _ok_stream(text: str = "Hello from opencode", *, session: str = SESSION) -> bytes:
    return _stream(
        {"type": "step_start", "sessionID": session},
        {"type": "text", "sessionID": session, "part": {"id": "p1", "text": text}},
        {
            "type": "step_finish",
            "sessionID": session,
            "part": {"reason": "stop", "tokens": {"total": 42}, "cost": 0.5},
        },
    )


@pytest.fixture
def mock_process():
    proc = AsyncMock()
    proc.returncode = 0
    proc.communicate.return_value = (_ok_stream(), b"")
    return proc


def _exec_patch(proc):
    return patch(
        "pyclaudius.opencode.asyncio.create_subprocess_exec", return_value=proc
    )


# --- argv construction ---------------------------------------------------


async def test_argv_base_flags(mock_process):
    with _exec_patch(mock_process) as mock_exec:
        await call_opencode(prompt="hello", opencode_path="opencode")
    args = mock_exec.call_args[0]
    assert args == (
        "opencode",
        "run",
        "--format",
        "json",
        "--log-level",
        "ERROR",
        "--pure",
        "--",
        "hello",
    )


async def test_prompt_is_the_last_argument(mock_process):
    with _exec_patch(mock_process) as mock_exec:
        await call_opencode(
            prompt="the prompt", model="p/m", session_id=SESSION, resume=True
        )
    assert mock_exec.call_args[0][-1] == "the prompt"


async def test_model_is_passed(mock_process):
    with _exec_patch(mock_process) as mock_exec:
        await call_opencode(prompt="hi", model="tensorx/moonshotai/kimi-k3")
    args = mock_exec.call_args[0]
    assert args[args.index("--model") + 1] == "tensorx/moonshotai/kimi-k3"


async def test_model_omitted_when_unset(mock_process):
    with _exec_patch(mock_process) as mock_exec:
        await call_opencode(prompt="hi")
    assert "--model" not in mock_exec.call_args[0]


async def test_fresh_call_passes_no_session(mock_process):
    """The id is minted by opencode and harvested from the stream."""
    with _exec_patch(mock_process) as mock_exec:
        await call_opencode(prompt="hi")
    assert "--session" not in mock_exec.call_args[0]


async def test_resume_passes_session(mock_process):
    with _exec_patch(mock_process) as mock_exec:
        await call_opencode(prompt="hi", session_id=SESSION, resume=True)
    args = mock_exec.call_args[0]
    assert args[args.index("--session") + 1] == SESSION


async def test_resume_false_ignores_stored_session(mock_process):
    with _exec_patch(mock_process) as mock_exec:
        await call_opencode(prompt="hi", session_id=SESSION, resume=False)
    assert "--session" not in mock_exec.call_args[0]


async def test_legacy_uuid_session_is_not_resumed(mock_process):
    """A uuid persisted by a pre-opencode version must never reach --session."""
    with _exec_patch(mock_process) as mock_exec:
        await call_opencode(
            prompt="hi", session_id="a1b2c3d4-e5f6-7890-abcd-ef1234567890", resume=True
        )
    assert "--session" not in mock_exec.call_args[0]


async def test_prompt_is_separated_from_options(mock_process):
    """Without "--", --file swallows the prompt and a leading dash prints usage."""
    with _exec_patch(mock_process) as mock_exec:
        await call_opencode(prompt="--not-a-flag", files=["/a.png"])
    args = list(mock_exec.call_args[0])
    assert args[-2:] == ["--", "--not-a-flag"]
    assert args.index("--file") < args.index("--")


async def test_files_are_attached(mock_process):
    """Attaching hands the file to the model; naming a path only hopes it reads it."""
    with _exec_patch(mock_process) as mock_exec:
        await call_opencode(prompt="hi", files=["/work/uploads/image_1.jpg"])
    args = mock_exec.call_args[0]
    assert args[args.index("--file") + 1] == "/work/uploads/image_1.jpg"


async def test_multiple_files_are_attached(mock_process):
    with _exec_patch(mock_process) as mock_exec:
        await call_opencode(prompt="hi", files=["/a.png", "/b.pdf"])
    args = list(mock_exec.call_args[0])
    assert args.count("--file") == 2
    assert "/a.png" in args and "/b.pdf" in args


async def test_no_file_flag_without_attachments(mock_process):
    with _exec_patch(mock_process) as mock_exec:
        await call_opencode(prompt="hi")
    assert "--file" not in mock_exec.call_args[0]


async def test_attachments_survive_a_stale_session_retry():
    stale = AsyncMock()
    stale.returncode = 1
    stale.communicate.return_value = (b"", b"Error: Session not found\n")
    fresh = AsyncMock()
    fresh.returncode = 0
    fresh.communicate.return_value = (_ok_stream(), b"")
    with patch(
        "pyclaudius.opencode.asyncio.create_subprocess_exec", side_effect=[stale, fresh]
    ) as mock_exec:
        await call_opencode(
            prompt="hi", session_id=SESSION, resume=True, files=["/a.png"]
        )
    assert "/a.png" in mock_exec.call_args_list[1][0]


async def test_auto_approve_flag(mock_process):
    with _exec_patch(mock_process) as mock_exec:
        await call_opencode(prompt="hi", auto_approve=True)
    assert "--auto" in mock_exec.call_args[0]


async def test_auto_approve_off_by_default(mock_process):
    with _exec_patch(mock_process) as mock_exec:
        await call_opencode(prompt="hi")
    assert "--auto" not in mock_exec.call_args[0]


async def test_cwd_is_passed(mock_process):
    with _exec_patch(mock_process) as mock_exec:
        await call_opencode(prompt="hi", cwd="/work")
    assert mock_exec.call_args[1]["cwd"] == "/work"


async def test_stdin_is_closed(mock_process):
    """No TTY, no stdin: a permission prompt must never be able to block."""
    import asyncio as _asyncio

    with _exec_patch(mock_process) as mock_exec:
        await call_opencode(prompt="hi")
    assert mock_exec.call_args[1]["stdin"] == _asyncio.subprocess.DEVNULL


# --- return values -------------------------------------------------------


async def test_returns_text_and_session_id(mock_process):
    with _exec_patch(mock_process):
        response, session_id = await call_opencode(prompt="hi")
    assert response == "Hello from opencode"
    assert session_id == SESSION


async def test_records_usage_in_run_info(mock_process):
    run_info: dict = {}
    with _exec_patch(mock_process):
        await call_opencode(prompt="hi", run_info=run_info)
    assert run_info["tokens"] == 42
    assert run_info["cost"] == 0.5
    assert run_info["result"].session_id == SESSION


async def test_error_event_is_formatted_for_the_user(mock_process):
    mock_process.returncode = 1
    mock_process.communicate.return_value = (
        _stream(
            {
                "type": "error",
                "sessionID": SESSION,
                "error": {
                    "name": "APIError",
                    "data": {
                        "message": "Invalid API key or unauthorised access.",
                        "statusCode": 401,
                        "isRetryable": False,
                    },
                },
            }
        ),
        b"",
    )
    with _exec_patch(mock_process):
        response, _ = await call_opencode(prompt="hi")
    assert response == "Error: APIError (401): Invalid API key or unauthorised access."


async def test_empty_stream_returns_empty_string(mock_process):
    mock_process.communicate.return_value = (b"", b"")
    with _exec_patch(mock_process):
        response, session_id = await call_opencode(prompt="hi")
    assert response == ""
    assert session_id is None


async def test_nonzero_exit_without_events_reports_stderr(mock_process):
    mock_process.returncode = 1
    mock_process.communicate.return_value = (b"", b"something broke\n")
    with _exec_patch(mock_process):
        response, _ = await call_opencode(prompt="hi")
    assert response == "Error: something broke"


async def test_nonzero_exit_still_returns_text_when_present(mock_process):
    mock_process.returncode = 1
    mock_process.communicate.return_value = (_ok_stream("partial answer"), b"")
    with _exec_patch(mock_process):
        response, _ = await call_opencode(prompt="hi")
    assert response == "partial answer"


async def test_timeout_kills_the_process(mock_process):
    mock_process.communicate.side_effect = TimeoutError
    mock_process.kill = MagicMock()
    mock_process.wait = AsyncMock()
    with _exec_patch(mock_process):
        response, session_id = await call_opencode(prompt="hi", timeout=7)
    assert response == "Error: opencode timed out after 7s"
    assert session_id is None
    mock_process.kill.assert_called_once()


async def test_missing_binary_is_reported(mock_process):
    with patch(
        "pyclaudius.opencode.asyncio.create_subprocess_exec",
        side_effect=FileNotFoundError("no opencode"),
    ):
        response, _ = await call_opencode(prompt="hi")
    assert response.startswith("Error: Could not run opencode:")


# --- stale sessions ------------------------------------------------------


async def test_stale_session_retries_without_session():
    """A forgotten session id prints plain text on stderr, not a JSON event."""
    stale = AsyncMock()
    stale.returncode = 1
    stale.communicate.return_value = (b"", b"\x1b[91mError: \x1b[0mSession not found\n")
    fresh = AsyncMock()
    fresh.returncode = 0
    fresh.communicate.return_value = (_ok_stream(session="ses_new"), b"")

    with patch(
        "pyclaudius.opencode.asyncio.create_subprocess_exec",
        side_effect=[stale, fresh],
    ) as mock_exec:
        response, session_id = await call_opencode(
            prompt="hi", session_id=SESSION, resume=True
        )

    assert response == "Hello from opencode"
    assert session_id == "ses_new"
    assert mock_exec.call_count == 2
    assert "--session" not in mock_exec.call_args_list[1][0]


async def test_nonzero_exit_with_no_events_is_treated_as_stale():
    first = AsyncMock()
    first.returncode = 1
    first.communicate.return_value = (b"", b"")
    second = AsyncMock()
    second.returncode = 0
    second.communicate.return_value = (_ok_stream(), b"")
    with patch(
        "pyclaudius.opencode.asyncio.create_subprocess_exec",
        side_effect=[first, second],
    ) as mock_exec:
        await call_opencode(prompt="hi", session_id=SESSION, resume=True)
    assert mock_exec.call_count == 2


async def test_api_error_is_not_treated_as_stale(mock_process):
    """A 401 is a real failure — retrying as a fresh session would just burn tokens."""
    mock_process.returncode = 1
    mock_process.communicate.return_value = (
        _stream(
            {
                "type": "error",
                "sessionID": SESSION,
                "error": {"name": "APIError", "data": {"statusCode": 401}},
            }
        ),
        b"",
    )
    with _exec_patch(mock_process) as mock_exec:
        await call_opencode(prompt="hi", session_id=SESSION, resume=True)
    assert mock_exec.call_count == 1


async def test_timeout_is_not_treated_as_stale(mock_process):
    """A timed-out run must not be silently retried — it would double the wait."""
    mock_process.communicate.side_effect = TimeoutError
    mock_process.kill = MagicMock()
    mock_process.wait = AsyncMock()
    with _exec_patch(mock_process) as mock_exec:
        await call_opencode(prompt="hi", session_id=SESSION, resume=True, timeout=1)
    assert mock_exec.call_count == 1


async def test_fresh_call_is_never_retried_as_stale():
    proc = AsyncMock()
    proc.returncode = 1
    proc.communicate.return_value = (b"", b"Error: Session not found\n")
    with patch(
        "pyclaudius.opencode.asyncio.create_subprocess_exec", return_value=proc
    ) as mock_exec:
        await call_opencode(prompt="hi")
    assert mock_exec.call_count == 1


# --- environment ---------------------------------------------------------


def test_env_forwards_home_and_path(monkeypatch):
    monkeypatch.setenv("HOME", "/home/tester")
    monkeypatch.setenv("PATH", "/usr/bin")
    env = build_subprocess_env(api_key="", config_file=None)
    assert env["HOME"] == "/home/tester"
    assert env["PATH"] == "/usr/bin"


def test_env_strips_unrelated_secrets(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "super-secret")
    monkeypatch.setenv("EMAIL_PASSWORD", "also-secret")
    env = build_subprocess_env(api_key="", config_file=None)
    assert "TELEGRAM_BOT_TOKEN" not in env
    assert "EMAIL_PASSWORD" not in env


def test_env_carries_the_provider_key():
    """The key in the env is what activates TensorX from opencode's registry."""
    env = build_subprocess_env(api_key="sk-test", config_file=None)
    assert env[API_KEY_ENV] == "sk-test"


def test_env_omits_empty_provider_key():
    assert API_KEY_ENV not in build_subprocess_env(api_key="", config_file=None)


def test_env_points_at_the_config_file():
    env = build_subprocess_env(api_key="", config_file=Path("/relay/opencode.json"))
    assert env["OPENCODE_CONFIG"] == "/relay/opencode.json"


def test_env_forwards_xdg_paths(monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", "/xdg/data")
    env = build_subprocess_env(api_key="", config_file=None)
    assert env["XDG_DATA_HOME"] == "/xdg/data"


def test_env_disables_colour():
    env = build_subprocess_env(api_key="", config_file=None)
    assert env["NO_COLOR"] == "1"
    assert env["TERM"] == "dumb"


async def test_env_is_used_for_the_subprocess(mock_process, monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "leak-me-not")
    with _exec_patch(mock_process) as mock_exec:
        await call_opencode(prompt="hi", api_key="sk-x")
    env = mock_exec.call_args[1]["env"]
    assert env[API_KEY_ENV] == "sk-x"
    assert "TELEGRAM_BOT_TOKEN" not in env


# --- helpers -------------------------------------------------------------


@pytest.mark.parametrize(
    ("session_id", "expected"),
    [
        (SESSION, True),
        ("ses_x", True),
        ("a1b2c3d4-e5f6-7890-abcd-ef1234567890", False),
        ("", False),
        (None, False),
    ],
)
def test_is_resumable_session(session_id, expected):
    assert is_resumable_session(session_id=session_id) is expected


def test_local_failure_sentinel_is_negative():
    """_is_stale_session relies on this being below any real exit status."""
    assert LOCAL_FAILURE < 0


# --- backlog integration -------------------------------------------------


async def test_backlog_records_failed_prompt(mock_process, tmp_path):
    mock_process.returncode = 1
    mock_process.communicate.return_value = (
        _stream(
            {
                "type": "error",
                "sessionID": SESSION,
                "error": {
                    "name": "APIError",
                    "data": {
                        "message": "nope",
                        "statusCode": 401,
                        "isRetryable": False,
                    },
                },
            }
        ),
        b"",
    )
    backlog_file = tmp_path / "backlog.json"
    bot_data = {
        "settings": MagicMock(backlog_enabled=True, backlog_file=backlog_file),
        "backlog": [],
    }
    with _exec_patch(mock_process):
        response, _ = await call_opencode(
            prompt="hi", bot_data=bot_data, user_message="original message", run_info={}
        )
    assert "saved to backlog" in response
    assert json.loads(backlog_file.read_text())[0]["prompt"] == "original message"


async def test_backlog_left_alone_on_success(mock_process, tmp_path):
    bot_data = {
        "settings": MagicMock(
            backlog_enabled=True, backlog_file=tmp_path / "backlog.json"
        ),
        "backlog": [],
    }
    with _exec_patch(mock_process):
        response, _ = await call_opencode(
            prompt="hi", bot_data=bot_data, user_message="msg", run_info={}
        )
    assert response == "Hello from opencode"
    assert bot_data["backlog"] == []


def test_ok_stream_fixture_parses():
    """Guard the test helper itself, so failures point at the code under test."""
    result = parse_opencode_stream(stdout=_ok_stream().decode())
    assert result.text == "Hello from opencode"
    assert result.session_id == SESSION
