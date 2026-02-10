import asyncio
import contextlib
import logging
import os
import pty
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


async def refresh_auth(
    *, claude_path: str = "claude", cwd: str | None = None
) -> bool:
    """Spawn Claude interactively via a PTY to trigger an OAuth token refresh.

    The Claude CLI (Ink-based) requires a real TTY on **both** stdin and
    stdout to enter interactive mode.  We allocate a pseudo-terminal for
    stdin and stdout so the CLI detects a TTY, wait for the startup/auth
    handshake, then send ``/exit`` to quit cleanly.

    stderr is kept as a pipe so we can capture error messages for logging.

    Returns True if the process exits with code 0.
    """
    from pyclaudius.claude import _build_subprocess_env

    logger.info(f"Attempting OAuth token refresh via {claude_path} (cwd={cwd})")

    # Create a PTY pair so the CLI sees a real terminal on stdin + stdout.
    master_fd, slave_fd = pty.openpty()
    try:
        proc = await asyncio.create_subprocess_exec(
            claude_path,
            stdin=slave_fd,
            stdout=slave_fd,
            stderr=asyncio.subprocess.PIPE,
            env=_build_subprocess_env(),
            cwd=cwd,
        )
    except FileNotFoundError:
        logger.error(f"Claude CLI not found at {claude_path}")
        os.close(master_fd)
        os.close(slave_fd)
        return False

    # Close slave in parent — the child process owns it now.
    os.close(slave_fd)

    try:
        # Give the CLI time to start up, handle trust/onboarding screens,
        # and silently refresh the OAuth token.
        await asyncio.sleep(5)

        # Send newlines to dismiss any prompts, then /exit to quit.
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, os.write, master_fd, b"\n\n/exit\n")

        # communicate() reads stderr (PIPE) and waits for exit.
        # stdout is on the PTY so communicate() returns None for it.
        _stdout, stderr = await asyncio.wait_for(
            proc.communicate(), timeout=30
        )
    except TimeoutError:
        logger.error("Token refresh timed out after 30 seconds")
        with contextlib.suppress(ProcessLookupError):
            proc.kill()
        return False
    finally:
        with contextlib.suppress(OSError):
            os.close(master_fd)

    stderr_text = (stderr or b"").decode(errors="replace")[:500]
    logger.info(
        f"Token refresh exited with code {proc.returncode}: "
        f"stderr={stderr_text!r}"
    )
    return proc.returncode == 0


def with_auth_retry(
    func: Callable[..., Awaitable[tuple[str, str | None]]],
) -> Callable[..., Awaitable[tuple[str, str | None]]]:
    """Retry *func* once after refreshing the OAuth token on auth errors."""

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
                response, session_id = await func(**kwargs)
            else:
                logger.error("Token refresh failed")
        return response, session_id

    return wrapper
