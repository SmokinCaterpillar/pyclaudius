import logging
from datetime import UTC, datetime

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.date import DateTrigger
from telegram import Chat, Message, Update, User
from telegram.ext import Application

from pyclaudius.cron.models import ScheduledJob
from pyclaudius.cron.store import save_cron_jobs

logger = logging.getLogger(__name__)

_update_counter = 0


def create_scheduler() -> AsyncIOScheduler:
    """Create and return a new AsyncIOScheduler (not started)."""
    return AsyncIOScheduler()


def register_job(
    *,
    scheduler: AsyncIOScheduler,
    job: ScheduledJob,
    callback: object,
    callback_kwargs: dict[str, object],
) -> None:
    """Register a job with the scheduler using the appropriate trigger."""
    if job["job_type"] == "cron":
        trigger = CronTrigger.from_crontab(job["expression"])
    else:
        dt = parse_schedule_datetime(text=job["expression"])
        if dt is None:
            logger.warning(f"Invalid datetime for job {job['id']}: {job['expression']}")
            return
        trigger = DateTrigger(run_date=dt)

    scheduler.add_job(
        callback,
        trigger=trigger,
        id=job["id"],
        kwargs=callback_kwargs,
        replace_existing=True,
    )
    logger.info(f"Registered {job['job_type']} job {job['id']}: {job['prompt'][:50]}")


def unregister_job(*, scheduler: AsyncIOScheduler, job_id: str) -> None:
    """Remove a job from the scheduler if it exists."""
    try:
        scheduler.remove_job(job_id)
    except Exception:
        logger.warning(
            f"Job {job_id} not found in scheduler (already removed or expired)"
        )


def validate_cron_expression(*, expression: str) -> bool:
    """Check if a cron expression is valid (5-field)."""
    try:
        CronTrigger.from_crontab(expression)
        return True
    except (ValueError, KeyError):
        return False


def parse_schedule_datetime(*, text: str) -> datetime | None:
    """Parse a datetime string. Supports '%Y-%m-%d %H:%M' and ISO 8601."""
    formats = [
        "%Y-%m-%d %H:%M",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%dT%H:%M",
        "%Y-%m-%d %H:%M:%S",
    ]
    for fmt in formats:
        try:
            dt = datetime.strptime(text.strip(), fmt)  # noqa: DTZ007
            return dt.replace(tzinfo=UTC)
        except ValueError:
            continue
    return None


async def execute_scheduled_job(
    *,
    application: Application,
    chat_id: str,
    prompt_text: str,
    job_id: str,
    job_type: str,
    is_test: bool = False,
) -> None:
    """Execute a scheduled job by dispatching a synthetic Update through the application."""
    global _update_counter
    _update_counter += 1

    logger.info(f"Executing scheduled job {job_id}: {prompt_text[:50]}")

    user = User(id=int(chat_id), is_bot=False, first_name="Scheduled")
    chat = Chat(id=int(chat_id), type="private")
    message = Message(
        message_id=_update_counter,
        date=datetime.now(tz=UTC),
        chat=chat,
        from_user=user,
        text=prompt_text,
    )
    message.set_bot(application.bot)
    update = Update(update_id=_update_counter, message=message)

    scheduled_ids: set[int] = application.bot_data.setdefault(
        "_scheduled_update_ids", set()
    )
    scheduled_ids.add(update.update_id)

    await application.process_update(update)

    if job_type == "once" and not is_test:
        cron_jobs: list[ScheduledJob] = application.bot_data.get("cron_jobs", [])
        cron_jobs = [j for j in cron_jobs if j["id"] != job_id]
        application.bot_data["cron_jobs"] = cron_jobs
        settings = application.bot_data["settings"]
        save_cron_jobs(cron_file=settings.cron_file, jobs=cron_jobs)
        logger.info(f"One-time job {job_id} completed and removed")
