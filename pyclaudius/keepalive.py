import asyncio
import logging

logger = logging.getLogger(__name__)


def is_trust_dialog(*, screen: str) -> bool:
    """Return True if the pane shows Claude's folder trust dialog.

    Both phrases are required so a chat message that merely mentions
    trusting a folder does not match.
    """
    text = screen.lower()
    return "trust this folder" in text and "no, exit" in text


async def _tmux_capture(*, session_name: str) -> str | None:
    """Return the visible text of a tmux session's pane, or None on failure."""
    proc = await asyncio.create_subprocess_exec(
        "tmux",
        "capture-pane",
        "-p",
        "-t",
        session_name,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()
    if proc.returncode != 0:
        logger.warning(
            f"Tmux capture-pane failed for {session_name!r}: {stderr.decode().strip()}"
        )
        return None
    return stdout.decode(errors="replace")


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

    Checks the pane first: in Claude's folder trust dialog the default
    choice is "No, exit", so our Enter would quit claude instead of
    reaching it. Two separate send-keys calls with a delay so the CLI
    has time to process /clear before receiving the next input.
    """
    screen = await _tmux_capture(session_name=session_name)
    if screen is None:
        logger.warning(f"Tmux keepalive failed for {session_name!r}")
        return

    if is_trust_dialog(screen=screen):
        logger.error(
            f"Claude in tmux session {session_name!r} shows the folder trust "
            f"dialog; not sending keepalive. Attach with 'tmux attach -t "
            f"{session_name}' and choose 'Yes, I trust this folder' once."
        )
        return

    if not await _tmux_send(session_name=session_name, text="/clear"):
        return

    await asyncio.sleep(2)

    if await _tmux_send(session_name=session_name, text="Hello from pyclaudius"):
        logger.info(f"Sent keepalive to tmux session {session_name!r}")
    else:
        logger.warning(f"Tmux keepalive failed for {session_name!r}")
