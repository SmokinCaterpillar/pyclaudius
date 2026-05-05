import logging
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from pyclaudius.claude import _build_subprocess_env, call_claude


@pytest.fixture
def mock_process():
    proc = AsyncMock()
    proc.returncode = 0
    proc.communicate.return_value = (b"Hello from Claude", b"")
    return proc


@pytest.mark.asyncio
async def test_call_claude_success(mock_process):
    with patch(
        "pyclaudius.claude.asyncio.create_subprocess_exec", return_value=mock_process
    ) as mock_exec:
        result, session_id = await call_claude(prompt="hello")
        assert result == "Hello from Claude"
        assert session_id is not None
        mock_exec.assert_called_once()
        args = mock_exec.call_args[0]
        assert args[:4] == ("claude", "-p", "hello", "--output-format")
        assert "--session-id" in args


@pytest.mark.asyncio
async def test_call_claude_with_resume(mock_process):
    with patch(
        "pyclaudius.claude.asyncio.create_subprocess_exec", return_value=mock_process
    ) as mock_exec:
        await call_claude(
            prompt="hi",
            resume=True,
            session_id="abc-123",
        )
        args = mock_exec.call_args[0]
        assert "--resume" in args
        assert "abc-123" in args


@pytest.mark.asyncio
async def test_call_claude_resume_without_session_id(mock_process):
    with patch(
        "pyclaudius.claude.asyncio.create_subprocess_exec", return_value=mock_process
    ) as mock_exec:
        _, session_id = await call_claude(prompt="hi", resume=True, session_id=None)
        args = mock_exec.call_args[0]
        assert "--resume" not in args
        assert "--session-id" in args
        assert session_id is not None


@pytest.mark.asyncio
async def test_call_claude_nonzero_exit():
    proc = AsyncMock()
    proc.returncode = 1
    proc.communicate.return_value = (b"", b"something went wrong")
    with patch("pyclaudius.claude.asyncio.create_subprocess_exec", return_value=proc):
        result, session_id = await call_claude(prompt="fail")
        assert result.startswith("Error:")
        assert "something went wrong" in result
        assert session_id is None


@pytest.mark.asyncio
async def test_call_claude_nonzero_exit_no_stderr():
    proc = AsyncMock()
    proc.returncode = 42
    proc.communicate.return_value = (b"", b"")
    with patch("pyclaudius.claude.asyncio.create_subprocess_exec", return_value=proc):
        result, _ = await call_claude(prompt="fail")
        assert "42" in result


@pytest.mark.asyncio
async def test_call_claude_generates_session_id():
    proc = AsyncMock()
    proc.returncode = 0
    proc.communicate.return_value = (b"Response text", b"")
    with patch(
        "pyclaudius.claude.asyncio.create_subprocess_exec", return_value=proc
    ) as mock_exec:
        result, session_id = await call_claude(prompt="test")
        assert result == "Response text"
        assert session_id is not None
        args = mock_exec.call_args[0]
        assert "--session-id" in args
        idx = args.index("--session-id")
        assert args[idx + 1] == session_id


@pytest.mark.asyncio
async def test_call_claude_file_not_found():
    with patch(
        "pyclaudius.claude.asyncio.create_subprocess_exec",
        side_effect=FileNotFoundError,
    ):
        result, session_id = await call_claude(prompt="test")
        assert "Error" in result
        assert session_id is None


@pytest.mark.asyncio
async def test_call_claude_custom_path(mock_process):
    with patch(
        "pyclaudius.claude.asyncio.create_subprocess_exec", return_value=mock_process
    ) as mock_exec:
        await call_claude(prompt="hi", claude_path="/usr/local/bin/claude")
        args = mock_exec.call_args[0]
        assert args[0] == "/usr/local/bin/claude"


@pytest.mark.asyncio
async def test_call_claude_allowed_tools(mock_process):
    with patch(
        "pyclaudius.claude.asyncio.create_subprocess_exec", return_value=mock_process
    ) as mock_exec:
        await call_claude(prompt="hi", allowed_tools=["WebSearch"])
        args = mock_exec.call_args[0]
        idx = args.index("--allowedTools")
        assert args[idx + 1] == "WebSearch"


