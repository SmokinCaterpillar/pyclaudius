from datetime import UTC, datetime


def build_prompt(*, user_message: str) -> str:
    """Build the full prompt with system context for Claude."""
    now = datetime.now(tz=UTC).astimezone()
    time_str = now.strftime("%A, %B %d, %Y, %I:%M %p")

    return (
        "You are responding via Telegram. Keep responses concise.\n\n"
        f"Current time: {time_str}\n\n"
        f"User: {user_message}"
    )
