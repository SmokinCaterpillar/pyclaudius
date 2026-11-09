import os
from pathlib import Path

import pytest

from pyclaudius.lockfile import acquire_lock, release_lock


def test_acquire_lock_no_existing(tmp_path: Path) -> None:
    lock_file = tmp_path / "bot.lock"
    handle = acquire_lock(lock_file=lock_file)
    assert handle is not None
    assert int(lock_file.read_text()) == os.getpid()
    release_lock(lock_handle=handle)


def test_acquire_lock_creates_parent_dir(tmp_path: Path) -> None:
    lock_file = tmp_path / "relay" / "bot.lock"
    handle = acquire_lock(lock_file=lock_file)
    assert handle is not None
    release_lock(lock_handle=handle)


def test_acquire_lock_held_returns_none(tmp_path: Path) -> None:
    lock_file = tmp_path / "bot.lock"
    first = acquire_lock(lock_file=lock_file)
    assert first is not None
    # flock conflicts across open file descriptions, even within one process.
    assert acquire_lock(lock_file=lock_file) is None
    # The failed attempt must not wipe the holder's PID.
    assert int(lock_file.read_text()) == os.getpid()
    release_lock(lock_handle=first)


def test_acquire_lock_after_release(tmp_path: Path) -> None:
    lock_file = tmp_path / "bot.lock"
    first = acquire_lock(lock_file=lock_file)
    assert first is not None
    release_lock(lock_handle=first)
    second = acquire_lock(lock_file=lock_file)
    assert second is not None
    release_lock(lock_handle=second)


@pytest.mark.parametrize(
    "content",
    [str(os.getpid()), "99999999", "not-a-pid", ""],
    ids=["live-pid", "dead-pid", "garbage", "empty"],
)
def test_acquire_lock_leftover_file(tmp_path: Path, content: str) -> None:
    # Reboot case: a file left by a dead process never blocks, whatever PID it holds.
    lock_file = tmp_path / "bot.lock"
    lock_file.write_text(content)
    handle = acquire_lock(lock_file=lock_file)
    assert handle is not None
    assert int(lock_file.read_text()) == os.getpid()
    release_lock(lock_handle=handle)


def test_release_lock_keeps_file(tmp_path: Path) -> None:
    lock_file = tmp_path / "bot.lock"
    handle = acquire_lock(lock_file=lock_file)
    assert handle is not None
    release_lock(lock_handle=handle)
    assert lock_file.exists()
    assert handle.closed


def test_release_lock_already_closed(tmp_path: Path) -> None:
    lock_file = tmp_path / "bot.lock"
    handle = acquire_lock(lock_file=lock_file)
    assert handle is not None
    handle.close()
    release_lock(lock_handle=handle)