@pytest.mark.asyncio
async def test_call_claude_allowed_tools_multiple(mock_process):
    with patch(
        "pyclaudius.claude.asyncio.create_subprocess_exec", return_value=mock_process
    ) as mock_exec:
        await call_claude(prompt="hi", allowed_tools=["WebSearch", "WebFetch"])
        args = mock_exec.call_args[0]
        assert args.count("--allowedTools") == 1
        idx = args.index("--allowedTools")
        assert args[idx + 1] == "WebSearch,WebFetch"


@pytest.mark.asyncio
async def test_call_claude_allowed_tools_empty(mock_process):
    with patch(
        "pyclaudius.claude.asyncio.create_subprocess_exec", return_value=mock_process
    ) as mock_exec:
        await call_claude(prompt="hi", allowed_tools=[])
        args = mock_exec.call_args[0]
        assert "--allowedTools" not in args


@pytest.mark.asyncio
async def test_call_claude_cwd_passed_to_subprocess(mock_process):
    with patch(
        "pyclaudius.claude.asyncio.create_subprocess_exec", return_value=mock_process
    ) as mock_exec:
        await call_claude(prompt="hi", cwd="/tmp/work")
        assert mock_exec.call_args.kwargs["cwd"] == "/tmp/work"


@pytest.mark.asyncio
async def test_call_claude_cwd_default_is_none(mock_process):
    with patch(
        "pyclaudius.claude.asyncio.create_subprocess_exec", return_value=mock_process
    ) as mock_exec:
        await call_claude(prompt="hi")
        assert mock_exec.call_args.kwargs["cwd"] is None


@pytest.mark.asyncio
async def test_call_claude_nonzero_exit_with_stdout():
    proc = AsyncMock()
    proc.returncode = 1
    proc.communicate.return_value = (b"Partial response from Claude", b"tool error")
    with patch("pyclaudius.claude.asyncio.create_subprocess_exec", return_value=proc):
        result, session_id = await call_claude(prompt="search something")
        assert result == "Partial response from Claude"
        assert session_id is not None


def test_build_subprocess_env_contains_only_home_and_path():
    with patch.dict(
        "os.environ",
        {
            "HOME": "/home/test",
            "PATH": "/usr/bin",
            "TELEGRAM_BOT_TOKEN": "secret",
            "OTHER_VAR": "value",
        },
        clear=True,
    ):
        env = _build_subprocess_env()
        assert env == {
            "HOME": "/home/test",
            "PATH": "/usr/bin",
            "CLAUDE_AUTOCOMPACT_PCT_OVERRIDE": "90",
        }


def test_build_subprocess_env_excludes_secrets():
    with patch.dict(
        "os.environ",
        {"HOME": "/home/test", "PATH": "/usr/bin", "TELEGRAM_BOT_TOKEN": "secret123"},
        clear=True,
    ):
        env = _build_subprocess_env()
        assert "TELEGRAM_BOT_TOKEN" not in env


def test_build_subprocess_env_handles_missing_keys():
    with patch.dict("os.environ", {"HOME": "/home/test"}, clear=True):
        env = _build_subprocess_env()
        assert env == {"HOME": "/home/test", "CLAUDE_AUTOCOMPACT_PCT_OVERRIDE": "90"}
        assert "PATH" not in env


def test_build_subprocess_env_sets_autocompact():
    with patch.dict(
        "os.environ", {"HOME": "/home/test", "PATH": "/usr/bin"}, clear=True
    ):
        env = _build_subprocess_env()
        assert env["CLAUDE_AUTOCOMPACT_PCT_OVERRIDE"] == "90"


