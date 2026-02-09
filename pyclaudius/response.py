import re

_SILENT_PATTERN = re.compile(r"\[SILENT\]", re.IGNORECASE)


def has_silent_tag(*, text: str) -> bool:
    """Check if text contains [SILENT]."""
    return bool(_SILENT_PATTERN.search(text))


def split_response(*, text: str, max_length: int = 4000) -> list[str]:
    """Split text into chunks for Telegram's message limit.

    Priority: split at paragraph > line > word > hard break.
    """
    if not text:
        return []

    if len(text) <= max_length:
        return [text]

    chunks: list[str] = []
    remaining = text

    while remaining:
        if len(remaining) <= max_length:
            chunks.append(remaining)
            break

        split_at = remaining.rfind("\n\n", 0, max_length)
        if split_at == -1:
            split_at = remaining.rfind("\n", 0, max_length)
        if split_at == -1:
            split_at = remaining.rfind(" ", 0, max_length)
        if split_at == -1:
            split_at = max_length

        chunks.append(remaining[:split_at])
        remaining = remaining[split_at:].lstrip()

    return chunks
