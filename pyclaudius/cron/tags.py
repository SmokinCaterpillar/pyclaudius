import re

_CRON_ADD_PATTERN = re.compile(r"\[CRON_ADD:\s*([^\]]+)\]", re.IGNORECASE)
_SCHEDULE_PATTERN = re.compile(r"\[SCHEDULE:\s*([^\]]+)\]", re.IGNORECASE)
_CRON_REMOVE_PATTERN = re.compile(r"\[CRON_REMOVE:\s*([^\]]+)\]", re.IGNORECASE)
_CRON_LIST_PATTERN = re.compile(r"\[CRON_LIST\]", re.IGNORECASE)
_SILENT_PATTERN = re.compile(r"\[SILENT\]", re.IGNORECASE)


def extract_cron_add_tags(*, text: str) -> list[str]:
    """Extract [CRON_ADD: ...] values from text."""
    return [match.strip() for match in _CRON_ADD_PATTERN.findall(text)]


def extract_schedule_tags(*, text: str) -> list[str]:
    """Extract [SCHEDULE: ...] values from text."""
    return [match.strip() for match in _SCHEDULE_PATTERN.findall(text)]


def extract_cron_remove_tags(*, text: str) -> list[int]:
    """Extract [CRON_REMOVE: N] indices (1-based) from text."""
    results: list[int] = []
    for match in _CRON_REMOVE_PATTERN.findall(text):
        stripped = match.strip()
        if stripped.isdigit():
            results.append(int(stripped))
    return results


def has_cron_list_tag(*, text: str) -> bool:
    """Check if text contains [CRON_LIST]."""
    return bool(_CRON_LIST_PATTERN.search(text))


def has_silent_tag(*, text: str) -> bool:
    """Check if text contains [SILENT]."""
    return bool(_SILENT_PATTERN.search(text))


def strip_cron_tags(*, text: str) -> str:
    """Remove all cron-related tags from text."""
    text = _CRON_ADD_PATTERN.sub("", text)
    text = _SCHEDULE_PATTERN.sub("", text)
    text = _CRON_REMOVE_PATTERN.sub("", text)
    text = _CRON_LIST_PATTERN.sub("", text)
    text = _SILENT_PATTERN.sub("", text)
    return text.strip()


def parse_cron_add_value(*, value: str) -> tuple[str, str] | None:
    """Split 'expression | prompt' on pipe. Returns (expression, prompt) or None."""
    if "|" not in value:
        return None
    expression, prompt = value.split("|", maxsplit=1)
    expression = expression.strip()
    prompt = prompt.strip()
    if not expression or not prompt:
        return None
    return expression, prompt


def parse_schedule_value(*, value: str) -> tuple[str, str] | None:
    """Split 'datetime | prompt' on pipe. Returns (datetime_str, prompt) or None."""
    if "|" not in value:
        return None
    datetime_str, prompt = value.split("|", maxsplit=1)
    datetime_str = datetime_str.strip()
    prompt = prompt.strip()
    if not datetime_str or not prompt:
        return None
    return datetime_str, prompt
