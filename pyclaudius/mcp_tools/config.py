import asyncio
import logging
import socket

logger = logging.getLogger(__name__)

MCP_SERVER_NAME = "pyclaudius"


def find_free_port() -> int:
    """Bind to port 0 and return the OS-assigned free port."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


async def register_mcp_server(*, claude_path: str, port: int) -> bool:
    """Register the MCP server with Claude CLI via ``claude mcp add``.

    Uses ``--scope user`` so the server is available in all sessions.
    Overwrites any existing entry with the same name.
    """
    proc = await asyncio.create_subprocess_exec(
        claude_path,
        "mcp",
        "add",
        "--transport",
        "http",
        "--scope",
        "user",
        MCP_SERVER_NAME,
        f"http://127.0.0.1:{port}/mcp",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    _stdout, stderr = await proc.communicate()
    if proc.returncode != 0:
        logger.error(f"Failed to register MCP server: {stderr.decode().strip()}")
    return proc.returncode == 0


async def unregister_mcp_server(*, claude_path: str) -> bool:
    """Remove the MCP server from Claude CLI config."""
    proc = await asyncio.create_subprocess_exec(
        claude_path,
        "mcp",
        "remove",
        "--scope",
        "user",
        MCP_SERVER_NAME,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    _stdout, stderr = await proc.communicate()
    if proc.returncode != 0:
        logger.warning(f"Failed to unregister MCP server: {stderr.decode().strip()}")
    return proc.returncode == 0
