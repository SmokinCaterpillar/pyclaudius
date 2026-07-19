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


def is_session_limit_error(*, response: str) -> bool:
    """Check if a response indicates the Claude plan/session usage limit was hit."""
    return "You've hit your session limit" in response


def is_usage_credits_error(*, response: str) -> bool:
    """Check if a response indicates 1M-context usage credits are required.

    Claude subscription plans gate the 1M-token context window (the
    default on models like Sonnet 4.6+) behind a separate "usage credits"
    balance. This is a billing-account state, not something a retry fixes.
    """
    return "Usage credits required" in response


def is_empty_response(*, response: str) -> bool:
    """Detect a silent ``claude -p`` failure: rc=0 with no output.

    Returns True for empty or whitespace-only strings. A deliberate
    ``[SILENT]`` reply is not empty and is not treated as a failure.
    """
    return not response.strip()
