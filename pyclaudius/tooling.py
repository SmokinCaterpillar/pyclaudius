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

# Env vars that must never be passed to a Claude CLI subprocess.
_SECRET_ENV_VARS: frozenset[str] = frozenset({
    "TELEGRAM_BOT_TOKEN",
    "TELEGRAM_USER_ID",
    "ANTHROPIC_API_KEY",
})


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
    """Attempt to refresh the Claude CLI OAuth token.

    Tries ``claude auth login`` first (pipe-based, no PTY needed).
    Falls back to spawning an interactive PTY session if that fails.

    Returns True if any approach exits with code 0.
    """
    # Use a permissive environment for the refresh — the CLI may need vars
    # like USER, LANG, XDG_*, NODE_*, etc. that _build_subprocess_env strips.
    # Only secrets are removed.
    env = {k: v for k, v in os.environ.items() if k not in _SECRET_ENV_VARS}
    env["TERM"] = "xterm-256color"

    # --- Approach 1: `claude auth login` via pipes (simple, no PTY) ---
    result = await _try_auth_login(
        claude_path=claude_path, cwd=cwd, env=env,
    )
    if result is not None:
        return result

    # --- Approach 2: interactive PTY session ---
    return await _refresh_auth_pty(
        claude_path=claude_path, cwd=cwd, env=env,
    )


async def _try_auth_login(
    *, claude_path: str, cwd: str | None, env: dict[str, str],
) -> bool | None:
    """Try ``claude auth login`` via pipes.

    Returns True/False on success/failure, or None if the subcommand
    does not exist (so the caller can fall back).
    """
    logger.info(f"Trying 'claude auth login' (cwd={cwd})")
    try:
        proc = await asyncio.create_subprocess_exec(
            claude_path, "auth", "login",
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
            cwd=cwd,
        )
        stdout, stderr = await asyncio.wait_for(
            proc.communicate(), timeout=30,
        )
    except FileNotFoundError:
        logger.error(f"Claude CLI not found at {claude_path}")
        return False
    except TimeoutError:
        logger.warning("'claude auth login' timed out after 30s")
        with contextlib.suppress(ProcessLookupError):
            proc.kill()
        return None

    stdout_text = stdout.decode(errors="replace")[:1000]
    stderr_text = stderr.decode(errors="replace")[:1000]
    logger.warning(
        f"'claude auth login' exited {proc.returncode}: "
        f"stdout={stdout_text!r}, stderr={stderr_text!r}"
    )

    # Only return True on success; any failure falls through to PTY.
    if proc.returncode == 0:
        return True
    return None


async def _refresh_auth_pty(
    *,
    claude_path: str,
    cwd: str | None,
    env: dict[str, str],
) -> bool:
    """Spawn Claude interactively via a PTY to trigger an OAuth refresh.

    Falls back to SIGTERM if the TUI cannot be navigated.
    """
    logger.info(f"Trying interactive PTY refresh (cwd={cwd})")

    master_fd, slave_fd = pty.openpty()

    with contextlib.suppress(OSError):
        winsize = struct.pack("HHHH", 24, 80, 0, 0)
        fcntl.ioctl(slave_fd, termios.TIOCSWINSZ, winsize)

    def _setup_ctty() -> None:
        """Make the slave PTY the controlling terminal of the child.

        After start_new_session calls setsid(), the child is a session
        leader without a controlling terminal.  TIOCSCTTY on stdin
        (already dup2'd to the slave fd) makes it the controlling
        terminal so /dev/tty works and the CLI enters interactive mode.
        """
        fcntl.ioctl(0, termios.TIOCSCTTY, 0)

    # All three fds must be the PTY — Node.js checks isTTY on all of
    # stdin, stdout, *and* stderr to decide if it's truly interactive.
    try:
        proc = await asyncio.create_subprocess_exec(
            claude_path,
            stdin=slave_fd,
            stdout=slave_fd,
            stderr=slave_fd,
            env=env,
            cwd=cwd,
            start_new_session=True,
            preexec_fn=_setup_ctty,
        )
    except FileNotFoundError:
        logger.error(f"Claude CLI not found at {claude_path}")
        os.close(master_fd)
        os.close(slave_fd)
        return False

    os.close(slave_fd)

    loop = asyncio.get_running_loop()
    drain_future = loop.run_in_executor(None, _drain_pty_blocking, master_fd)

    async def _pty_write(data: bytes) -> None:
        await loop.run_in_executor(None, os.write, master_fd, data)

    timed_out = False
    try:
        # Wait for CLI to start and (hopefully) refresh the token as a
        # side-effect of initialisation.
        await asyncio.sleep(8)

        # Try to navigate any trust/onboarding dialogs.
        await _pty_write(b"\r")
        await asyncio.sleep(3)
        await _pty_write(b"\r")
        await asyncio.sleep(2)
        await _pty_write(b"\x1b")
        await asyncio.sleep(1)
        await _pty_write(b"/exit\r")
        await asyncio.sleep(3)

        # SIGTERM for graceful shutdown if /exit didn't work.
        if proc.returncode is None:
            logger.info("CLI still running after /exit, sending SIGTERM...")
            with contextlib.suppress(ProcessLookupError):
                proc.send_signal(signal.SIGTERM)

        await asyncio.wait_for(proc.wait(), timeout=15)
    except TimeoutError:
        timed_out = True
        with contextlib.suppress(ProcessLookupError):
            proc.kill()
    finally:
        with contextlib.suppress(OSError):
            os.close(master_fd)

    pty_output = b""
    with contextlib.suppress(Exception):
        pty_output = await drain_future

    pty_text = _strip_ansi(pty_output.decode(errors="replace"))[:2000]
    raw_hex = pty_output[:800].hex(" ")
    stderr_text = ""  # stderr is on the PTY now, captured in pty_output

    if timed_out:
        logger.error(
            f"PTY refresh timed out: pty={pty_text!r}, stderr={stderr_text!r}"
        )
    else:
        logger.info(
            f"PTY refresh exited with code {proc.returncode}: "
            f"pty={pty_text!r}, stderr={stderr_text!r}"
        )
    logger.warning(f"PTY refresh raw hex: {raw_hex}")
    return not timed_out and proc.returncode == 0


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
