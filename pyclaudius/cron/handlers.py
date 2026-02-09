import logging

from telegram import Update
from telegram.ext import ContextTypes

from pyclaudius.config import Settings
from pyclaudius.cron.models import ScheduledJob
from pyclaudius.cron.scheduler import execute_scheduled_job
from pyclaudius.operations import (
    add_cron_job,
    list_cron_jobs,
    remove_cron_job,
    schedule_once,
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

    try:
        result = add_cron_job(
            expression=expression, prompt_text=prompt_text, bot_data=context.bot_data
        )
    except ValueError as e:
        await update.message.reply_text(str(e))
        return

    await update.message.reply_text(result)


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

    try:
        result = schedule_once(
            datetime_str=datetime_str,
            prompt_text=prompt_text,
            bot_data=context.bot_data,
        )
    except ValueError as e:
        await update.message.reply_text(str(e))
        return

    await update.message.reply_text(result)


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

    try:
        result = remove_cron_job(index=index, bot_data=context.bot_data)
    except ValueError as e:
        await update.message.reply_text(str(e))
        return

    await update.message.reply_text(result)


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

    text = list_cron_jobs(bot_data=context.bot_data)
    await update.message.reply_text(text)
