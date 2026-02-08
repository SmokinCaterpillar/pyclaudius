from unittest.mock import AsyncMock, patch

import pytest

from pyclaudius.claude import call_claude


@pytest.fixture
def mock_process():
    proc = AsyncMock()
    proc.returncode = 0
    proc.communicate.return_value = (b"Hello from Claude", b"")
    return proc


@pytest.mark.asyncio
async def test_call_claude_success(mock_process):
    with patch("pyclaudius.claude.asyncio.create_subprocess_exec", return_value=mock_process) as mock_exec:
        result, session_id = await call_claude(prompt="hello")
        assert result == "Hello from Claude"
        assert session_id is not None
        mock_exec.assert_called_once()
        args = mock_exec.call_args[0]
        assert args[:4] == ("claude", "-p", "hello", "--output-format")
        assert "--session-id" in args


@pytest.mark.asyncio
async def test_call_claude_with_resume(mock_process):
    with patch("pyclaudius.claude.asyncio.create_subprocess_exec", return_value=mock_process) as mock_exec:
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
    with patch("pyclaudius.claude.asyncio.create_subprocess_exec", return_value=mock_process) as mock_exec:
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
    with patch("pyclaudius.claude.asyncio.create_subprocess_exec", return_value=proc) as mock_exec:
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
    with patch("pyclaudius.claude.asyncio.create_subprocess_exec", return_value=mock_process) as mock_exec:
        await call_claude(prompt="hi", claude_path="/usr/local/bin/claude")
        args = mock_exec.call_args[0]
        assert args[0] == "/usr/local/bin/claude"


@pytest.mark.asyncio
async def test_call_claude_allowed_tools(mock_process):
    with patch("pyclaudius.claude.asyncio.create_subprocess_exec", return_value=mock_process) as mock_exec:
        await call_claude(prompt="hi", allowed_tools=["WebSearch"])
        args = mock_exec.call_args[0]
        idx = args.index("--allowedTools")
        assert args[idx + 1] == "WebSearch"


@pytest.mark.asyncio
async def test_call_claude_allowed_tools_multiple(mock_process):
    with patch("pyclaudius.claude.asyncio.create_subprocess_exec", return_value=mock_process) as mock_exec:
        await call_claude(prompt="hi", allowed_tools=["WebSearch", "WebFetch"])
        args = mock_exec.call_args[0]
        assert args.count("--allowedTools") == 1
        idx = args.index("--allowedTools")
        assert args[idx + 1] == "WebSearch,WebFetch"


@pytest.mark.asyncio
async def test_call_claude_allowed_tools_empty(mock_process):
    with patch("pyclaudius.claude.asyncio.create_subprocess_exec", return_value=mock_process) as mock_exec:
        await call_claude(prompt="hi", allowed_tools=[])
        args = mock_exec.call_args[0]
        assert "--allowedTools" not in args


@pytest.mark.asyncio
async def test_call_claude_nonzero_exit_with_stdout():
    proc = AsyncMock()
    proc.returncode = 1
    proc.communicate.return_value = (b"Partial response from Claude", b"tool error")
    with patch("pyclaudius.claude.asyncio.create_subprocess_exec", return_value=proc):
        result, session_id = await call_claude(prompt="search something")
        assert result == "Partial response from Claude"
        assert session_id is not None
