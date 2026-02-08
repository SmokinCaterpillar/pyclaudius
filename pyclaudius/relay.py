import asyncio
import logging
import sys
from datetime import UTC, datetime

from telegram.ext import (
    Application,
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    filters,
)

from pyclaudius.config import Settings, ensure_dirs
from pyclaudius.cron.handlers import (
    handle_addcron_command,
    handle_listcron_command,
    handle_removecron_command,
    handle_schedule_command,
)
from pyclaudius.cron.scheduler import (
    create_scheduler,
    execute_scheduled_job,
    parse_schedule_datetime,
    register_job,
)
from pyclaudius.cron.store import load_cron_jobs, save_cron_jobs
from pyclaudius.handlers import (
    handle_document,
    handle_forget_command,
    handle_help_command,
    handle_listmemory_command,
    handle_photo,
    handle_remember_command,
    handle_text,
)
from pyclaudius.lockfile import acquire_lock, release_lock, setup_signal_handlers
from pyclaudius.memory import load_memory
from pyclaudius.session import load_session
from pyclaudius.version import __version__

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


async def _post_init(application: Application) -> None:
    """Start the scheduler after the event loop is running."""
    scheduler = application.bot_data.get("scheduler")
    if scheduler is not None:
        scheduler.start()
        logger.info("APScheduler started")


async def _post_shutdown(application: Application) -> None:
    """Shut down the scheduler gracefully."""
    scheduler = application.bot_data.get("scheduler")
    if scheduler is not None:
        scheduler.shutdown(wait=False)
        logger.info("APScheduler shut down")


def main() -> None:
    settings = Settings()
    logger.info(f"Started pyclaudius {__version__} with {settings!s}")
    ensure_dirs(settings=settings)

    if not acquire_lock(lock_file=settings.lock_file):
        logger.error("Another instance is running")
        sys.exit(1)

    setup_signal_handlers(lock_file=settings.lock_file)

    app = (
        ApplicationBuilder()
        .token(settings.telegram_bot_token)
        .post_init(_post_init)
        .post_shutdown(_post_shutdown)
        .build()
    )
    app.bot_data["settings"] = settings
    app.bot_data["session"] = load_session(session_file=settings.session_file)
    app.bot_data["application"] = app

    if settings.memory_enabled:
        app.bot_data["memory"] = load_memory(memory_file=settings.memory_file)
        logger.info(f"Memory enabled with {len(app.bot_data['memory'])} stored fact(s)")
    else:
        app.bot_data["memory"] = []
        logger.info("Memory disabled")

    # Cron / scheduling setup
    if settings.cron_enabled:
        scheduler = create_scheduler()
        app.bot_data["scheduler"] = scheduler
        app.bot_data["claude_lock"] = asyncio.Lock()

        cron_jobs = load_cron_jobs(cron_file=settings.cron_file)

        # Filter out past one-time jobs
        now = datetime.now(tz=UTC)
        valid_jobs = []
        for job in cron_jobs:
            if job["job_type"] == "once":
                dt = parse_schedule_datetime(text=job["expression"])
                if dt is not None and dt <= now:
                    logger.info(
                        f"Removing past one-time job {job['id']}: {job['prompt'][:50]}"
                    )
                    continue
            valid_jobs.append(job)

        if len(valid_jobs) != len(cron_jobs):
            save_cron_jobs(cron_file=settings.cron_file, jobs=valid_jobs)

        app.bot_data["cron_jobs"] = valid_jobs

        # Register all valid jobs with the scheduler
        for job in valid_jobs:
            register_job(
                scheduler=scheduler,
                job=job,
                callback=execute_scheduled_job,
                callback_kwargs={
                    "application": app,
                    "chat_id": settings.telegram_user_id,
                    "prompt_text": job["prompt"],
                    "job_id": job["id"],
                    "job_type": job["job_type"],
                },
            )

        logger.info(f"Cron enabled with {len(valid_jobs)} scheduled job(s)")
    else:
        app.bot_data["cron_jobs"] = []
        logger.info("Cron disabled")

    app.add_handler(CommandHandler("help", handle_help_command))
    app.add_handler(CommandHandler("remember", handle_remember_command))
    app.add_handler(CommandHandler("listmemory", handle_listmemory_command))
    app.add_handler(CommandHandler("forget", handle_forget_command))
    app.add_handler(CommandHandler("addcron", handle_addcron_command))
    app.add_handler(CommandHandler("schedule", handle_schedule_command))
    app.add_handler(CommandHandler("listcron", handle_listcron_command))
    app.add_handler(CommandHandler("removecron", handle_removecron_command))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    app.add_handler(MessageHandler(filters.Document.ALL, handle_document))

    logger.info(f"Bot starting with relay dir: {settings.relay_dir}")

    try:
        app.run_polling()
    finally:
        release_lock(lock_file=settings.lock_file)


if __name__ == "__main__":
    main()
