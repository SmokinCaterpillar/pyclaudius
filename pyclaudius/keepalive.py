import asyncio
import logging

logger = logging.getLogger(__name__)


async def send_tmux_keepalive(*, session_name: str) -> None:
    """Send a keepalive keystroke to a tmux session to prevent auth expiry."""
    proc = await asyncio.create_subprocess_exec(
        "tmux",
        "send-keys",
        "-t",
        session_name,
        "/clear",
        "Enter",
        "Hello from pyclaudius",
        "Enter",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await proc.communicate()
    if proc.returncode != 0:
        logger.warning(
            f"Tmux keepalive failed for {session_name!r}: {stderr.decode().strip()}"
        )
    else:
        logger.info(f"Sent keepalive to tmux session {session_name!r}")
