"""Interactive OAuth login via Claude REPL.

Spawns the Claude CLI in REPL mode (inside ``script(1)`` for PTY support),
sends ``/login``, captures the OAuth URL from output, relays it to the user
via callbacks, waits for the auth code reply, and feeds it back into the REPL.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import re
import signal
from collections.abc import Awaitable, Callable

from pyclaudius.claude import _build_subprocess_env

logger = logging.getLogger(__name__)

_ANSI_RE = re.compile(
    r"\x1b\[[0-9;?]*[A-Za-z]"       # CSI sequences (e.g. colors, cursor)
    r"|\x1b\[<[0-9;]*[A-Za-z]"      # Kitty keyboard protocol (e.g. \x1b[<u)
    r"|\x1b\].*?\x07"               # OSC sequences
    r"|\x1b[()][A-Z0-9]"            # Character set selection
)

_URL_RE = re.compile(r"https://[^\s\"'<>]+")


def _strip_ansi(text: str) -> str:
    """Remove ANSI escape sequences and collapse whitespace."""
    cleaned = _ANSI_RE.sub("", text)
    cleaned = re.sub(r"[^\S\n]+", " ", cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.strip()


async def _read_until(
    *,
    stream: asyncio.StreamReader,
    pattern: re.Pattern[str],
    timeout: float = 60.0,
) -> str | None:
    """Incrementally read from *stream*, strip ANSI, return first *pattern* match.

    Returns ``None`` if *timeout* expires before a match is found.
    """
    buf = ""
    try:
        async with asyncio.timeout(timeout):
            while True:
                chunk = await stream.read(4096)
                if not chunk:
                    break
                buf += _strip_ansi(chunk.decode(errors="replace"))
                match = pattern.search(buf)
                if match:
                    return match.group(0)
    except TimeoutError:
        logger.warning(f"_read_until timed out after {timeout}s, buffer: {buf[:500]!r}")
    return None


async def interactive_login(
    *,
    claude_path: str = "claude",
    cwd: str | None = None,
    send_message: Callable[[str], Awaitable[None]],
    wait_for_reply: Callable[[], Awaitable[str]],
    timeout: float = 300.0,
) -> bool:
    """Run an interactive OAuth login flow via the Claude REPL.

    Spawns ``script -qec claude /dev/null`` (PTY required for the REPL),
    sends ``/login``, captures the OAuth URL, relays it to the user via
    *send_message*, waits for the auth code via *wait_for_reply*, and
    feeds it back into the REPL.

    Returns ``True`` on success, ``False`` on any failure.
    """
    env = _build_subprocess_env()
    env["TERM"] = "xterm-256color"

    try:
        proc = await asyncio.create_subprocess_exec(
            "script", "-qec", claude_path, "/dev/null",
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            env=env,
            cwd=cwd,
        )
    except FileNotFoundError:
        logger.error(f"'script' or Claude CLI not found (claude_path={claude_path})")
        await send_message("Login failed: Claude CLI not found.")
        return False

    try:
        return await _drive_repl(
            proc=proc,
            send_message=send_message,
            wait_for_reply=wait_for_reply,
            timeout=timeout,
        )
    finally:
        await _cleanup_proc(proc=proc)


async def _drive_repl(
    *,
    proc: asyncio.subprocess.Process,
    send_message: Callable[[str], Awaitable[None]],
    wait_for_reply: Callable[[], Awaitable[str]],
    timeout: float,
) -> bool:
    """Drive the REPL through the /login flow. Returns True on success."""
    # Wait for REPL startup.
    await asyncio.sleep(5)

    # Send /login command.
    proc.stdin.write(b"/login\r")
    await proc.stdin.drain()
    logger.info("Sent /login to REPL, waiting for URL...")

    # Wait for URL in output.
    url = await _read_until(
        stream=proc.stdout,
        pattern=_URL_RE,
        timeout=60.0,
    )

    if not url:
        logger.error("No OAuth URL found in REPL output")
        await send_message("Login failed: no OAuth URL found in CLI output.")
        return False

    logger.info(f"Found OAuth URL: {url[:80]}...")
    await send_message(f"Please visit this URL to log in:\n{url}")

    # Wait for user to reply with auth code.
    try:
        auth_code = await asyncio.wait_for(
            wait_for_reply(),
            timeout=timeout,
        )
    except TimeoutError:
        logger.error(f"Timed out waiting for auth code after {timeout}s")
        await send_message("Login timed out waiting for the auth code.")
        return False

    # Send auth code to REPL.
    proc.stdin.write(f"{auth_code.strip()}\r".encode())
    await proc.stdin.drain()
    logger.info("Sent auth code to REPL, waiting for completion...")

    # Give the CLI time to process the code.
    await asyncio.sleep(5)
    return True


async def _cleanup_proc(*, proc: asyncio.subprocess.Process) -> None:
    """Gracefully terminate the REPL subprocess."""
    if proc.returncode is not None:
        return

    # Try /exit first.
    with contextlib.suppress(OSError):
        proc.stdin.write(b"\x1b/exit\r")
        await proc.stdin.drain()

    # Give it a moment to exit.
    with contextlib.suppress(TimeoutError):
        await asyncio.wait_for(proc.wait(), timeout=5)

    # SIGTERM if still running.
    if proc.returncode is None:
        with contextlib.suppress(ProcessLookupError):
            proc.send_signal(signal.SIGTERM)
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(proc.wait(), timeout=5)

    # SIGKILL as last resort.
    if proc.returncode is None:
        with contextlib.suppress(ProcessLookupError):
            proc.kill()
