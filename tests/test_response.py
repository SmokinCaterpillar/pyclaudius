from pyclaudius.response import has_silent_tag, split_response


def test_empty_text():
    assert split_response(text="") == []


def test_short_text():
    assert split_response(text="hello") == ["hello"]


def test_text_at_limit():
    text = "a" * 4000
    assert split_response(text=text) == [text]


def test_split_at_paragraph():
    text = "a" * 3000 + "\n\n" + "b" * 3000
    chunks = split_response(text=text)
    assert len(chunks) == 2
    assert chunks[0] == "a" * 3000
    assert chunks[1] == "b" * 3000


def test_split_at_newline():
    text = "a" * 3000 + "\n" + "b" * 3000
    chunks = split_response(text=text)
    assert len(chunks) == 2
    assert chunks[0] == "a" * 3000
    assert chunks[1] == "b" * 3000


def test_split_at_space():
    text = "a" * 3000 + " " + "b" * 3000
    chunks = split_response(text=text)
    assert len(chunks) == 2
    assert chunks[0] == "a" * 3000
    assert chunks[1] == "b" * 3000


def test_hard_break():
    text = "a" * 5000
    chunks = split_response(text=text, max_length=4000)
    assert len(chunks) == 2
    assert chunks[0] == "a" * 4000
    assert chunks[1] == "a" * 1000


def test_custom_max_length():
    text = "hello world foo bar"
    chunks = split_response(text=text, max_length=12)
    assert chunks == ["hello world", "foo bar"]


def test_multiple_splits():
    text = "aaa bbb ccc ddd"
    chunks = split_response(text=text, max_length=8)
    assert chunks == ["aaa bbb", "ccc ddd"]


def test_has_silent_tag_true():
    assert has_silent_tag(text="Nothing to report [SILENT]") is True


def test_has_silent_tag_false():
    assert has_silent_tag(text="Here is the weather report") is False


def test_has_silent_tag_case_insensitive():
    assert has_silent_tag(text="[silent]") is True
    assert has_silent_tag(text="[Silent]") is True
