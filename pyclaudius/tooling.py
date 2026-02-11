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


def with_auth_retry(
    func: Callable[..., Awaitable[tuple[str, str | None]]],
) -> Callable[..., Awaitable[tuple[str, str | None]]]:
    """Retry *func* once after an interactive OAuth login on auth errors.

    Pops ``auto_refresh_auth``, ``auth_send_message``, and
    ``auth_wait_for_reply`` from *kwargs* before forwarding to *func*.

    When callbacks are provided and an auth error is detected, spawns
    ``interactive_login`` (from ``pyclaudius.login``) and retries on success.
    Without callbacks the auth error response is returned as-is.
    """

    @wraps(func)
    async def wrapper(**kwargs: object) -> tuple[str, str | None]:
        auto_refresh: bool = bool(kwargs.pop("auto_refresh_auth", False))
        send_message = kwargs.pop("auth_send_message", None)
        wait_for_reply = kwargs.pop("auth_wait_for_reply", None)

        response, session_id = await func(**kwargs)

        if not auto_refresh or not is_auth_error(response=response):
            return response, session_id

        if send_message is None or wait_for_reply is None:
            logger.warning("Auth error detected but no auth callbacks provided")
            return response, session_id

        logger.warning("Auth error detected, starting interactive login...")

        from pyclaudius.login import interactive_login

        refreshed = await interactive_login(
            claude_path=str(kwargs.get("claude_path", "claude")),
            cwd=str(kwargs["cwd"]) if kwargs.get("cwd") else None,
            send_message=send_message,
            wait_for_reply=wait_for_reply,
        )

        if refreshed:
            logger.info("Interactive login succeeded, retrying...")
            response, session_id = await func(**kwargs)
        else:
            logger.warning("Interactive login failed, returning original error")

        return response, session_id

    return wrapper
