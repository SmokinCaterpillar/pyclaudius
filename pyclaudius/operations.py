"""Shared business logic for cron and memory operations.

Used by both MCP tools (server.py) and Telegram command handlers.
Each function takes explicit parameters plus a ``bot_data`` dict,
returns a result string, and raises ``ValueError`` on validation failure.
"""

import logging
import uuid
from datetime import UTC, datetime

from pyclaudius.backlog import BacklogItem, format_backlog_list, save_backlog
from pyclaudius.config import Settings
from pyclaudius.cron.models import ScheduledJob
from pyclaudius.cron.scheduler import (
    execute_scheduled_job,
    parse_schedule_datetime,
    register_job,
    unregister_job,
    validate_cron_expression,
)
from pyclaudius.cron.store import format_cron_list, save_cron_jobs
from pyclaudius.memory import add_memories, remove_memories, save_memory

logger = logging.getLogger(__name__)


def add_cron_job(*, expression: str, prompt_text: str, bot_data: dict) -> str:
    """Add a recurring cron job. Raises ValueError if the expression is invalid."""
    if not validate_cron_expression(expression=expression):
        raise ValueError(f"Invalid cron expression: {expression}")

    settings: Settings = bot_data["settings"]
    user_tz: str | None = bot_data.get("user_timezone")
    job: ScheduledJob = {
        "id": str(uuid.uuid4()),
        "job_type": "cron",
        "expression": expression,
        "prompt": prompt_text,
        "created_at": datetime.now(tz=UTC).isoformat(),
    }
    if user_tz is not None:
        job["timezone"] = user_tz

    cron_jobs: list[ScheduledJob] = bot_data.get("cron_jobs", [])
    cron_jobs.append(job)
    bot_data["cron_jobs"] = cron_jobs
    save_cron_jobs(cron_file=settings.cron_file, jobs=cron_jobs)

    scheduler = bot_data["scheduler"]
    application = bot_data["application"]
    register_job(
        scheduler=scheduler,
        job=job,
        callback=execute_scheduled_job,
        callback_kwargs={
            "application": application,
            "chat_id": settings.telegram_user_id,
            "prompt_text": prompt_text,
            "job_id": job["id"],
            "job_type": "cron",
        },
    )

    logger.info(f"Added cron job {job['id']}: {expression} — {prompt_text[:50]}")
    return f"Cron job added: {expression} — {prompt_text}"


def schedule_once(*, datetime_str: str, prompt_text: str, bot_data: dict) -> str:
    """Schedule a one-time task. Raises ValueError on invalid/past datetime."""
    settings: Settings = bot_data["settings"]
    user_tz: str | None = bot_data.get("user_timezone")

    dt = parse_schedule_datetime(text=datetime_str, timezone=user_tz)
    if dt is None:
        raise ValueError(
            f"Invalid datetime: {datetime_str}. "
            "Supported formats: YYYY-MM-DD HH:MM, YYYY-MM-DDTHH:MM:SS"
        )

    if dt <= datetime.now(tz=UTC):
        raise ValueError("Datetime must be in the future.")

    job: ScheduledJob = {
        "id": str(uuid.uuid4()),
        "job_type": "once",
        "expression": datetime_str,
        "prompt": prompt_text,
        "created_at": datetime.now(tz=UTC).isoformat(),
    }
    if user_tz is not None:
        job["timezone"] = user_tz

    cron_jobs: list[ScheduledJob] = bot_data.get("cron_jobs", [])
    cron_jobs.append(job)
    bot_data["cron_jobs"] = cron_jobs
    save_cron_jobs(cron_file=settings.cron_file, jobs=cron_jobs)

    scheduler = bot_data["scheduler"]
    application = bot_data["application"]
    register_job(
        scheduler=scheduler,
        job=job,
        callback=execute_scheduled_job,
        callback_kwargs={
            "application": application,
            "chat_id": settings.telegram_user_id,
            "prompt_text": prompt_text,
            "job_id": job["id"],
            "job_type": "once",
        },
    )

    logger.info(
        f"Scheduled one-time job {job['id']}: {datetime_str} — {prompt_text[:50]}"
    )
    return f"Scheduled one-time task: {datetime_str} — {prompt_text}"


