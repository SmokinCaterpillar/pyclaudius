import logging
import sys

from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters

from pyclaudius.config import Settings, ensure_dirs
from pyclaudius.handlers import (
    handle_document,
    handle_forget_command,
    handle_remember_command,
    handle_photo,
    handle_text,
)
from pyclaudius.lockfile import acquire_lock, release_lock, setup_signal_handlers
from pyclaudius.memory import load_memory
from pyclaudius.session import load_session

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


def main() -> None:
    settings = Settings()
    logger.info(f"Started with {str(settings)}")
    ensure_dirs(settings=settings)

    if not acquire_lock(lock_file=settings.lock_file):
        logger.error("Another instance is running")
        sys.exit(1)

    setup_signal_handlers(lock_file=settings.lock_file)

    app = ApplicationBuilder().token(settings.telegram_bot_token).build()
    app.bot_data["settings"] = settings
    app.bot_data["session"] = load_session(session_file=settings.session_file)

    if settings.memory_enabled:
        app.bot_data["memory"] = load_memory(memory_file=settings.memory_file)
        logger.info(f"Memory enabled with {len(app.bot_data['memory'])} stored fact(s)")
    else:
        app.bot_data["memory"] = []
        logger.info("Memory disabled")

    app.add_handler(CommandHandler("remember", handle_remember_command))
    app.add_handler(CommandHandler("forget", handle_forget_command))
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
