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

from pyclaudius.backlog import load_backlog
from pyclaudius.config import Settings, ensure_dirs
from pyclaudius.cron.handlers import (
    handle_addcron_command,
    handle_listcron_command,
    handle_removecron_command,
    handle_schedule_command,
    handle_testcron_command,
)
from pyclaudius.cron.scheduler import (
    create_scheduler,
    execute_scheduled_job,
    parse_schedule_datetime,
    register_job,
)
from pyclaudius.cron.store import load_cron_jobs, save_cron_jobs
from pyclaudius.handlers import (
    handle_clearbacklog_command,
    handle_document,
    handle_forget_command,
    handle_help_command,
    handle_listbacklog_command,
    handle_listmemory_command,
    handle_photo,
    handle_remember_command,
    handle_replaybacklog_command,
    handle_replayone_command,
    handle_text,
    handle_timezone_command,
)
from pyclaudius.lockfile import acquire_lock, release_lock, setup_signal_handlers
from pyclaudius.mcp_tools.config import (
    find_free_port,
    register_mcp_server,
    unregister_mcp_server,
)
from pyclaudius.mcp_tools.server import create_mcp_server, get_allowed_tools_wildcard
from pyclaudius.memory import load_memory
from pyclaudius.session import load_session
from pyclaudius.timezone import load_timezone
from pyclaudius.version import __version__

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


async def _post_init(application: Application) -> None:
    """Start the scheduler and MCP server after the event loop is running."""
    scheduler = application.bot_data.get("scheduler")
    if scheduler is not None:
        scheduler.start()
        logger.info("APScheduler started")

    mcp_server = application.bot_data.get("mcp_server")
    if mcp_server is not None:
        mcp_port = application.bot_data["mcp_port"]
        task = asyncio.create_task(
            mcp_server.run_http_async(
                host="127.0.0.1",
                port=mcp_port,
                show_banner=False,
            )
        )
        application.bot_data["mcp_task"] = task
        logger.info(f"MCP server started on 127.0.0.1:{mcp_port}")

        # Register with Claude CLI (workaround for --mcp-config hang bug).
        # Unregister first to clear any stale entry from a previous run.
        settings = application.bot_data["settings"]
        work_dir = str(settings.claude_work_dir)
        await unregister_mcp_server(claude_path=settings.claude_path, cwd=work_dir)
        registered = await register_mcp_server(
            claude_path=settings.claude_path, port=mcp_port, cwd=work_dir
        )
        if registered:
            logger.info("Registered MCP server with Claude CLI")
        else:
            logger.error("Failed to register MCP server with Claude CLI")


async def _post_shutdown(application: Application) -> None:
    """Shut down the scheduler and MCP server gracefully."""
    scheduler = application.bot_data.get("scheduler")
    if scheduler is not None:
        scheduler.shutdown(wait=False)
        logger.info("APScheduler shut down")

    mcp_task: asyncio.Task | None = application.bot_data.get("mcp_task")
    if mcp_task is not None:
        mcp_task.cancel()
        logger.info("MCP server shut down")

    settings = application.bot_data["settings"]
    await unregister_mcp_server(
        claude_path=settings.claude_path, cwd=str(settings.claude_work_dir)
    )
    logger.info("Unregistered MCP server from Claude CLI")


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

    if settings.backlog_enabled:
        app.bot_data["backlog"] = load_backlog(backlog_file=settings.backlog_file)
        logger.info(f"Backlog enabled with {len(app.bot_data['backlog'])} pending item(s)")
    else:
        app.bot_data["backlog"] = []
        logger.info("Backlog disabled")

    app.bot_data["user_timezone"] = load_timezone(timezone_file=settings.timezone_file)
    logger.info(f"User timezone: {app.bot_data['user_timezone'] or 'UTC (default)'}")

    # claude_lock is always created (MCP tools may mutate shared state)
    app.bot_data["claude_lock"] = asyncio.Lock()

    # Cron / scheduling setup
    if settings.cron_enabled:
        scheduler = create_scheduler()
        app.bot_data["scheduler"] = scheduler

        cron_jobs = load_cron_jobs(cron_file=settings.cron_file)

        # Filter out past one-time jobs
        now = datetime.now(tz=UTC)
        valid_jobs = []
        for job in cron_jobs:
            if job["job_type"] == "once":
                dt = parse_schedule_datetime(
                    text=job["expression"], timezone=job.get("timezone")
                )
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

    # MCP server setup (always on — registered with Claude CLI in _post_init)
    mcp_port = find_free_port()
    mcp_server = create_mcp_server(bot_data=app.bot_data)
    app.bot_data["mcp_server"] = mcp_server
    app.bot_data["mcp_port"] = mcp_port
    app.bot_data["mcp_allowed_tools"] = [get_allowed_tools_wildcard()]
    logger.info(f"MCP enabled on port {mcp_port}")

    app.add_handler(CommandHandler("help", handle_help_command))
    app.add_handler(CommandHandler("timezone", handle_timezone_command))
    app.add_handler(CommandHandler("remember", handle_remember_command))
    app.add_handler(CommandHandler("listmemory", handle_listmemory_command))
    app.add_handler(CommandHandler("forget", handle_forget_command))
    app.add_handler(CommandHandler("addcron", handle_addcron_command))
    app.add_handler(CommandHandler("schedule", handle_schedule_command))
    app.add_handler(CommandHandler("listcron", handle_listcron_command))
    app.add_handler(CommandHandler("removecron", handle_removecron_command))
    app.add_handler(CommandHandler("testcron", handle_testcron_command))
    app.add_handler(CommandHandler("listbacklog", handle_listbacklog_command))
    app.add_handler(CommandHandler("clearbacklog", handle_clearbacklog_command))
    app.add_handler(CommandHandler("replaybacklog", handle_replaybacklog_command))
    app.add_handler(CommandHandler("replayone", handle_replayone_command))
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
