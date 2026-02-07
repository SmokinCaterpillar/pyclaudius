import contextlib
import logging
import os
import signal
import sys
from pathlib import Path

logger = logging.getLogger(__name__)


def acquire_lock(*, lock_file: Path) -> bool:
    """Acquire a PID lock file. Returns True if lock acquired."""
    if lock_file.exists():
        try:
            existing_pid = int(lock_file.read_text().strip())
            os.kill(existing_pid, 0)
            logger.error(f"Another instance is running (PID {existing_pid})")
            return False
        except (ValueError, ProcessLookupError):
            logger.warning("Removing stale lock file")
        except PermissionError:
            logger.error("Lock file exists and process is running")
            return False

    lock_file.parent.mkdir(parents=True, exist_ok=True)
    lock_file.write_text(str(os.getpid()))
    return True


def release_lock(*, lock_file: Path) -> None:
    """Delete the lock file, ignoring errors."""
    with contextlib.suppress(OSError):
        lock_file.unlink()


def setup_signal_handlers(*, lock_file: Path) -> None:
    """Register SIGINT/SIGTERM handlers that release the lock and exit."""

    def _handler(signum: int, _frame: object) -> None:
        logger.info(f"Received signal {signum}, shutting down")
        release_lock(lock_file=lock_file)
        sys.exit(0)

    signal.signal(signal.SIGINT, _handler)
    signal.signal(signal.SIGTERM, _handler)
