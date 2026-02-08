from pyclaudius.cron.tags import (
    extract_cron_add_tags,
    extract_cron_remove_tags,
    extract_schedule_tags,
    has_cron_list_tag,
    has_silent_tag,
    parse_cron_add_value,
    parse_schedule_value,
    strip_cron_tags,
)


def test_extract_cron_add_tags_none():
    assert extract_cron_add_tags(text="no tags here") == []


def test_extract_cron_add_tags_single():
    result = extract_cron_add_tags(text="ok [CRON_ADD: */5 * * * * | check weather]")
    assert result == ["*/5 * * * * | check weather"]


def test_extract_cron_add_tags_multiple():
    text = "[CRON_ADD: 0 9 * * * | morning] and [CRON_ADD: 0 17 * * * | evening]"
    result = extract_cron_add_tags(text=text)
    assert len(result) == 2


def test_extract_cron_add_tags_case_insensitive():
    result = extract_cron_add_tags(text="[cron_add: */5 * * * * | test]")
    assert len(result) == 1


def test_extract_schedule_tags_none():
    assert extract_schedule_tags(text="no tags") == []


def test_extract_schedule_tags_single():
    result = extract_schedule_tags(text="[SCHEDULE: 2026-02-10 14:30 | meeting]")
    assert result == ["2026-02-10 14:30 | meeting"]


def test_extract_schedule_tags_multiple():
    text = "[SCHEDULE: 2026-02-10 14:30 | a] [SCHEDULE: 2026-03-01 09:00 | b]"
    assert len(extract_schedule_tags(text=text)) == 2


def test_extract_schedule_tags_case_insensitive():
    result = extract_schedule_tags(text="[schedule: 2026-02-10 14:30 | test]")
    assert len(result) == 1


def test_extract_cron_remove_tags_none():
    assert extract_cron_remove_tags(text="no tags") == []


def test_extract_cron_remove_tags_single():
    result = extract_cron_remove_tags(text="[CRON_REMOVE: 2]")
    assert result == [2]


def test_extract_cron_remove_tags_multiple():
    result = extract_cron_remove_tags(text="[CRON_REMOVE: 1] [CRON_REMOVE: 3]")
    assert result == [1, 3]


def test_extract_cron_remove_tags_non_digit_ignored():
    result = extract_cron_remove_tags(text="[CRON_REMOVE: abc]")
    assert result == []


def test_extract_cron_remove_tags_case_insensitive():
    result = extract_cron_remove_tags(text="[cron_remove: 1]")
    assert result == [1]


def test_has_cron_list_tag_false():
    assert has_cron_list_tag(text="no tag") is False


def test_has_cron_list_tag_true():
    assert has_cron_list_tag(text="here [CRON_LIST] please") is True


def test_has_cron_list_tag_case_insensitive():
    assert has_cron_list_tag(text="[cron_list]") is True


def test_strip_cron_tags_removes_all():
    text = (
        "Hello [CRON_ADD: */5 * * * * | test] "
        "[SCHEDULE: 2026-02-10 14:30 | meeting] "
        "[CRON_REMOVE: 2] "
        "[CRON_LIST] bye"
    )
    result = strip_cron_tags(text=text)
    assert "[CRON_ADD" not in result
    assert "[SCHEDULE" not in result
    assert "[CRON_REMOVE" not in result
    assert "[CRON_LIST" not in result
    assert "Hello" in result
    assert "bye" in result


def test_strip_cron_tags_no_tags():
    assert strip_cron_tags(text="hello world") == "hello world"


def test_parse_cron_add_value_valid():
    result = parse_cron_add_value(value="*/5 * * * * | check weather")
    assert result == ("*/5 * * * *", "check weather")


def test_parse_cron_add_value_no_pipe():
    assert parse_cron_add_value(value="no pipe here") is None


def test_parse_cron_add_value_empty_prompt():
    assert parse_cron_add_value(value="*/5 * * * * | ") is None


def test_parse_cron_add_value_empty_expression():
    assert parse_cron_add_value(value=" | check weather") is None


def test_parse_schedule_value_valid():
    result = parse_schedule_value(value="2026-02-10 14:30 | meeting reminder")
    assert result == ("2026-02-10 14:30", "meeting reminder")


def test_parse_schedule_value_no_pipe():
    assert parse_schedule_value(value="2026-02-10 14:30 meeting") is None


def test_parse_schedule_value_empty_prompt():
    assert parse_schedule_value(value="2026-02-10 14:30 | ") is None


def test_parse_schedule_value_empty_datetime():
    assert parse_schedule_value(value=" | meeting") is None


def test_has_silent_tag_true():
    assert has_silent_tag(text="Nothing to report [SILENT]") is True


def test_has_silent_tag_false():
    assert has_silent_tag(text="Here is the weather report") is False


def test_has_silent_tag_case_insensitive():
    assert has_silent_tag(text="[silent]") is True
    assert has_silent_tag(text="[Silent]") is True


def test_strip_cron_tags_removes_silent():
    text = "Hello [SILENT] bye"
    result = strip_cron_tags(text=text)
    assert "[SILENT]" not in result
    assert "Hello" in result
    assert "bye" in result
