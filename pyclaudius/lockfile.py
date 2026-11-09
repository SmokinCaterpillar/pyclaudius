import contextlib
import logging
import os
import sys
from pathlib import Path
from typing import TextIO

logger = logging.getLogger(__name__)


def _try_lock(*, fd: int) -> bool:
    """Take a non-blocking exclusive OS lock on fd. Returns False if held elsewhere."""
    try:
        if sys.platform == "win32":
            import msvcrt

            msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
        else:
            import fcntl

            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        return False
    return True


def _unlock(*, fd: int) -> None:
    """Release the OS lock on fd."""
    if sys.platform == "win32":
        import msvcrt

        msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
    else:
        import fcntl

        fcntl.flock(fd, fcntl.LOCK_UN)


def acquire_lock(*, lock_file: Path) -> TextIO | None:
    """Lock lock_file for this process. Returns the open handle, or None if taken.

    The OS drops the lock when the process dies, so a crash or hard reset
    never leaves a stale lock. A PID check was rejected: after a reboot the
    old PID can belong to an unrelated process.
    Keep the returned handle open for the whole run.
    """
    lock_file.parent.mkdir(parents=True, exist_ok=True)
    # O_CREAT without O_TRUNC: don't wipe the holder's PID before we own the lock.
    fd = os.open(lock_file, os.O_RDWR | os.O_CREAT, 0o644)
    handle = os.fdopen(fd, "r+")
    if not _try_lock(fd=fd):
        holder = "unknown"
        # Windows blocks reading a locked region, so the PID may be unreadable.
        with contextlib.suppress(OSError):
            holder = handle.read().strip() or holder
        handle.close()
        logger.error(f"Another instance is running (PID {holder})")
        return None

    # The PID is only for humans; the OS lock is what counts.
    handle.seek(0)
    handle.truncate()
    handle.write(str(os.getpid()))
    handle.flush()
    return handle


def release_lock(*, lock_handle: TextIO) -> None:
    """Unlock and close the lock file, ignoring errors.

    The file is kept: unlinking it lets a second process lock a new file
    while a third still holds the old one.
    """
    with contextlib.suppress(OSError, ValueError):
        # msvcrt unlocks from the current position; the lock covers byte 0.
        lock_handle.seek(0)
        _unlock(fd=lock_handle.fileno())
    with contextlib.suppress(OSError):
        lock_handle.close()
