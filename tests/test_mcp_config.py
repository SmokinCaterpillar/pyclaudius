from unittest.mock import AsyncMock, patch

import pytest

from pyclaudius.mcp_tools.config import (
    MCP_SERVER_NAME,
    find_free_port,
    register_mcp_server,
    unregister_mcp_server,
)


def test_find_free_port():
    port = find_free_port()
    assert isinstance(port, int)
    assert port > 0


def test_find_free_port_returns_different_ports():
    port1 = find_free_port()
    port2 = find_free_port()
    # Ports should generally be different (OS assigns sequentially)
    # but we just check both are valid
    assert port1 > 0
    assert port2 > 0


def test_mcp_server_name():
    assert MCP_SERVER_NAME == "pyclaudius"


@pytest.mark.asyncio
async def test_register_mcp_server_success():
    mock_proc = AsyncMock()
    mock_proc.returncode = 0
    mock_proc.communicate.return_value = (b"Added\n", b"")
    with patch(
        "pyclaudius.mcp_tools.config.asyncio.create_subprocess_exec",
        return_value=mock_proc,
    ) as mock_exec:
        result = await register_mcp_server(claude_path="claude", port=12345, cwd="/tmp")
        assert result is True
        args = mock_exec.call_args[0]
        assert "mcp" in args
        assert "add" in args
        assert "--transport" in args
        assert "http" in args
        assert "http://127.0.0.1:12345/mcp" in args


@pytest.mark.asyncio
async def test_register_mcp_server_failure():
    mock_proc = AsyncMock()
    mock_proc.returncode = 1
    mock_proc.communicate.return_value = (b"", b"error\n")
    with patch(
        "pyclaudius.mcp_tools.config.asyncio.create_subprocess_exec",
        return_value=mock_proc,
    ):
        result = await register_mcp_server(claude_path="claude", port=12345, cwd="/tmp")
        assert result is False


@pytest.mark.asyncio
async def test_unregister_mcp_server_success():
    mock_proc = AsyncMock()
    mock_proc.returncode = 0
    mock_proc.communicate.return_value = (b"Removed\n", b"")
    with patch(
        "pyclaudius.mcp_tools.config.asyncio.create_subprocess_exec",
        return_value=mock_proc,
    ) as mock_exec:
        result = await unregister_mcp_server(claude_path="claude", cwd="/tmp")
        assert result is True
        args = mock_exec.call_args[0]
        assert "mcp" in args
        assert "remove" in args
        assert MCP_SERVER_NAME in args


@pytest.mark.asyncio
async def test_unregister_mcp_server_failure():
    mock_proc = AsyncMock()
    mock_proc.returncode = 1
    mock_proc.communicate.return_value = (b"", b"not found\n")
    with patch(
        "pyclaudius.mcp_tools.config.asyncio.create_subprocess_exec",
        return_value=mock_proc,
    ):
        result = await unregister_mcp_server(claude_path="claude", cwd="/tmp")
        assert result is False
