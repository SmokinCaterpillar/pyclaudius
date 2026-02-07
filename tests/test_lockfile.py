import os

from pyclaudius.lockfile import acquire_lock, release_lock


def test_acquire_lock_no_existing(tmp_path):
    lock_file = tmp_path / "bot.lock"
    assert acquire_lock(lock_file=lock_file) is True
    assert lock_file.exists()
    assert int(lock_file.read_text()) == os.getpid()


def test_acquire_lock_stale_pid(tmp_path):
    lock_file = tmp_path / "bot.lock"
    lock_file.write_text("99999999")
    assert acquire_lock(lock_file=lock_file) is True


def test_acquire_lock_live_pid(tmp_path):
    lock_file = tmp_path / "bot.lock"
    lock_file.write_text(str(os.getpid()))
    assert acquire_lock(lock_file=lock_file) is False


def test_acquire_lock_invalid_content(tmp_path):
    lock_file = tmp_path / "bot.lock"
    lock_file.write_text("not-a-pid")
    assert acquire_lock(lock_file=lock_file) is True


def test_release_lock(tmp_path):
    lock_file = tmp_path / "bot.lock"
    lock_file.write_text(str(os.getpid()))
    release_lock(lock_file=lock_file)
    assert not lock_file.exists()


def test_release_lock_missing_file(tmp_path):
    lock_file = tmp_path / "bot.lock"
    release_lock(lock_file=lock_file)
