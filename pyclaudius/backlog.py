"""Backlog storage and decorator for saving failed prompts on recoverable errors."""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from functools import wraps
from typing import TYPE_CHECKING, TypedDict, cast

from pyclaudius.opencode_events import OpencodeResult
from pyclaudius.tooling import (
    is_api_error,
    is_auth_error,
    is_empty_response,
    is_rate_limit_error,
)

if TYPE_CHECKING:
    from pathlib import Path

    from pyclaudius.bot_data import BotData

logger = logging.getLogger(__name__)


_AUTH_ERROR = "Authentication error"
_EMPTY_RESPONSE = "opencode returned no output"
_RATE_LIMITED = "Provider rate limit reached"
_API_ERROR = "Provider error"

_BACKLOG_HINT: dict[str, str] = {
    _AUTH_ERROR: "Check TENSORX_API_KEY, then /replaybacklog.",
    _EMPTY_RESPONSE: "Try /replaybacklog later.",
    _RATE_LIMITED: "Try /replaybacklog after the rate limit resets.",
    _API_ERROR: "Try /replaybacklog once the provider recovers.",
}

# Present in every response where the message was re-queued. Callers looping
# over the backlog watch for it so they stop instead of re-queueing everything.
BACKLOG_SAVED_MARKER = "Message saved to backlog"

# Seconds to wait before the single automatic retry.
_RETRY_DELAY_SECONDS = 5


def _classify_failure(
    *, response: str, result: OpencodeResult | None = None
) -> str | None:
    """Identify recoverable failure modes; returns None on success."""
    if result is not None:
        if is_auth_error(result=result):
            return _AUTH_ERROR
        if is_rate_limit_error(result=result):
            return _RATE_LIMITED
        if is_api_error(result=result):
            return _API_ERROR
    if is_empty_response(response=response):
        return _EMPTY_RESPONSE
    return None


def _is_retryable(*, failure: str, result: OpencodeResult | None) -> bool:
    """Decide whether one immediate retry could plausibly succeed.

    An empty response is the shape opencode's occasional dropped-event bug
    takes, so it is always worth one retry. Otherwise the provider itself says
    whether the failure is transient via ``isRetryable``; a bad API key never
    self-heals.
    """
    if failure == _EMPTY_RESPONSE:
        return True
    if failure == _AUTH_ERROR:
        return False
    return bool(result is not None and result.is_retryable)


class BacklogItem(TypedDict):
    prompt: str
    created_at: str


def load_backlog(*, backlog_file: Path) -> list[BacklogItem]:
    """Load backlog items from a JSON file. Returns [] on missing/invalid."""
    try:
        data = json.loads(backlog_file.read_text(encoding="utf-8"))
        if isinstance(data, list):
            return data
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        pass
    return []


def save_backlog(*, backlog_file: Path, items: list[BacklogItem]) -> None:
    """Save backlog items to a JSON file."""
    backlog_file.write_text(json.dumps(items, indent=2), encoding="utf-8")


def format_backlog_list(*, items: list[BacklogItem]) -> str:
    """Format backlog items as a numbered list with timestamps."""
    if not items:
        return "Backlog is empty."
    lines = []
    for i, item in enumerate(items, start=1):
        lines.append(f"{i}. [{item['created_at']}] {item['prompt']}")
    return f"Pending backlog items ({len(items)}):\n\n" + "\n".join(lines)


def _result_from_kwargs(kwargs: dict) -> OpencodeResult | None:
    """Read the parsed result the wrapped call recorded in ``run_info``."""
    run_info = kwargs.get("run_info")
    if isinstance(run_info, dict):
        result = run_info.get("result")
        if isinstance(result, OpencodeResult):
            return result
    return None


def with_backlog(
    func: Callable[..., Awaitable[tuple[str, str | None]]],
) -> Callable[..., Awaitable[tuple[str, str | None]]]:
    """Save the user's original message to a backlog on recoverable failures.

    Failure modes treated as recoverable:
    - Provider authentication errors (HTTP 401/403).
    - Provider rate limits (HTTP 429) — the task was never executed.
    - Any other provider-side error event.
    - An empty response, i.e. opencode exited without producing text.

    Transient failures get one immediate retry (see :func:`_is_retryable`);
    otherwise, and if the retry also fails, the user's original message is
    appended to the backlog and a tailored error message is returned.
    """

    @wraps(func)
    async def wrapper(**kwargs: object) -> tuple[str, str | None]:
        bot_data = cast("BotData | None", kwargs.pop("bot_data", None))
        user_message = kwargs.pop("user_message", None)

        response, session_id = await func(**kwargs)

        if bot_data is None:
            return response, session_id

        settings = bot_data["settings"]
        if not settings.backlog_enabled:
            return response, session_id

        result = _result_from_kwargs(kwargs)
        failure = _classify_failure(response=response, result=result)
        if failure is None:
            return response, session_id

        if _is_retryable(failure=failure, result=result):
            logger.info(f"{failure} — retrying once in {_RETRY_DELAY_SECONDS}s")
            await asyncio.sleep(_RETRY_DELAY_SECONDS)
            response, session_id = await func(**kwargs)
            retry_result = _result_from_kwargs(kwargs)
            if _classify_failure(response=response, result=retry_result) is None:
                logger.info("Retry succeeded")
                return response, session_id
            logger.warning("Retry still failed — saving to backlog")

        if not user_message or not str(user_message).strip():
            return response, session_id

        backlog = bot_data["backlog"]
        backlog.append(
            BacklogItem(
                prompt=str(user_message or ""),
                created_at=datetime.now(tz=UTC).isoformat(),
            )
        )
        bot_data["backlog"] = backlog
        save_backlog(backlog_file=settings.backlog_file, items=backlog)

        count = len(backlog)
        logger.warning(f"{failure} — saved message to backlog ({count} pending)")
        hint = _BACKLOG_HINT[failure]
        return (
            f"{failure}. {BACKLOG_SAVED_MARKER} ({count} pending).\n{hint}",
            None,
        )

    return wrapper
