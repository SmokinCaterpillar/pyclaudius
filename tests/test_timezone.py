from zoneinfo import ZoneInfo

from pyclaudius.timezone import (
    find_timezones,
    get_zoneinfo,
    load_timezone,
    save_timezone,
)


def test_load_timezone_missing_file(tmp_path):
    result = load_timezone(timezone_file=tmp_path / "missing.json")
    assert result is None


def test_load_timezone_invalid_json(tmp_path):
    f = tmp_path / "bad.json"
    f.write_text("not json", encoding="utf-8")
    result = load_timezone(timezone_file=f)
    assert result is None


def test_save_and_load_timezone(tmp_path):
    f = tmp_path / "tz.json"
    save_timezone(timezone_file=f, timezone="Europe/Berlin")
    result = load_timezone(timezone_file=f)
    assert result == "Europe/Berlin"


def test_save_timezone_none(tmp_path):
    f = tmp_path / "tz.json"
    save_timezone(timezone_file=f, timezone=None)
    result = load_timezone(timezone_file=f)
    assert result is None


def test_get_zoneinfo_none_returns_utc():
    result = get_zoneinfo(timezone=None)
    assert result == ZoneInfo("UTC")


def test_get_zoneinfo_valid():
    result = get_zoneinfo(timezone="Europe/Berlin")
    assert result == ZoneInfo("Europe/Berlin")


def test_get_zoneinfo_invalid_falls_back_to_utc():
    result = get_zoneinfo(timezone="Invalid/Nonexistent")
    assert result == ZoneInfo("UTC")


def test_find_timezones_exact_match():
    result = find_timezones(query="UTC")
    assert "UTC" in result


def test_find_timezones_city_match():
    result = find_timezones(query="Berlin")
    assert "Europe/Berlin" in result


def test_find_timezones_case_insensitive():
    result = find_timezones(query="berlin")
    assert "Europe/Berlin" in result


def test_find_timezones_spaces_to_underscores():
    result = find_timezones(query="New York")
    assert "America/New_York" in result


def test_find_timezones_substring_match():
    result = find_timezones(query="tokyo")
    assert "Asia/Tokyo" in result


def test_find_timezones_no_match():
    result = find_timezones(query="xyznonexistent")
    assert result == []


def test_find_timezones_empty_query():
    result = find_timezones(query="")
    assert result == []


def test_find_timezones_partial_city():
    result = find_timezones(query="Berli")
    assert "Europe/Berlin" in result
