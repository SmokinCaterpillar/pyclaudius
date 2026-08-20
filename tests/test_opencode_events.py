import json

from pyclaudius.opencode_events import parse_opencode_stream

SESSION = "ses_fe592c0e1ffeTZIh71EY8Wn1Ey"


def _line(**event) -> str:
    return json.dumps(event)


def _stream(*events: str) -> str:
    return "\n".join(events) + "\n"


def _text_event(text: str, *, part_id: str = "prt_1") -> str:
    return _line(type="text", sessionID=SESSION, part={"id": part_id, "text": text})


def _step_finish(*, reason: str = "stop", total: int = 100, cost: float = 0.01) -> str:
    return _line(
        type="step_finish",
        sessionID=SESSION,
        part={"reason": reason, "tokens": {"total": total}, "cost": cost},
    )


def test_parse_simple_run():
    stream = _stream(
        _line(type="step_start", sessionID=SESSION),
        _text_event("PONG"),
        _step_finish(total=5703, cost=0.0175),
    )
    result = parse_opencode_stream(stdout=stream)
    assert result.text == "PONG"
    assert result.session_id == SESSION
    assert result.finished is True
    assert result.tokens == 5703
    assert result.cost == 0.0175
    assert result.error_name is None


def test_parse_empty_stream():
    result = parse_opencode_stream(stdout="")
    assert result.text == ""
    assert result.session_id is None
    assert result.finished is False
    assert result.tokens is None
    assert result.cost is None


def test_parse_skips_non_json_lines():
    stream = _stream(
        "Warning: something noisy on stdout",
        _line(type="step_start", sessionID=SESSION),
        "{ not valid json",
        _text_event("still parsed"),
        _step_finish(),
    )
    result = parse_opencode_stream(stdout=stream)
    assert result.text == "still parsed"
    assert result.finished is True


def test_parse_skips_json_that_is_not_an_object():
    stream = _stream("[1, 2, 3]", '"a string"', _text_event("kept"))
    assert parse_opencode_stream(stdout=stream).text == "kept"


def test_parse_returns_last_step_text_for_tool_using_turn():
    """A tool-using turn narrates in early steps; only the last one is the answer."""
    stream = _stream(
        _line(type="step_start", sessionID=SESSION),
        _text_event("Let me check that file", part_id="prt_a"),
        _line(
            type="tool_use",
            sessionID=SESSION,
            part={"tool": "bash", "state": {"status": "completed"}},
        ),
        _step_finish(reason="tool-calls", total=5850, cost=0.01),
        _line(type="step_start", sessionID=SESSION),
        _text_event("The file says hello", part_id="prt_b"),
        _step_finish(reason="stop", total=5948, cost=0.02),
    )
    result = parse_opencode_stream(stdout=stream)
    assert result.text == "The file says hello"
    assert result.tokens == 5948
    assert result.cost == 0.03


def test_parse_falls_back_to_earlier_text_when_last_step_is_empty():
    stream = _stream(
        _line(type="step_start", sessionID=SESSION),
        _text_event("partial answer"),
        _step_finish(reason="tool-calls"),
        _line(type="step_start", sessionID=SESSION),
    )
    result = parse_opencode_stream(stdout=stream)
    assert result.text == "partial answer"
    assert result.finished is False


def test_parse_joins_multiple_text_parts_in_one_step():
    stream = _stream(
        _line(type="step_start", sessionID=SESSION),
        _text_event("first", part_id="prt_a"),
        _text_event("second", part_id="prt_b"),
        _step_finish(),
    )
    assert parse_opencode_stream(stdout=stream).text == "first\n\nsecond"


def test_parse_replaces_resent_part_instead_of_duplicating():
    stream = _stream(
        _line(type="step_start", sessionID=SESSION),
        _text_event("Hel", part_id="prt_same"),
        _text_event("Hello", part_id="prt_same"),
        _step_finish(),
    )
    assert parse_opencode_stream(stdout=stream).text == "Hello"


def test_parse_text_without_step_start():
    """Upstream can drop step_start; text must still be collected."""
    stream = _stream(_text_event("orphaned text"))
    assert parse_opencode_stream(stdout=stream).text == "orphaned text"


def test_parse_text_parts_without_ids():
    stream = _stream(
        _line(type="step_start", sessionID=SESSION),
        _line(type="text", sessionID=SESSION, part={"text": "one"}),
        _line(type="text", sessionID=SESSION, part={"text": "two"}),
        _step_finish(),
    )
    assert parse_opencode_stream(stdout=stream).text == "one\n\ntwo"


def test_parse_missing_terminal_step_finish():
    """The documented upstream bug: text arrives, terminal event does not."""
    stream = _stream(_line(type="step_start", sessionID=SESSION), _text_event("answer"))
    result = parse_opencode_stream(stdout=stream)
    assert result.text == "answer"
    assert result.finished is False


def test_parse_error_event():
    stream = _stream(
        _line(
            type="error",
            sessionID=SESSION,
            error={
                "name": "APIError",
                "data": {
                    "message": "Invalid API key or unauthorised access.",
                    "statusCode": 401,
                    "isRetryable": False,
                },
            },
        )
    )
    result = parse_opencode_stream(stdout=stream)
    assert result.error_name == "APIError"
    assert result.error_message == "Invalid API key or unauthorised access."
    assert result.status_code == 401
    assert result.is_retryable is False
    assert result.session_id == SESSION
    assert result.text == ""


def test_parse_error_event_without_data():
    stream = _stream(_line(type="error", sessionID=SESSION, error={"name": "OddError"}))
    result = parse_opencode_stream(stdout=stream)
    assert result.error_name == "OddError"
    assert result.error_message is None
    assert result.status_code is None
    assert result.is_retryable is None


def test_parse_error_event_without_name():
    stream = _stream(_line(type="error", sessionID=SESSION, error={}))
    assert parse_opencode_stream(stdout=stream).error_name == "UnknownError"


def test_parse_ignores_blank_lines():
    stream = f"\n\n{_text_event('hi')}\n\n\n"
    assert parse_opencode_stream(stdout=stream).text == "hi"


def test_parse_takes_first_session_id():
    stream = _stream(
        _line(type="step_start", sessionID=SESSION),
        _line(type="step_start", sessionID="ses_other"),
    )
    assert parse_opencode_stream(stdout=stream).session_id == SESSION


def test_parse_ignores_empty_session_id():
    stream = _stream(
        _line(type="step_start", sessionID=""),
        _line(type="step_start", sessionID=SESSION),
    )
    assert parse_opencode_stream(stdout=stream).session_id == SESSION


def test_parse_whitespace_only_text_is_not_an_answer():
    stream = _stream(
        _line(type="step_start", sessionID=SESSION),
        _text_event("   \n  "),
        _step_finish(),
    )
    assert parse_opencode_stream(stdout=stream).text == ""


def test_parse_tolerates_non_dict_part():
    stream = _stream(
        _line(type="text", sessionID=SESSION, part="not-a-dict"),
        _text_event("real"),
    )
    assert parse_opencode_stream(stdout=stream).text == "real"
