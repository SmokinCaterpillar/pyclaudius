"""Parsing of the JSONL event stream emitted by ``opencode run --format json``.

Observed event shapes (opencode 1.18.18)::

    {"type": "step_start",  "sessionID": "ses_..."}
    {"type": "text",        "sessionID": "ses_...", "part": {"id": "prt_...", "text": "..."}}
    {"type": "tool_use",    "sessionID": "ses_...", "part": {"tool": "bash", "state": {"status": "completed"}}}
    {"type": "step_finish", "sessionID": "ses_...", "part": {"reason": "stop", "tokens": {...}, "cost": 0.01}}
    {"type": "error",       "sessionID": "ses_...", "error": {"name": "APIError", "data": {...}}}

A tool-using turn produces several steps: each intermediate step ends with
``reason == "tool-calls"`` and a fresh ``step_start`` follows, until a final
step ends with ``reason == "stop"``. Only the last step's text is the answer —
earlier steps carry the model narrating its way towards a tool call, which the
Claude CLI's ``--output-format text`` never showed the user either.

The parser is deliberately forgiving: upstream has open bugs about the terminal
``step_finish`` (and occasionally ``text``) being dropped in some environments,
so a missing terminal event is reported via ``finished`` rather than treated as
a hard failure.
"""

import json
import logging
from typing import Any, NamedTuple

logger = logging.getLogger(__name__)


class OpencodeResult(NamedTuple):
    """Everything pyclaudius needs out of one ``opencode run`` invocation."""

    text: str
    session_id: str | None
    error_name: str | None
    error_message: str | None
    status_code: int | None
    is_retryable: bool | None
    finished: bool
    tokens: int | None
    cost: float | None


def _as_dict(value: Any) -> dict:
    """Return *value* if it is a dict, else an empty dict."""
    return value if isinstance(value, dict) else {}


def _iter_events(*, stdout: str) -> list[dict]:
    """Decode JSONL, skipping blank and non-object lines instead of raising.

    Stray non-JSON output (a warning banner, a partially flushed line) must not
    lose the events that did arrive.
    """
    events: list[dict] = []
    for line in stdout.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        try:
            event = json.loads(stripped)
        except json.JSONDecodeError:
            logger.debug(f"Skipping non-JSON line from opencode: {stripped[:120]}")
            continue
        if isinstance(event, dict):
            events.append(event)
    return events


def _join_step(*, step: dict[str, str]) -> str:
    """Join the text parts of one step in arrival order."""
    return "\n\n".join(text for text in step.values() if text.strip()).strip()


def _select_text(*, steps: list[dict[str, str]]) -> str:
    """Pick the answer text: the last step that produced any.

    Falls back to every step's text joined, so that a stream whose final step
    was truncated still surfaces whatever the model did say.
    """
    for step in reversed(steps):
        text = _join_step(step=step)
        if text:
            return text
    return ""


def parse_opencode_stream(*, stdout: str) -> OpencodeResult:
    """Parse an ``opencode run --format json`` stream into a single result."""
    session_id: str | None = None
    steps: list[dict[str, str]] = []
    error_name: str | None = None
    error_message: str | None = None
    status_code: int | None = None
    is_retryable: bool | None = None
    finished = False
    tokens: int | None = None
    cost: float | None = None

    for event in _iter_events(stdout=stdout):
        if session_id is None:
            candidate = event.get("sessionID")
            if isinstance(candidate, str) and candidate:
                session_id = candidate

        event_type = event.get("type")
        part = _as_dict(event.get("part"))

        if event_type == "step_start":
            steps.append({})

        elif event_type == "text":
            text = part.get("text")
            if isinstance(text, str):
                if not steps:
                    steps.append({})
                # Keyed by part id so a re-sent part replaces rather than
                # duplicates itself; positional key when the id is absent.
                part_id = part.get("id")
                key = part_id if isinstance(part_id, str) else f"_{len(steps[-1])}"
                steps[-1][key] = text

        elif event_type == "step_finish":
            if part.get("reason") == "stop":
                finished = True
            step_tokens = _as_dict(part.get("tokens")).get("total")
            if isinstance(step_tokens, int):
                tokens = step_tokens
            step_cost = part.get("cost")
            if isinstance(step_cost, int | float):
                cost = (cost or 0.0) + float(step_cost)

        elif event_type == "error":
            error = _as_dict(event.get("error"))
            data = _as_dict(error.get("data"))
            name = error.get("name")
            error_name = name if isinstance(name, str) else "UnknownError"
            message = data.get("message")
            error_message = message if isinstance(message, str) else None
            code = data.get("statusCode")
            status_code = code if isinstance(code, int) else None
            retryable = data.get("isRetryable")
            is_retryable = retryable if isinstance(retryable, bool) else None

    return OpencodeResult(
        text=_select_text(steps=steps),
        session_id=session_id,
        error_name=error_name,
        error_message=error_message,
        status_code=status_code,
        is_retryable=is_retryable,
        finished=finished,
        tokens=tokens,
        cost=cost,
    )
