import asyncio
import logging

logger = logging.getLogger(__name__)


async def _tmux_send(*, session_name: str, text: str) -> bool:
    """Send text + Enter to a tmux session. Returns True on success."""
    proc = await asyncio.create_subprocess_exec(
        "tmux",
        "send-keys",
        "-t",
        session_name,
        text,
        "Enter",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await proc.communicate()
    if proc.returncode != 0:
        logger.warning(
            f"Tmux send-keys failed for {session_name!r}: {stderr.decode().strip()}"
        )
        return False
    return True


async def send_tmux_keepalive(*, session_name: str) -> None:
    """Send /clear then a keepalive message to a tmux session.

    Two separate send-keys calls with a delay so the CLI has time
    to process /clear before receiving the next input.
    """
    if not await _tmux_send(session_name=session_name, text="/clear"):
        return

    await asyncio.sleep(2)

    if await _tmux_send(session_name=session_name, text="Hello from pyclaudius"):
        logger.info(f"Sent keepalive to tmux session {session_name!r}")
    else:
        logger.warning(f"Tmux keepalive failed for {session_name!r}")