@pytest.mark.asyncio
async def test_call_claude_passes_sanitized_env(mock_process):
    with (
        patch(
            "pyclaudius.claude.asyncio.create_subprocess_exec",
            return_value=mock_process,
        ) as mock_exec,
        patch.dict(
            "os.environ",
            {"HOME": "/home/test", "PATH": "/usr/bin", "TELEGRAM_BOT_TOKEN": "secret"},
            clear=True,
        ),
    ):
        await call_claude(prompt="hi")
        env_kwarg = mock_exec.call_args.kwargs["env"]
        assert env_kwarg == {
            "HOME": "/home/test",
            "PATH": "/usr/bin",
            "CLAUDE_AUTOCOMPACT_PCT_OVERRIDE": "90",
        }
        assert "TELEGRAM_BOT_TOKEN" not in env_kwarg


@pytest.mark.asyncio
async def test_call_claude_backlog_saves_on_auth_error(tmp_path):
    """Auth error with bot_data triggers backlog save via decorator."""
    proc = AsyncMock()
    proc.returncode = 0
    proc.communicate.return_value = (
        b'{"type":"error","error":{"type":"authentication_error"}}',
        b"",
    )

    backlog_file = tmp_path / "backlog.json"
    bot_data = {
        "settings": MagicMock(backlog_enabled=True, backlog_file=backlog_file),
        "backlog": [],
    }

    with patch("pyclaudius.claude.asyncio.create_subprocess_exec", return_value=proc):
        result, session_id = await call_claude(
            prompt="hello",
            bot_data=bot_data,
            user_message="original question",
        )
        assert "Authentication error" in result
        assert session_id is None
        assert len(bot_data["backlog"]) == 1
        assert bot_data["backlog"][0]["prompt"] == "original question"


@pytest.mark.asyncio
async def test_call_claude_no_backlog_on_normal_response(mock_process):
    """Normal response passes through without affecting backlog."""
    bot_data = {
        "settings": MagicMock(backlog_enabled=True, backlog_file="/tmp/bl.json"),
        "backlog": [],
    }
    with patch(
        "pyclaudius.claude.asyncio.create_subprocess_exec",
        return_value=mock_process,
    ):
        result, _ = await call_claude(
            prompt="hello", bot_data=bot_data, user_message="hello"
        )
        assert result == "Hello from Claude"
        assert bot_data["backlog"] == []


@pytest.mark.asyncio
async def test_call_claude_timeout():
    proc = AsyncMock()
    proc.communicate.side_effect = TimeoutError
    proc.kill = MagicMock()
    proc.wait = AsyncMock()

    with patch("pyclaudius.claude.asyncio.create_subprocess_exec", return_value=proc):
        result, session_id = await call_claude(prompt="slow query", timeout=10)
        assert "timed out after 10s" in result
        assert session_id is None
        proc.kill.assert_called_once()
        proc.wait.assert_awaited_once()


@pytest.mark.asyncio
async def test_call_claude_permission_error():
    with patch(
        "pyclaudius.claude.asyncio.create_subprocess_exec",
        side_effect=PermissionError("Permission denied"),
    ):
        result, session_id = await call_claude(prompt="test")
        assert "Error" in result
        assert "Permission denied" in result
        assert session_id is None


@pytest.mark.asyncio
async def test_call_claude_empty_stdout_with_stderr():
    proc = AsyncMock()
    proc.returncode = 0
    proc.communicate.return_value = (b"", b"rate limit exceeded")
    with patch("pyclaudius.claude.asyncio.create_subprocess_exec", return_value=proc):
        result, session_id = await call_claude(prompt="hello")
        assert result == "Error: rate limit exceeded"
        assert session_id is None


@pytest.mark.asyncio
async def test_call_claude_empty_stdout_empty_stderr(caplog):
    proc = AsyncMock()
    proc.returncode = 0
    proc.communicate.return_value = (b"", b"")
    with patch("pyclaudius.claude.asyncio.create_subprocess_exec", return_value=proc):
        with caplog.at_level(logging.WARNING, logger="pyclaudius.claude"):
            result, session_id = await call_claude(prompt="hello")
        assert result == ""
        assert session_id is not None
        assert "rc=0" in caplog.text
        assert "stdout_bytes=0" in caplog.text
        assert "stderr_bytes=0" in caplog.text
        assert "session=" in caplog.text


