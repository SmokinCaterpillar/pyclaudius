import json
import re
from datetime import UTC, datetime
from pathlib import Path


def load_session(*, session_file: Path) -> dict:
    """Load session state from JSON file. Returns defaults if missing."""
    try:
        data = json.loads(session_file.read_text())
        return {
            "session_id": data.get("session_id"),
            "last_activity": data.get("last_activity", ""),
        }
    except (FileNotFoundError, json.JSONDecodeError):
        return {"session_id": None, "last_activity": ""}


def save_session(
    *,
    session_file: Path,
    session_id: str | None,
    last_activity: str | None = None,
) -> None:
    """Save session state to JSON file."""
    if last_activity is None:
        last_activity = datetime.now(tz=UTC).isoformat()
    session_file.parent.mkdir(parents=True, exist_ok=True)
    session_file.write_text(
        json.dumps(
            {"session_id": session_id, "last_activity": last_activity},
            indent=2,
        )
    )


def extract_session_id(*, output: str) -> str | None:
    """Extract session ID from Claude CLI output."""
    match = re.search(r"Session ID: ([a-f0-9-]+)", output, re.IGNORECASE)
    return match.group(1) if match else None
