import json

from pyclaudius.session import load_session, save_session


def test_load_session_missing_file(tmp_path):
    result = load_session(session_file=tmp_path / "nonexistent.json")
    assert result == {"session_id": None, "last_activity": ""}


def test_save_and_load_session(tmp_path):
    session_file = tmp_path / "session.json"
    save_session(
        session_file=session_file,
        session_id="ses_fe591cc9fffeoMveld49fa4stF",
        last_activity="2026-01-01T00:00:00",
    )
    result = load_session(session_file=session_file)
    assert result["session_id"] == "ses_fe591cc9fffeoMveld49fa4stF"
    assert result["last_activity"] == "2026-01-01T00:00:00"


def test_save_session_default_last_activity(tmp_path):
    session_file = tmp_path / "session.json"
    save_session(session_file=session_file, session_id="x")
    data = json.loads(session_file.read_text())
    assert data["last_activity"] != ""


def test_save_session_creates_parent_dirs(tmp_path):
    session_file = tmp_path / "deep" / "nested" / "session.json"
    save_session(session_file=session_file, session_id=None)
    assert session_file.exists()


def test_load_session_invalid_json(tmp_path):
    session_file = tmp_path / "session.json"
    session_file.write_text("not json")
    result = load_session(session_file=session_file)
    assert result == {"session_id": None, "last_activity": ""}


def test_load_session_drops_legacy_uuid_id(tmp_path):
    """A uuid written by a pre-opencode version is not resumable."""
    session_file = tmp_path / "session.json"
    save_session(
        session_file=session_file,
        session_id="a1b2c3d4-e5f6-7890-abcd-ef1234567890",
        last_activity="2026-01-01T00:00:00",
    )
    result = load_session(session_file=session_file)
    assert result["session_id"] is None
    assert result["last_activity"] == "2026-01-01T00:00:00"


def test_load_session_keeps_opencode_id(tmp_path):
    session_file = tmp_path / "session.json"
    save_session(session_file=session_file, session_id="ses_abc")
    assert load_session(session_file=session_file)["session_id"] == "ses_abc"
