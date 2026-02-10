import asyncio
import contextlib
import fcntl
import logging
import os
import pty
import re
import signal
import struct
import termios
from collections.abc import Awaitable, Callable
from functools import wraps

from telegram import Update
from telegram.ext import ContextTypes

logger = logging.getLogger(__name__)


def check_authorized(user_id: int, *, allowed_user_id: str) -> bool:
    """Check if a Telegram user ID is authorized."""
    return str(user_id) == allowed_user_id


def authorized(
    func: Callable[[Update, ContextTypes.DEFAULT_TYPE], Awaitable[None]],
) -> Callable[[Update, ContextTypes.DEFAULT_TYPE], Awaitable[None]]:
    """Reject unauthorized users with 'This bot is private.'."""

    @wraps(func)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not update.effective_user or not update.message:
            return
        settings = context.bot_data["settings"]
        if not check_authorized(
            update.effective_user.id, allowed_user_id=settings.telegram_user_id
        ):
            await update.message.reply_text("This bot is private.")
            return
        await func(update, context)

    return wrapper


_AUTH_ERROR_MARKERS: tuple[str, ...] = (
    "authentication_error",
    "OAuth token has expired",
    "API Error: 401",
)


def is_auth_error(*, response: str) -> bool:
    """Check if a response contains authentication error indicators."""
    return any(marker in response for marker in _AUTH_ERROR_MARKERS)


_ANSI_RE = re.compile(
    r"\x1b\[[0-9;?]*[A-Za-z]"       # CSI sequences (e.g. colors, cursor)
    r"|\x1b\[<[0-9;]*[A-Za-z]"      # Kitty keyboard protocol (e.g. \x1b[<u)
    r"|\x1b\].*?\x07"               # OSC sequences
    r"|\x1b[()][A-Z0-9]"            # Character set selection
)


