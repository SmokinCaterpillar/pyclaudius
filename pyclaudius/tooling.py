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