@pytest.mark.asyncio
async def test_call_claude_retries_on_no_conversation_found():
    """Stale --resume returning 'No conversation found' triggers a retry."""
    proc1 = AsyncMock()
    proc1.returncode = 0
    proc1.communicate.return_value = (
        b"Error: No conversation found with session ID: abc-123",
        b"",
    )
    proc2 = AsyncMock()
    proc2.returncode = 0
    proc2.communicate.return_value = (b"Recovered", b"")

    with patch(
        "pyclaudius.claude.asyncio.create_subprocess_exec",
        side_effect=[proc1, proc2],
    ) as mock_exec:
        result, session_id = await call_claude(
            prompt="hi", resume=True, session_id="abc-123"
        )
        assert result == "Recovered"
        assert mock_exec.call_count == 2
        first_args = mock_exec.call_args_list[0][0]
        assert "--resume" in first_args
        assert "abc-123" in first_args
        second_args = mock_exec.call_args_list[1][0]
        assert "--resume" not in second_args
        assert "--session-id" in second_args
        assert session_id is not None
        assert session_id != "abc-123"


@pytest.mark.asyncio
async def test_call_claude_retries_on_silent_resume_failure():
    """--resume with rc=0 and empty stdout/stderr triggers a retry."""
    proc1 = AsyncMock()
    proc1.returncode = 0
    proc1.communicate.return_value = (b"", b"")
    proc2 = AsyncMock()
    proc2.returncode = 0
    proc2.communicate.return_value = (b"Recovered", b"")

    with patch(
        "pyclaudius.claude.asyncio.create_subprocess_exec",
        side_effect=[proc1, proc2],
    ) as mock_exec:
        result, session_id = await call_claude(
            prompt="hi", resume=True, session_id="stale-id"
        )
        assert result == "Recovered"
        assert mock_exec.call_count == 2
        second_args = mock_exec.call_args_list[1][0]
        assert "--resume" not in second_args
        assert "--session-id" in second_args
        assert session_id != "stale-id"


@pytest.mark.asyncio
async def test_call_claude_no_retry_when_not_resuming():
    """A fresh session with empty output must not loop into a retry."""
    proc = AsyncMock()
    proc.returncode = 0
    proc.communicate.return_value = (b"", b"")

    with patch(
        "pyclaudius.claude.asyncio.create_subprocess_exec",
        return_value=proc,
    ) as mock_exec:
        result, session_id = await call_claude(prompt="hi")
        assert result == ""
        assert session_id is not None
        assert mock_exec.call_count == 1


@pytest.mark.asyncio
async def test_call_claude_no_backlog_without_bot_data(mock_process):
    """Without bot_data kwarg, auth error passes through unchanged."""
    proc = AsyncMock()
    proc.returncode = 0
    proc.communicate.return_value = (
        b'{"type":"error","error":{"type":"authentication_error"}}',
        b"",
    )
    with patch(
        "pyclaudius.claude.asyncio.create_subprocess_exec",
        return_value=proc,
    ) as mock_exec:
        result, session_id = await call_claude(prompt="hello")
        assert "authentication_error" in result
        assert session_id is not None
        mock_exec.assert_called_once()


@pytest.mark.asyncio
async def test_call_claude_empty_triggers_tmux_retry_and_backlog(tmp_path):
    """Persistent silent failure triggers tmux keepalive then saves to backlog."""
    proc = AsyncMock()
    proc.returncode = 0
    proc.communicate.return_value = (b"", b"")

    backlog_file = tmp_path / "backlog.json"
    bot_data = {
        "settings": MagicMock(
            backlog_enabled=True,
            backlog_file=backlog_file,
            tmux_session="claude",
        ),
        "backlog": [],
    }

    with (
        patch(
            "pyclaudius.claude.asyncio.create_subprocess_exec",
            return_value=proc,
        ),
        patch(
            "pyclaudius.backlog.send_tmux_keepalive",
            new_callable=AsyncMock,
        ) as mock_keepalive,
        patch("pyclaudius.backlog.asyncio.sleep", new_callable=AsyncMock),
    ):
        result, session_id = await call_claude(
            prompt="hello",
            bot_data=bot_data,
            user_message="original question",
        )
        mock_keepalive.assert_awaited_once_with(session_name="claude")
        assert "Claude CLI returned no output" in result
        assert "saved to backlog" in result
        assert session_id is None
        assert len(bot_data["backlog"]) == 1
        assert bot_data["backlog"][0]["prompt"] == "original question"


