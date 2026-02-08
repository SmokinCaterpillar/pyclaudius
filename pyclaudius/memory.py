import json
import logging
import re
from pathlib import Path

logger = logging.getLogger(__name__)

_REMEMBER_PATTERN = re.compile(r"\[REMEMBER:\s*([^\]]+)\]", re.IGNORECASE)
_FORGET_PATTERN = re.compile(r"\[FORGET:\s*([^\]]+)\]", re.IGNORECASE)


def load_memory(*, memory_file: Path) -> list[str]:
    """Load memory facts from a JSON file. Returns [] on missing/invalid."""
    try:
        data = json.loads(memory_file.read_text(encoding="utf-8"))
        if isinstance(data, list):
            return [str(item) for item in data]
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        pass
    return []


def save_memory(*, memory_file: Path, memories: list[str]) -> None:
    """Save memory facts to a JSON file."""
    memory_file.write_text(json.dumps(memories, indent=2), encoding="utf-8")


def format_memory_section(*, memories: list[str]) -> str:
    """Format memories as a markdown section for the prompt."""
    if not memories:
        return ""
    lines = "\n".join(f"- {fact}" for fact in memories)
    return f"## Memory\n{lines}\n\n"


def extract_remember_tags(*, text: str) -> list[str]:
    """Extract [REMEMBER: ...] facts from text."""
    return [match.strip() for match in _REMEMBER_PATTERN.findall(text)]


def extract_forget_tags(*, text: str) -> list[str]:
    """Extract [FORGET: ...] keywords from text."""
    return [match.strip() for match in _FORGET_PATTERN.findall(text)]


def strip_remember_tags(*, text: str) -> str:
    """Remove [REMEMBER: ...] and [FORGET: ...] tags from text."""
    text = _REMEMBER_PATTERN.sub("", text)
    text = _FORGET_PATTERN.sub("", text)
    return text.strip()


def remove_memories(*, existing: list[str], keywords: list[str]) -> list[str]:
    """Remove memories that contain any of the keywords (case-insensitive)."""
    lower_keywords = [kw.lower() for kw in keywords]
    return [
        fact for fact in existing
        if not any(kw in fact.lower() for kw in lower_keywords)
    ]


def add_memories(
    *, existing: list[str], new: list[str], max_memories: int = 100
) -> list[str]:
    """Append unique memories (case-insensitive dedup), trim to max."""
    seen = {fact.lower() for fact in existing}
    combined = list(existing)
    for fact in new:
        if fact.lower() not in seen:
            seen.add(fact.lower())
            combined.append(fact)
    return combined[-max_memories:]
