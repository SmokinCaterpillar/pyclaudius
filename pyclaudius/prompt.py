from datetime import UTC, datetime


def build_prompt(*, user_message: str, memory_section: str | None = None) -> str:
    """Build the full prompt with system context for Claude."""
    now = datetime.now(tz=UTC).astimezone()
    time_str = now.strftime("%A, %B %d, %Y, %I:%M %p")

    memory_instruction = (
        "If you learn an important fact about the user, include [REMEMBER: fact] in your response.\n\n"
        if memory_section is not None
        else ""
    )

    return (
        "You are responding via Telegram. Keep responses concise.\n\n"
        f"Current time: {time_str}\n\n"
        f"{memory_instruction}"
        f"{memory_section or ''}"
        f"User: {user_message}"
    )
