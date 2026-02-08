import json

from pyclaudius.cron.store import format_cron_list, load_cron_jobs, save_cron_jobs


def test_load_cron_jobs_missing_file(tmp_path):
    result = load_cron_jobs(cron_file=tmp_path / "missing.json")
    assert result == []


def test_load_cron_jobs_invalid_json(tmp_path):
    f = tmp_path / "bad.json"
    f.write_text("not json", encoding="utf-8")
    result = load_cron_jobs(cron_file=f)
    assert result == []


def test_load_cron_jobs_valid(tmp_path):
    f = tmp_path / "cron.json"
    jobs = [
        {
            "id": "abc",
            "job_type": "cron",
            "expression": "*/5 * * * *",
            "prompt": "check weather",
            "created_at": "2026-01-01T00:00:00",
        }
    ]
    f.write_text(json.dumps(jobs), encoding="utf-8")
    result = load_cron_jobs(cron_file=f)
    assert len(result) == 1
    assert result[0]["id"] == "abc"
    assert result[0]["prompt"] == "check weather"


def test_save_cron_jobs_creates_file(tmp_path):
    f = tmp_path / "cron.json"
    jobs = [
        {
            "id": "abc",
            "job_type": "once",
            "expression": "2026-02-10T14:30:00",
            "prompt": "remind me",
            "created_at": "2026-01-01T00:00:00",
        }
    ]
    save_cron_jobs(cron_file=f, jobs=jobs)
    assert f.exists()
    data = json.loads(f.read_text(encoding="utf-8"))
    assert len(data) == 1
    assert data[0]["id"] == "abc"


def test_save_and_load_roundtrip(tmp_path):
    f = tmp_path / "cron.json"
    jobs = [
        {
            "id": "x1",
            "job_type": "cron",
            "expression": "0 9 * * *",
            "prompt": "morning check",
            "created_at": "2026-01-01T00:00:00",
        },
        {
            "id": "x2",
            "job_type": "once",
            "expression": "2026-03-01T10:00:00",
            "prompt": "one time task",
            "created_at": "2026-01-02T00:00:00",
        },
    ]
    save_cron_jobs(cron_file=f, jobs=jobs)
    loaded = load_cron_jobs(cron_file=f)
    assert loaded == jobs


def test_format_cron_list_empty():
    result = format_cron_list(jobs=[])
    assert result == "No scheduled jobs."


def test_format_cron_list_single_cron():
    jobs = [
        {
            "id": "a",
            "job_type": "cron",
            "expression": "*/5 * * * *",
            "prompt": "check weather",
            "created_at": "2026-01-01T00:00:00",
        }
    ]
    result = format_cron_list(jobs=jobs)
    assert result == "1. [CRON] */5 * * * * \u2014 check weather"


def test_format_cron_list_mixed_types():
    jobs = [
        {
            "id": "a",
            "job_type": "cron",
            "expression": "0 9 * * *",
            "prompt": "morning",
            "created_at": "2026-01-01T00:00:00",
        },
        {
            "id": "b",
            "job_type": "once",
            "expression": "2026-03-01T10:00:00",
            "prompt": "reminder",
            "created_at": "2026-01-02T00:00:00",
        },
    ]
    result = format_cron_list(jobs=jobs)
    assert "[CRON]" in result
    assert "[ONCE]" in result
    assert "1." in result
    assert "2." in result
