import json
from datetime import UTC, datetime
from pathlib import Path

from pyclaudius.opencode import is_resumable_session


def load_session(*, session_file: Path) -> dict:
    """Load session state from JSON file. Returns defaults if missing.

    A stored id that opencode could not resume — notably a uuid written by a
    pre-opencode version of pyclaudius — is dropped so the next message simply
    starts a fresh session instead of failing on ``--session``.
    """
    try:
        data = json.loads(session_file.read_text())
        session_id = data.get("session_id")
        if not is_resumable_session(session_id=session_id):
            session_id = None
        return {
            "session_id": session_id,
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