@pytest.mark.asyncio
async def test_call_claude_empty_recovers_after_tmux_retry(tmp_path):
    """Empty first call, tmux keepalive, retry succeeds — no backlog."""
    proc1 = AsyncMock()
    proc1.returncode = 0
    proc1.communicate.return_value = (b"", b"")
    proc2 = AsyncMock()
    proc2.returncode = 0
    proc2.communicate.return_value = (b"Recovered", b"")

    backlog_file = tmp_path / "backlog.json"
    bot_data = {
        "settings": MagicMock(
            backlog_enabled=True,
            backlog_file=backlog_file,
            tmux_session="claude",
        ),
        "backlog": [],
    }

    with (
        patch(
            "pyclaudius.claude.asyncio.create_subprocess_exec",
            side_effect=[proc1, proc2],
        ),
        patch(
            "pyclaudius.backlog.send_tmux_keepalive",
            new_callable=AsyncMock,
        ) as mock_keepalive,
        patch("pyclaudius.backlog.asyncio.sleep", new_callable=AsyncMock),
    ):
        result, _ = await call_claude(
            prompt="hello",
            bot_data=bot_data,
            user_message="original question",
        )
        mock_keepalive.assert_awaited_once_with(session_name="claude")
        assert result == "Recovered"
        assert bot_data["backlog"] == []


@pytest.mark.asyncio
async def test_call_claude_empty_no_retry_without_tmux_session(tmp_path):
    """Without tmux_session configured, empty response goes straight to backlog."""
    proc = AsyncMock()
    proc.returncode = 0
    proc.communicate.return_value = (b"", b"")

    backlog_file = tmp_path / "backlog.json"
    bot_data = {
        "settings": MagicMock(
            backlog_enabled=True,
            backlog_file=backlog_file,
            tmux_session=None,
        ),
        "backlog": [],
    }

    with (
        patch(
            "pyclaudius.claude.asyncio.create_subprocess_exec",
            return_value=proc,
        ) as mock_exec,
        patch(
            "pyclaudius.backlog.send_tmux_keepalive",
            new_callable=AsyncMock,
        ) as mock_keepalive,
    ):
        result, _ = await call_claude(
            prompt="hello",
            bot_data=bot_data,
            user_message="original question",
        )
        mock_keepalive.assert_not_awaited()
        # Only one subprocess call (no retry without tmux_session).
        assert mock_exec.call_count == 1
        assert "Claude CLI returned no output" in result
        assert len(bot_data["backlog"]) == 1


@pytest.mark.asyncio
async def test_call_claude_empty_no_backlog_when_disabled(tmp_path):
    """With backlog disabled, empty response is returned as-is."""
    proc = AsyncMock()
    proc.returncode = 0
    proc.communicate.return_value = (b"", b"")

    bot_data = {
        "settings": MagicMock(
            backlog_enabled=False,
            backlog_file=tmp_path / "backlog.json",
            tmux_session="claude",
        ),
        "backlog": [],
    }

    with (
        patch(
            "pyclaudius.claude.asyncio.create_subprocess_exec",
            return_value=proc,
        ),
        patch(
            "pyclaudius.backlog.send_tmux_keepalive",
            new_callable=AsyncMock,
        ) as mock_keepalive,
    ):
        result, _ = await call_claude(
            prompt="hello",
            bot_data=bot_data,
            user_message="original question",
        )
        mock_keepalive.assert_not_awaited()
        assert result == ""
        assert bot_data["backlog"] == []