def remove_cron_job(*, index: int, bot_data: dict) -> str:
    """Remove a job by 1-based index. Raises ValueError if index is out of range."""
    settings: Settings = bot_data["settings"]
    cron_jobs: list[ScheduledJob] = bot_data.get("cron_jobs", [])

    if index < 1 or index > len(cron_jobs):
        raise ValueError(f"Invalid index {index}. Valid range: 1-{len(cron_jobs)}.")

    removed = cron_jobs.pop(index - 1)
    bot_data["cron_jobs"] = cron_jobs
    save_cron_jobs(cron_file=settings.cron_file, jobs=cron_jobs)

    scheduler = bot_data["scheduler"]
    unregister_job(scheduler=scheduler, job_id=removed["id"])

    label = "[CRON]" if removed["job_type"] == "cron" else "[ONCE]"
    logger.info(f"Removed job {removed['id']}: {removed['prompt'][:50]}")
    return f"Removed job {index}: {label} {removed['expression']} — {removed['prompt']}"


def list_cron_jobs(*, bot_data: dict) -> str:
    """List all scheduled jobs."""
    cron_jobs: list[ScheduledJob] = bot_data.get("cron_jobs", [])
    user_tz: str | None = bot_data.get("user_timezone")
    return format_cron_list(jobs=cron_jobs, display_timezone=user_tz)


def remember_fact(*, fact: str, bot_data: dict) -> str:
    """Remember a fact about the user. Returns confirmation string."""
    settings: Settings = bot_data["settings"]
    memory: list[str] = bot_data.get("memory", [])

    is_new = fact.lower() not in {f.lower() for f in memory}
    memory_before = list(memory)
    memory = add_memories(
        existing=memory,
        new=[fact],
        max_memories=settings.max_memories,
    )
    bot_data["memory"] = memory
    save_memory(memory_file=settings.memory_file, memories=memory)
    logger.info(f"Stored memory: {fact}")

    reply = f'Remembered: "{fact}"'
    if is_new and len(memory_before) >= settings.max_memories:
        dropped = memory_before[0]
        reply += (
            f"\n\nWarning: memory full ({settings.max_memories}). "
            f'Oldest fact forgotten: "{dropped}"'
        )
    return reply


def forget_memory(*, keyword: str, bot_data: dict) -> str:
    """Remove memories matching a keyword or 1-based index. Raises ValueError on invalid index."""
    settings: Settings = bot_data["settings"]
    memory: list[str] = bot_data.get("memory", [])

    # Index-based removal
    if keyword.isdigit():
        index = int(keyword)
        if index < 1 or index > len(memory):
            raise ValueError(f"Invalid index {index}. Valid range: 1-{len(memory)}.")
        removed_fact = memory.pop(index - 1)
        bot_data["memory"] = memory
        save_memory(memory_file=settings.memory_file, memories=memory)
        return f'Removed memory {index}: "{removed_fact}"'

    # Keyword-based removal
    updated = remove_memories(existing=memory, keywords=[keyword])
    removed_count = len(memory) - len(updated)

    if removed_count == 0:
        return f'No memories matching "{keyword}".'

    bot_data["memory"] = updated
    save_memory(memory_file=settings.memory_file, memories=updated)
    return f'Removed {removed_count} memory/memories matching "{keyword}".'


def list_memories(*, bot_data: dict) -> str:
    """List all stored memory facts."""
    memory: list[str] = bot_data.get("memory", [])
    if not memory:
        return "No memories stored."
    lines = "\n".join(f"{i + 1}. {fact}" for i, fact in enumerate(memory))
    return f"Stored memories ({len(memory)}):\n\n{lines}"


def list_backlog(*, bot_data: dict) -> str:
    """List all pending backlog items."""
    items: list[BacklogItem] = bot_data.get("backlog", [])
    return format_backlog_list(items=items)


def clear_backlog(*, bot_data: dict) -> str:
    """Clear all backlog items."""
    settings: Settings = bot_data["settings"]
    bot_data["backlog"] = []
    save_backlog(backlog_file=settings.backlog_file, items=[])
    logger.info("Backlog cleared")
    return "Backlog cleared."


def remove_backlog_item(*, index: int, bot_data: dict) -> BacklogItem:
    """Remove a backlog item by 1-based index. Raises ValueError if out of range."""
    settings: Settings = bot_data["settings"]
    items: list[BacklogItem] = bot_data.get("backlog", [])

    if index < 1 or index > len(items):
        raise ValueError(f"Invalid index {index}. Valid range: 1-{len(items)}.")

    removed = items.pop(index - 1)
    bot_data["backlog"] = items
    save_backlog(backlog_file=settings.backlog_file, items=items)
    logger.info(f"Removed backlog item {index}: {removed['prompt'][:50]}")
    return removed
