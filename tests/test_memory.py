import json

from pyclaudius.memory import (
    add_memories,
    format_memory_section,
    load_memory,
    remove_memories,
    save_memory,
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
