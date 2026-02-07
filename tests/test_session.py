import json

from pyclaudius.session import extract_session_id, load_session, save_session


def test_load_session_missing_file(tmp_path):
    result = load_session(session_file=tmp_path / "nonexistent.json")
    assert result == {"session_id": None, "last_activity": ""}


def test_save_and_load_session(tmp_path):
    session_file = tmp_path / "session.json"
    save_session(
        session_file=session_file,
        session_id="abc-123",
        last_activity="2026-01-01T00:00:00",
    )
    result = load_session(session_file=session_file)
    assert result["session_id"] == "abc-123"
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


def test_extract_session_id_match():
    output = "Some output\nSession ID: a1b2c3d4-e5f6-7890-abcd-ef1234567890\nMore"
    result = extract_session_id(output=output)
    assert result == "a1b2c3d4-e5f6-7890-abcd-ef1234567890"


def test_extract_session_id_no_match():
    result = extract_session_id(output="no session here")
    assert result is None


def test_extract_session_id_case_insensitive():
    output = "session id: abcdef01-2345-6789-abcd-ef0123456789"
    result = extract_session_id(output=output)
    assert result == "abcdef01-2345-6789-abcd-ef0123456789"
