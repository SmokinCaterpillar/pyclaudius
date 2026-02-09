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

    memory_instruction = (
        "If you learn an important fact about the user, include [REMEMBER: fact] in your response. "
        "To correct or remove an outdated fact, include [FORGET: keyword] in your response.\n\n"
        if memory_section is not None
        else ""
    )

    cron_instruction = ""
    if cron_count is not None:
        cron_instruction = (
            f"You have {cron_count} scheduled task(s).\n"
            "To add a recurring cron job: [CRON_ADD: <cron expression> | <prompt>]\n"
            "To schedule a one-time task: [SCHEDULE: <YYYY-MM-DD HH:MM> | <prompt>]\n"
            "To remove a scheduled task by number: [CRON_REMOVE: <number>]\n"
            "To list all scheduled tasks: [CRON_LIST]\n\n"
        )
        if is_scheduled:
            cron_instruction += (
                "This is an automated scheduled task. If there is nothing noteworthy "
                "to report, respond with only [SILENT] to suppress notification to "
                "the user.\n\n"
            )

    return (
        "You are responding via Telegram. Keep responses concise.\n\n"
        f"Current time of your user: {time_str} ({tz_label})\n\n"
        f"{memory_instruction}"
        f"{cron_instruction}"
        f"{memory_section or ''}"
        f"User: {user_message}"
    )
