from datetime import UTC, datetime

from pyclaudius.timezone import get_zoneinfo


def build_prompt(
    *,
    user_message: str,
    memory_section: str | None = None,
    cron_count: int | None = None,
    is_scheduled: bool = False,
    timezone: str | None = None,
) -> str:
    """Build the full prompt with system context for Claude."""
    tz = get_zoneinfo(timezone=timezone)
    now = datetime.now(tz=UTC).astimezone(tz)
    tz_label = timezone or "UTC"
    time_str = now.strftime("%A, %B %d, %Y, %I:%M %p")

    memory_hint = ""
    if memory_section is not None:
        memory_hint = "Use the remember_fact and forget_memory tools to manage facts about the user.\n\n"

    cron_hint = ""
    if cron_count is not None:
        cron_hint = (
            f"You have {cron_count} scheduled task(s). "
            "Use cron tools to manage them.\n\n"
        )
        if is_scheduled:
            cron_hint += (
                "This is an automated scheduled task. If there is nothing noteworthy "
                "to report, respond with only [SILENT] to suppress notification to "
                "the user.\n\n"
            )

    return (
        "You are responding via Telegram. Keep responses concise.\n\n"
        f"Current time of your user: {time_str} ({tz_label})\n\n"
        f"{memory_hint}"
        f"{cron_hint}"
        f"{memory_section or ''}"
        f"User: {user_message}"
    )
