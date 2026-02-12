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
        assert env == {"HOME": "/home/test", "PATH": "/usr/bin"}


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
        assert env == {"HOME": "/home/test"}
        assert "PATH" not in env


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
        assert env_kwarg == {"HOME": "/home/test", "PATH": "/usr/bin"}
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
