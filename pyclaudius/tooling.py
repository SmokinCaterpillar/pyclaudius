import asyncio
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


async def refresh_auth(*, claude_path: str = "claude") -> bool:
    """Spawn Claude interactively to trigger an OAuth token refresh.

    Pipes ``/exit`` to stdin so the process closes immediately.
    Returns True if the process exits with code 0.
    """
    try:
        from pyclaudius.claude import _build_subprocess_env

        proc = await asyncio.create_subprocess_exec(
            claude_path,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=_build_subprocess_env(),
        )
        await asyncio.wait_for(proc.communicate(input=b"/exit\n"), timeout=30)
        return proc.returncode == 0
    except TimeoutError:
        logger.error("Token refresh timed out")
        return False


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
            )
            if refreshed:
                logger.info("Token refreshed successfully, retrying...")
                response, session_id = await func(**kwargs)
            else:
                logger.error("Token refresh failed")
        return response, session_id

    return wrapper
