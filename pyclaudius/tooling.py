import logging
from collections.abc import Awaitable, Callable
from functools import wraps

from telegram import Update
from telegram.ext import ContextTypes

from pyclaudius.opencode_events import OpencodeResult

logger = logging.getLogger(__name__)

HTTP_UNAUTHORIZED = 401
HTTP_FORBIDDEN = 403
HTTP_TOO_MANY_REQUESTS = 429


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


def is_auth_error(*, result: OpencodeResult) -> bool:
    """Check whether an opencode run failed on provider authentication.

    opencode reports provider failures as structured ``error`` events carrying
    an HTTP status, so classification does not depend on the wording of any
    error message. A missing or wrong ``TENSORX_API_KEY`` surfaces as 401.
    """
    if result.status_code in (HTTP_UNAUTHORIZED, HTTP_FORBIDDEN):
        return True
    return "auth" in (result.error_name or "").lower()


def _squash(name: str | None) -> str:
    """Lowercase *name* with separators removed, for tolerant matching."""
    return (name or "").lower().replace("_", "").replace("-", "").replace(" ", "")


def is_rate_limit_error(*, result: OpencodeResult) -> bool:
    """Check whether the provider rate-limited or refused on quota."""
    if result.status_code == HTTP_TOO_MANY_REQUESTS:
        return True
    return "ratelimit" in _squash(result.error_name)


def is_api_error(*, result: OpencodeResult) -> bool:
    """Check whether the run produced any provider-side error event."""
    return result.error_name is not None


def is_empty_response(*, response: str) -> bool:
    """Detect a silent failure: opencode exited cleanly with no text.

    Returns True for empty or whitespace-only strings. A deliberate
    ``[SILENT]`` reply is not empty and is not treated as a failure.
    """
    return not response.strip()
