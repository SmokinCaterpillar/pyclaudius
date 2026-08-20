import asyncio
import logging
import sys
from contextlib import suppress
from datetime import UTC, datetime
from typing import cast

from pydantic import ValidationError
from telegram import Update
from telegram.ext import (
    Application,
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from pyclaudius.backlog import load_backlog
from pyclaudius.bot_data import BotData
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
    handle_clear_command,
    handle_clearbacklog_command,
    handle_compact_command,
    handle_context_command,
    handle_deleteallreadmail_command,
    handle_document,
    handle_downloadnewmail_command,
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
from pyclaudius.mcp_tools.config import find_free_port
from pyclaudius.mcp_tools.server import create_mcp_server, mcp_tool_names
from pyclaudius.memory import load_memory
from pyclaudius.opencode import API_KEY_ENV
from pyclaudius.opencode_config import build_opencode_config, write_opencode_config
from pyclaudius.session import load_session
from pyclaudius.timezone import load_timezone
from pyclaudius.version import __version__

# Seconds to let the MCP server unwind before giving up on it.
_MCP_SHUTDOWN_TIMEOUT = 5.0


def configure_logging(*, level: int = logging.INFO) -> None:
    """Configure logging, keeping the bot token out of the logs.

    httpx logs every request URL at INFO, and python-telegram-bot puts the bot
    token in the URL path — so INFO-level httpx logging writes the token to the
    journal on every poll.
    """
    logging.basicConfig(
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        level=level,
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)


configure_logging()
logger = logging.getLogger(__name__)


def _on_mcp_task_done(task: asyncio.Task) -> None:
    """Surface MCP server task termination so it doesn't fail silently."""
    if task.cancelled():
        logger.info("MCP server task cancelled")
        return
    exc = task.exception()
    if exc is not None:
        logger.error(f"MCP server task crashed: {exc}", exc_info=exc)
    else:
        logger.warning("MCP server task exited unexpectedly without an error")


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
        task.add_done_callback(_on_mcp_task_done)
        application.bot_data["mcp_task"] = task
        logger.info(f"MCP server started on 127.0.0.1:{mcp_port}")


async def _post_shutdown(application: Application) -> None:
    """Shut down the scheduler and MCP server gracefully."""
    scheduler = application.bot_data.get("scheduler")
    if scheduler is not None:
        scheduler.shutdown(wait=False)
        logger.info("APScheduler shut down")

    mcp_task: asyncio.Task | None = application.bot_data.get("mcp_task")
    if mcp_task is not None:
        mcp_task.cancel()
        # Awaiting the cancellation gives uvicorn a chance to unwind its own
        # tasks. Without it the event loop closes first and asyncio complains
        # that tasks were destroyed while pending.
        with suppress(asyncio.CancelledError, TimeoutError):
            await asyncio.wait_for(mcp_task, timeout=_MCP_SHUTDOWN_TIMEOUT)
        logger.info("MCP server shut down")


async def _error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Log exceptions and notify the user."""
    logger.error(
        f"Exception while handling update: {context.error}", exc_info=context.error
    )
    if isinstance(update, Update) and update.message:
        await update.message.reply_text(f"Error: {context.error}")


# Settings that existed before the move to opencode. They are rejected as
# unknown input, so an un-migrated .env fails with a pydantic traceback rather
# than anything actionable — hence the explicit hint below.
# Retired setting -> its replacement, or None when the feature is simply gone.
_RETIRED_SETTINGS: dict[str, str | None] = {
    "claude_path": "OPENCODE_PATH",
    "claude_timeout": "OPENCODE_TIMEOUT",
    "claude_model": "OPENCODE_MODEL",
    "claude_effort": None,
    "tmux_session": None,
}

_REMOVED_REASON: dict[str, str] = {
    "claude_effort": "opencode accepts any --variant without validating it",
    "tmux_session": "the tmux keepalive is gone",
}


def _retired_setting_message(*, name: str) -> str:
    """Explain one retired setting: renamed to something, or dropped outright."""
    replacement = _RETIRED_SETTINGS[name]
    if replacement is not None:
        return f"{name.upper()} has been renamed — use {replacement} instead."
    reason = _REMOVED_REASON.get(name, "the feature was removed")
    return f"{name.upper()} is no longer supported — {reason}. Delete the line."


def _load_settings() -> Settings:
    """Load settings, translating an un-migrated .env into a usable message."""
    try:
        return Settings()
    except ValidationError as e:
        retired = [
            str(error["loc"][0])
            for error in e.errors()
            if error.get("type") == "extra_forbidden"
            and str(error["loc"][0]) in _RETIRED_SETTINGS
        ]
        if not retired:
            raise
        for name in retired:
            logger.error(_retired_setting_message(name=name))
        logger.error("Remove the retired entries from .env and restart.")
        sys.exit(1)


def main() -> None:
    settings = _load_settings()
    logger.info(f"Started pyclaudius {__version__} with {settings!s}")

    if not settings.tensorx_api_key:
        logger.error(
            f"{API_KEY_ENV} is not set — opencode cannot reach the model provider."
            " Add it to .env and restart."
        )
        sys.exit(1)

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
        logger.info(
            f"Backlog enabled with {len(app.bot_data['backlog'])} pending item(s)"
        )
    else:
        app.bot_data["backlog"] = []
        logger.info("Backlog disabled")

    app.bot_data["user_timezone"] = load_timezone(timezone_file=settings.timezone_file)
    logger.info(f"User timezone: {app.bot_data['user_timezone'] or 'UTC (default)'}")

    # opencode_lock is always created (MCP tools may mutate shared state)
    app.bot_data["opencode_lock"] = asyncio.Lock()
    app.bot_data["last_run"] = {}
    app.bot_data["_scheduled_update_ids"] = set()

    # Cron / scheduling setup
    if settings.cron_enabled:
        scheduler = create_scheduler()
        app.bot_data["scheduler"] = scheduler

    if settings.cron_enabled:
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

    # MCP server setup (always on — reached by opencode via the generated config)
    mcp_port = find_free_port()
    mcp_server = create_mcp_server(bot_data=cast(BotData, app.bot_data))
    tool_names = mcp_tool_names(settings=settings)
    app.bot_data["mcp_server"] = mcp_server
    app.bot_data["mcp_port"] = mcp_port
    app.bot_data["mcp_tool_names"] = tool_names
    logger.info(f"MCP enabled on port {mcp_port} with {len(tool_names)} tool(s)")

    # The config is regenerated every start: it carries this run's MCP port.
    write_opencode_config(
        path=settings.opencode_config_file,
        config=build_opencode_config(
            settings=settings, mcp_port=mcp_port, mcp_tool_names=tool_names
        ),
    )

    app.add_handler(CommandHandler("help", handle_help_command))
    app.add_handler(CommandHandler("clear", handle_clear_command))
    app.add_handler(CommandHandler("compact", handle_compact_command))
    app.add_handler(CommandHandler("context", handle_context_command))
    app.add_handler(CommandHandler("timezone", handle_timezone_command))
    app.add_handler(CommandHandler("remember", handle_remember_command))
    app.add_handler(CommandHandler("listmemory", handle_listmemory_command))
    app.add_handler(CommandHandler("forget", handle_forget_command))
    app.add_handler(CommandHandler("addcron", handle_addcron_command))
    app.add_handler(CommandHandler("schedule", handle_schedule_command))
    app.add_handler(CommandHandler("listcron", handle_listcron_command))
    app.add_handler(CommandHandler("removecron", handle_removecron_command))
    app.add_handler(CommandHandler("testcron", handle_testcron_command))
    app.add_handler(CommandHandler("downloadnewmail", handle_downloadnewmail_command))
    app.add_handler(
        CommandHandler("deleteallreadmail", handle_deleteallreadmail_command)
    )
    app.add_handler(CommandHandler("listbacklog", handle_listbacklog_command))
    app.add_handler(CommandHandler("clearbacklog", handle_clearbacklog_command))
    app.add_handler(CommandHandler("replaybacklog", handle_replaybacklog_command))
    app.add_handler(CommandHandler("replayone", handle_replayone_command))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    app.add_handler(MessageHandler(filters.Document.ALL, handle_document))

    app.add_error_handler(_error_handler)

    logger.info(f"Bot starting with relay dir: {settings.relay_dir}")

    try:
        app.run_polling()
    finally:
        release_lock(lock_file=settings.lock_file)


if __name__ == "__main__":
    main()
