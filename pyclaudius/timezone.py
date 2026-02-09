import json
import logging
from pathlib import Path
from zoneinfo import ZoneInfo, available_timezones

logger = logging.getLogger(__name__)


def load_timezone(*, timezone_file: Path) -> str | None:
    """Load timezone from a JSON file. Returns None if missing/invalid."""
    try:
        data = json.loads(timezone_file.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            return data.get("timezone")
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        pass
    return None


def save_timezone(*, timezone_file: Path, timezone: str | None) -> None:
    """Save timezone to a JSON file."""
    timezone_file.write_text(
        json.dumps({"timezone": timezone}, indent=2), encoding="utf-8"
    )


def get_zoneinfo(*, timezone: str | None) -> ZoneInfo:
    """Return a ZoneInfo for the given timezone string, falling back to UTC."""
    if timezone is None:
        return ZoneInfo("UTC")
    try:
        return ZoneInfo(timezone)
    except (KeyError, ValueError):
        logger.warning(f"Invalid timezone {timezone!r}, falling back to UTC")
        return ZoneInfo("UTC")


def find_timezones(*, query: str) -> list[str]:
    """Fuzzy-match a query against available IANA timezones.

    Priority: exact full match > city component match > substring match.
    """
    if not query:
        return []

    normalized = query.lower().replace(" ", "_")
    all_zones = sorted(available_timezones())

    # 1. Exact full match (case-insensitive)
    exact = [tz for tz in all_zones if tz.lower() == normalized]
    if exact:
        return exact

    # 2. City component match — last segment after '/'
    city_matches = [
        tz for tz in all_zones if tz.rsplit("/", maxsplit=1)[-1].lower() == normalized
    ]
    if city_matches:
        return city_matches

    # 3. Substring match anywhere in full key
    substring_matches = [tz for tz in all_zones if normalized in tz.lower()]
    return substring_matches
