import json

from pyclaudius.memory import (
    add_memories,
    extract_forget_tags,
    extract_remember_tags,
    format_memory_section,
    load_memory,
    remove_memories,
    save_memory,
    strip_remember_tags,
)


def test_load_memory_round_trip(tmp_path):
    f = tmp_path / "memory.json"
    facts = ["fact one", "fact two"]
    save_memory(memory_file=f, memories=facts)
    assert load_memory(memory_file=f) == facts


def test_load_memory_missing_file(tmp_path):
    f = tmp_path / "nonexistent.json"
    assert load_memory(memory_file=f) == []


def test_load_memory_invalid_json(tmp_path):
    f = tmp_path / "bad.json"
    f.write_text("{broken", encoding="utf-8")
    assert load_memory(memory_file=f) == []


def test_load_memory_non_list_json(tmp_path):
    f = tmp_path / "obj.json"
    f.write_text('{"key": "value"}', encoding="utf-8")
    assert load_memory(memory_file=f) == []


def test_save_memory_creates_file(tmp_path):
    f = tmp_path / "memory.json"
    save_memory(memory_file=f, memories=["hello"])
    assert json.loads(f.read_text(encoding="utf-8")) == ["hello"]


def test_format_memory_section_empty():
    assert format_memory_section(memories=[]) == ""


def test_format_memory_section_single():
    result = format_memory_section(memories=["user likes Python"])
    assert result == "## Memory\n- user likes Python\n\n"


def test_format_memory_section_multi():
    result = format_memory_section(memories=["fact1", "fact2", "fact3"])
    assert result == "## Memory\n- fact1\n- fact2\n- fact3\n\n"


def test_extract_remember_tags_none():
    assert extract_remember_tags(text="No tags here") == []


def test_extract_remember_tags_single():
    text = "Hello [REMEMBER: user likes coffee] world"
    assert extract_remember_tags(text=text) == ["user likes coffee"]


def test_extract_remember_tags_multi():
    text = "[REMEMBER: fact1] some text [REMEMBER: fact2]"
    assert extract_remember_tags(text=text) == ["fact1", "fact2"]


def test_extract_remember_tags_case_insensitive():
    text = "[remember: lowercase] and [Remember: mixed]"
    assert extract_remember_tags(text=text) == ["lowercase", "mixed"]


def test_strip_remember_tags():
    text = "Hello [REMEMBER: user likes coffee] world"
    assert strip_remember_tags(text=text) == "Hello  world"


def test_strip_remember_tags_multi():
    text = "[REMEMBER: a] text [REMEMBER: b] end"
    assert strip_remember_tags(text=text) == "text  end"


def test_strip_remember_tags_no_tags():
    text = "No tags here"
    assert strip_remember_tags(text=text) == "No tags here"


def test_add_memories_basic():
    result = add_memories(existing=["a"], new=["b"])
    assert result == ["a", "b"]


def test_add_memories_dedup_case_insensitive():
    result = add_memories(existing=["Hello"], new=["hello", "HELLO", "world"])
    assert result == ["Hello", "world"]


def test_add_memories_max_limit():
    result = add_memories(existing=["old"], new=["new1", "new2"], max_memories=2)
    assert result == ["new1", "new2"]


def test_add_memories_empty():
    result = add_memories(existing=[], new=[])
    assert result == []


def test_extract_forget_tags_none():
    assert extract_forget_tags(text="No tags here") == []


def test_extract_forget_tags_single():
    text = "OK [FORGET: coffee] done"
    assert extract_forget_tags(text=text) == ["coffee"]


def test_extract_forget_tags_case_insensitive():
    text = "[forget: old fact] and [Forget: another]"
    assert extract_forget_tags(text=text) == ["old fact", "another"]


def test_strip_remember_tags_also_strips_forget():
    text = "Hello [REMEMBER: a] and [FORGET: b] world"
    assert strip_remember_tags(text=text) == "Hello  and  world"


def test_remove_memories_by_keyword():
    result = remove_memories(
        existing=["user likes coffee", "user likes tea", "user is 30"],
        keywords=["coffee"],
    )
    assert result == ["user likes tea", "user is 30"]


def test_remove_memories_case_insensitive():
    result = remove_memories(
        existing=["User likes Coffee", "user likes tea"],
        keywords=["coffee"],
    )
    assert result == ["user likes tea"]


def test_remove_memories_multiple_keywords():
    result = remove_memories(
        existing=["likes coffee", "likes tea", "age 30"],
        keywords=["coffee", "age"],
    )
    assert result == ["likes tea"]


def test_remove_memories_no_match():
    facts = ["likes coffee", "likes tea"]
    result = remove_memories(existing=facts, keywords=["python"])
    assert result == facts