def _strip_ansi(text: str) -> str:
    """Remove ANSI escape sequences and collapse whitespace."""
    cleaned = _ANSI_RE.sub("", text)
    # Collapse runs of whitespace but keep newlines visible.
    cleaned = re.sub(r"[^\S\n]+", " ", cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.strip()


def _drain_pty_blocking(fd: int) -> bytes:
    """Read from a PTY master until EOF/error (runs in a thread)."""
    chunks: list[bytes] = []
    while True:
        try:
            data = os.read(fd, 4096)
            if not data:
                break
            chunks.append(data)
        except OSError:
            break
    return b"".join(chunks)


async def refresh_auth(
    *, claude_path: str = "claude", cwd: str | None = None
) -> bool:
    """Spawn Claude interactively via a PTY to trigger an OAuth token refresh.

    The Claude CLI (Ink-based) requires a real TTY on **both** stdin and
    stdout to enter interactive mode.  We allocate a pseudo-terminal for
    stdin and stdout so the CLI detects a TTY, wait for the startup/auth
    handshake, then send ``/exit`` to quit cleanly.

    A background thread continuously drains the PTY master to prevent the
    Ink-rendered terminal output from filling the PTY buffer and blocking
    the child process.

    stderr is kept as a pipe so we can capture error messages for logging.

    Returns True if the process exits with code 0.
    """
    from pyclaudius.claude import _build_subprocess_env

    logger.info(f"Attempting OAuth token refresh via {claude_path} (cwd={cwd})")

    # Create a PTY pair so the CLI sees a real terminal on stdin + stdout.
    master_fd, slave_fd = pty.openpty()

    # Set a reasonable terminal size — Ink requires dimensions to render.
    with contextlib.suppress(OSError):
        winsize = struct.pack("HHHH", 24, 80, 0, 0)
        fcntl.ioctl(slave_fd, termios.TIOCSWINSZ, winsize)

    # The Ink-based CLI needs TERM to operate correctly in a PTY.
    env = _build_subprocess_env()
    env["TERM"] = "xterm-256color"

    try:
        proc = await asyncio.create_subprocess_exec(
            claude_path,
            stdin=slave_fd,
            stdout=slave_fd,
            stderr=asyncio.subprocess.PIPE,
            env=env,
            cwd=cwd,
        )
    except FileNotFoundError:
        logger.error(f"Claude CLI not found at {claude_path}")
        os.close(master_fd)
        os.close(slave_fd)
        return False

    # Close slave in parent — the child process owns it now.
    os.close(slave_fd)

    # Drain the PTY master in a background thread so the Ink-rendered
    # terminal UI doesn't fill the PTY buffer and block the child.
    loop = asyncio.get_running_loop()
    drain_future = loop.run_in_executor(None, _drain_pty_blocking, master_fd)

    async def _pty_write(data: bytes) -> None:
        await loop.run_in_executor(None, os.write, master_fd, data)

    stderr: bytes | None = None
    timed_out = False
    try:
        # Give the CLI time to start up and show trust/onboarding screens.
        await asyncio.sleep(5)

        # Ink uses raw mode — Enter is \r, not \n.
        # Stage 1: Press Enter to confirm "Yes, I trust this folder".
        await _pty_write(b"\r")
        # Stage 2: Wait for potential onboarding/consent screens.
        await asyncio.sleep(3)
        # Stage 3: Press Enter again to dismiss any follow-up dialogs.
        await _pty_write(b"\r")
        await asyncio.sleep(2)
        # Stage 4: Escape to clear any modal state, then /exit.
        await _pty_write(b"\x1b")
        await asyncio.sleep(1)
        await _pty_write(b"/exit\r")
        await asyncio.sleep(3)

        # Stage 5: SIGTERM for graceful shutdown if /exit didn't work.
        if proc.returncode is None:
            logger.info("CLI still running after /exit, sending SIGTERM...")
            with contextlib.suppress(ProcessLookupError):
                proc.send_signal(signal.SIGTERM)

        # communicate() reads stderr (PIPE) and waits for exit.
        _stdout, stderr = await asyncio.wait_for(
            proc.communicate(), timeout=20
        )
    except TimeoutError:
        timed_out = True
        with contextlib.suppress(ProcessLookupError):
            proc.kill()
    finally:
        # Close master fd — unblocks the drain thread (EIO on read).
        with contextlib.suppress(OSError):
            os.close(master_fd)

    # Wait for drain thread to finish and collect PTY output for logging.
    pty_output = b""
    with contextlib.suppress(Exception):
        pty_output = await drain_future

    pty_text = _strip_ansi(pty_output.decode(errors="replace"))[:2000]
    # Log raw bytes so we can debug what the Ink TUI is actually rendering.
    raw_hex = pty_output[:800].hex(" ")
    stderr_text = (stderr or b"").decode(errors="replace")[:500]

    if timed_out:
        logger.error(
            f"Token refresh timed out: "
            f"pty={pty_text!r}, stderr={stderr_text!r}"
        )
        logger.warning(f"Token refresh raw PTY hex: {raw_hex}")
        return False

    logger.info(
        f"Token refresh exited with code {proc.returncode}: "
        f"pty={pty_text!r}, stderr={stderr_text!r}"
    )
    logger.debug(f"Token refresh raw PTY hex: {raw_hex}")
    return proc.returncode == 0


def with_auth_retry(
    func: Callable[..., Awaitable[tuple[str, str | None]]],
) -> Callable[..., Awaitable[tuple[str, str | None]]]:
    """Retry *func* once after refreshing the OAuth token on auth errors.

    Always retries after the refresh attempt, even if ``refresh_auth``
    reported failure.  The interactive CLI may refresh the token as a
    side-effect (e.g. before showing a trust dialog) and then time out
    on a subsequent screen.  Retrying catches that case.
    """

    @wraps(func)
    async def wrapper(**kwargs: object) -> tuple[str, str | None]:
        auto_refresh = kwargs.pop("auto_refresh_auth", False)
        response, session_id = await func(**kwargs)
        if auto_refresh and is_auth_error(response=response):
            logger.warning("Auth error detected, attempting token refresh...")
            refreshed = await refresh_auth(
                claude_path=str(kwargs.get("claude_path", "claude")),
                cwd=str(kwargs["cwd"]) if kwargs.get("cwd") else None,
            )
            if refreshed:
                logger.info("Token refreshed successfully, retrying...")
            else:
                logger.warning(
                    "Token refresh exited unsuccessfully, "
                    "retrying anyway (token may have been refreshed as side-effect)..."
                )
            response, session_id = await func(**kwargs)
        return response, session_id

    return wrapper
