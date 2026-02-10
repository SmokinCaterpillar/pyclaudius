import asyncio
import contextlib
import logging
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
    """Spawn Claude interactively to trigger an OAuth token refresh.

    Waits a few seconds for the CLI to start up and refresh the token,
    then sends newlines (to dismiss any trust/onboarding screens) followed
    by ``/exit`` to terminate the session.
    Returns True if the process exits with code 0.
    """
    from pyclaudius.claude import _build_subprocess_env

    logger.info(f"Attempting OAuth token refresh via {claude_path} (cwd={cwd})")
    try:
        proc = await asyncio.create_subprocess_exec(
            claude_path,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=_build_subprocess_env(),
            cwd=cwd,
        )
    except FileNotFoundError:
        logger.error(f"Claude CLI not found at {claude_path}")
        return False

    try:
        # Give the CLI time to start up, handle trust screens, and refresh
        # the OAuth token before we send the exit command.
        await asyncio.sleep(5)
        stdout, stderr = await asyncio.wait_for(
            proc.communicate(input=b"\n\n/exit\n"), timeout=30
        )
    except TimeoutError:
        logger.error("Token refresh timed out after 30 seconds")
        with contextlib.suppress(ProcessLookupError):
            proc.kill()
        return False

    stdout_text = stdout.decode()[:200]
    stderr_text = stderr.decode()[:200]
    logger.info(
        f"Token refresh exited with code {proc.returncode}: "
        f"stdout={stdout_text!r}, stderr={stderr_text!r}"
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
