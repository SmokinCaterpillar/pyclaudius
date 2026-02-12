"""Backlog storage and decorator for saving failed prompts on auth errors."""

import json
import logging
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from functools import wraps
from pathlib import Path
from typing import TypedDict

from pyclaudius.tooling import is_auth_error

logger = logging.getLogger(__name__)


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


def with_backlog(
    func: Callable[..., Awaitable[tuple[str, str | None]]],
) -> Callable[..., Awaitable[tuple[str, str | None]]]:
    """Save the user's original message to a backlog on auth errors."""

    @wraps(func)
    async def wrapper(**kwargs: object) -> tuple[str, str | None]:
        bot_data = kwargs.pop("bot_data", None)
        user_message = kwargs.pop("user_message", None)

        response, session_id = await func(**kwargs)

        if bot_data is None:
            return response, session_id

        from pyclaudius.config import Settings

        settings: Settings = bot_data["settings"]  # type: ignore[index]
        if not settings.backlog_enabled:
            return response, session_id

        if not is_auth_error(response=response):
            return response, session_id

        if not user_message or not str(user_message).strip():
            return response, session_id

        backlog: list[BacklogItem] = bot_data.get("backlog", [])  # type: ignore[union-attr]
        backlog.append(
            BacklogItem(
                prompt=str(user_message or ""),
                created_at=datetime.now(tz=UTC).isoformat(),
            )
        )
        bot_data["backlog"] = backlog  # type: ignore[index]
        save_backlog(backlog_file=settings.backlog_file, items=backlog)

        count = len(backlog)
        logger.warning(f"Auth error — saved message to backlog ({count} pending)")
        return (
            f"Authentication error. Message saved to backlog ({count} pending).\n"
            "Re-authenticate with 'claude auth login', then /replaybacklog.",
            None,
        )

    return wrapper
