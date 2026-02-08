import logging
import uuid
from datetime import UTC, datetime

from telegram import Update
from telegram.ext import ContextTypes

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
from pyclaudius.cron.tags import (
    extract_cron_add_tags,
    extract_cron_remove_tags,
    extract_schedule_tags,
    has_cron_list_tag,
    parse_cron_add_value,
    parse_schedule_value,
    strip_cron_tags,
)
from pyclaudius.tooling import authorized

logger = logging.getLogger(__name__)


@authorized
async def handle_addcron_command(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Handle /addcron <5 cron fields> <prompt>."""
    settings: Settings = context.bot_data["settings"]

    if not update.message or not update.message.text:
        return

    if not settings.cron_enabled:
        await update.message.reply_text("Cron scheduling is disabled.")
        return

    text = update.message.text.removeprefix("/addcron").strip()
    parts = text.split(maxsplit=5)
    if len(parts) < 6:
        await update.message.reply_text(
            "Usage: /addcron <min> <hour> <day> <month> <weekday> <prompt>\n"
            "Example: /addcron */5 * * * * check the weather"
        )
        return

    expression = " ".join(parts[:5])
    prompt_text = parts[5]

    if not validate_cron_expression(expression=expression):
        await update.message.reply_text(f"Invalid cron expression: {expression}")
        return

    job: ScheduledJob = {
        "id": str(uuid.uuid4()),
        "job_type": "cron",
        "expression": expression,
        "prompt": prompt_text,
        "created_at": datetime.now(tz=UTC).isoformat(),
    }

    cron_jobs: list[ScheduledJob] = context.bot_data.get("cron_jobs", [])
    cron_jobs.append(job)
    context.bot_data["cron_jobs"] = cron_jobs
    save_cron_jobs(cron_file=settings.cron_file, jobs=cron_jobs)

    scheduler = context.bot_data["scheduler"]
    application = context.bot_data["application"]
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

    await update.message.reply_text(f"Cron job added: {expression} — {prompt_text}")
    logger.info(f"Added cron job {job['id']}: {expression} — {prompt_text[:50]}")


@authorized
async def handle_schedule_command(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Handle /schedule <datetime> | <prompt>."""
    settings: Settings = context.bot_data["settings"]

    if not update.message or not update.message.text:
        return

    if not settings.cron_enabled:
        await update.message.reply_text("Cron scheduling is disabled.")
        return

    text = update.message.text.removeprefix("/schedule").strip()
    if "|" not in text:
        await update.message.reply_text(
            "Usage: /schedule <datetime> | <prompt>\n"
            "Example: /schedule 2026-02-10 14:30 | remind me about meeting"
        )
        return

    datetime_str, prompt_text = text.split("|", maxsplit=1)
    datetime_str = datetime_str.strip()
    prompt_text = prompt_text.strip()

    if not datetime_str or not prompt_text:
        await update.message.reply_text(
            "Usage: /schedule <datetime> | <prompt>\n"
            "Example: /schedule 2026-02-10 14:30 | remind me about meeting"
        )
        return

    dt = parse_schedule_datetime(text=datetime_str)
    if dt is None:
        await update.message.reply_text(
            f"Invalid datetime: {datetime_str}\n"
            "Supported formats: YYYY-MM-DD HH:MM, YYYY-MM-DDTHH:MM:SS"
        )
        return

    if dt <= datetime.now(tz=UTC):
        await update.message.reply_text("Datetime must be in the future.")
        return

    job: ScheduledJob = {
        "id": str(uuid.uuid4()),
        "job_type": "once",
        "expression": datetime_str,
        "prompt": prompt_text,
        "created_at": datetime.now(tz=UTC).isoformat(),
    }

    cron_jobs: list[ScheduledJob] = context.bot_data.get("cron_jobs", [])
    cron_jobs.append(job)
    context.bot_data["cron_jobs"] = cron_jobs
    save_cron_jobs(cron_file=settings.cron_file, jobs=cron_jobs)

    scheduler = context.bot_data["scheduler"]
    application = context.bot_data["application"]
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

    await update.message.reply_text(
        f"Scheduled one-time task: {datetime_str} — {prompt_text}"
    )
    logger.info(
        f"Scheduled one-time job {job['id']}: {datetime_str} — {prompt_text[:50]}"
    )


@authorized
async def handle_removecron_command(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Handle /removecron <number>."""
    settings: Settings = context.bot_data["settings"]

    if not update.message or not update.message.text:
        return

    if not settings.cron_enabled:
        await update.message.reply_text("Cron scheduling is disabled.")
        return

    text = update.message.text.removeprefix("/removecron").strip()
    if not text.isdigit():
        await update.message.reply_text("Usage: /removecron <number>")
        return

    index = int(text)
    cron_jobs: list[ScheduledJob] = context.bot_data.get("cron_jobs", [])

    if index < 1 or index > len(cron_jobs):
        await update.message.reply_text(
            f"Invalid index {index}. Use /listcron to see valid numbers (1\u2013{len(cron_jobs)})."
        )
        return

    removed = cron_jobs.pop(index - 1)
    context.bot_data["cron_jobs"] = cron_jobs
    save_cron_jobs(cron_file=settings.cron_file, jobs=cron_jobs)

    scheduler = context.bot_data["scheduler"]
    unregister_job(scheduler=scheduler, job_id=removed["id"])

    label = "[CRON]" if removed["job_type"] == "cron" else "[ONCE]"
    await update.message.reply_text(
        f"Removed job {index}: {label} {removed['expression']} \u2014 {removed['prompt']}"
    )
    logger.info(f"Removed job {removed['id']}: {removed['prompt'][:50]}")


@authorized
async def handle_testcron_command(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Handle /testcron <number> — immediately execute a scheduled job for testing."""
    settings: Settings = context.bot_data["settings"]

    if not update.message or not update.message.text:
        return

    if not settings.cron_enabled:
        await update.message.reply_text("Cron scheduling is disabled.")
        return

    text = update.message.text.removeprefix("/testcron").strip()
    if not text.isdigit():
        await update.message.reply_text("Usage: /testcron <number>")
        return

    index = int(text)
    cron_jobs: list[ScheduledJob] = context.bot_data.get("cron_jobs", [])

    if index < 1 or index > len(cron_jobs):
        await update.message.reply_text(
            f"Invalid index {index}. Use /listcron to see valid numbers (1\u2013{len(cron_jobs)})."
        )
        return

    job = cron_jobs[index - 1]
    application = context.bot_data["application"]

    await update.message.reply_text(
        f"Testing job {index}: {job['expression']} \u2014 {job['prompt']}"
    )

    await execute_scheduled_job(
        application=application,
        chat_id=settings.telegram_user_id,
        prompt_text=job["prompt"],
        job_id=job["id"],
        job_type=job["job_type"],
        is_test=True,
    )
    logger.info(f"Test-executed job {job['id']}: {job['prompt'][:50]}")


@authorized
async def handle_listcron_command(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Handle /listcron — list all scheduled jobs."""
    settings: Settings = context.bot_data["settings"]

    if not update.message:
        return

    if not settings.cron_enabled:
        await update.message.reply_text("Cron scheduling is disabled.")
        return

    cron_jobs: list[ScheduledJob] = context.bot_data.get("cron_jobs", [])
    text = format_cron_list(jobs=cron_jobs)
    await update.message.reply_text(text)


def process_cron_response(
    *, response: str, settings: Settings, context: ContextTypes.DEFAULT_TYPE
) -> str:
    """Extract cron tags from response, update jobs, return cleaned response."""
    if not settings.cron_enabled:
        return response

    cron_jobs: list[ScheduledJob] = context.bot_data.get("cron_jobs", [])
    scheduler = context.bot_data["scheduler"]
    application = context.bot_data["application"]
    changed = False

    # Process CRON_ADD tags
    for raw_value in extract_cron_add_tags(text=response):
        parsed = parse_cron_add_value(value=raw_value)
        if parsed is None:
            continue
        expression, prompt_text = parsed
        if not validate_cron_expression(expression=expression):
            continue
        job: ScheduledJob = {
            "id": str(uuid.uuid4()),
            "job_type": "cron",
            "expression": expression,
            "prompt": prompt_text,
            "created_at": datetime.now(tz=UTC).isoformat(),
        }
        cron_jobs.append(job)
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
        changed = True
        logger.info(
            f"LLM added cron job {job['id']}: {expression} — {prompt_text[:50]}"
        )

    # Process SCHEDULE tags
    for raw_value in extract_schedule_tags(text=response):
        parsed = parse_schedule_value(value=raw_value)
        if parsed is None:
            continue
        datetime_str, prompt_text = parsed
        dt = parse_schedule_datetime(text=datetime_str)
        if dt is None or dt <= datetime.now(tz=UTC):
            continue
        job = {
            "id": str(uuid.uuid4()),
            "job_type": "once",
            "expression": datetime_str,
            "prompt": prompt_text,
            "created_at": datetime.now(tz=UTC).isoformat(),
        }
        cron_jobs.append(job)
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
        changed = True
        logger.info(
            f"LLM scheduled one-time job {job['id']}: {datetime_str} — {prompt_text[:50]}"
        )

    # Process CRON_REMOVE tags (sort descending to remove from end first)
    remove_indices = sorted(extract_cron_remove_tags(text=response), reverse=True)
    for index in remove_indices:
        if 1 <= index <= len(cron_jobs):
            removed = cron_jobs.pop(index - 1)
            unregister_job(scheduler=scheduler, job_id=removed["id"])
            changed = True
            logger.info(f"LLM removed job {removed['id']}: {removed['prompt'][:50]}")

    if changed:
        context.bot_data["cron_jobs"] = cron_jobs
        save_cron_jobs(cron_file=settings.cron_file, jobs=cron_jobs)

    # Append list if requested
    cleaned = strip_cron_tags(text=response)
    if has_cron_list_tag(text=response):
        job_list = format_cron_list(jobs=cron_jobs)
        cleaned = f"{cleaned}\n\n{job_list}"

    return cleaned
