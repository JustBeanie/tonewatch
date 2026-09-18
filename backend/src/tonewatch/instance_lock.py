"""Lifetime lock protecting a ToneWatch data directory from concurrent instances."""

from __future__ import annotations

import os
from typing import TYPE_CHECKING, Any, NoReturn

if TYPE_CHECKING:
    from pathlib import Path

_locker: Any = __import__("msvcrt" if os.name == "nt" else "fcntl")


class InstanceRunningError(RuntimeError):
    """The data directory is already owned by another ToneWatch process."""

    def __init__(self) -> None:
        """Build the stable running-instance error."""
        super().__init__("ToneWatch is already running for this data directory")


def _reject_running() -> NoReturn:
    raise InstanceRunningError


def acquire_instance_lock(data_dir: Path) -> Any:
    """Take a nonblocking OS lock and write the owning PID."""
    data_dir.mkdir(parents=True, exist_ok=True)
    path = data_dir / "tonewatch.pid.lock"
    handle = path.open("a+b")
    try:
        handle.seek(0)
        handle.write(b"0")
        handle.flush()
        handle.seek(0)
        if os.name == "nt":
            _locker.locking(handle.fileno(), _locker.LK_NBLCK, 1)
        else:
            _locker.flock(handle.fileno(), _locker.LOCK_EX | _locker.LOCK_NB)
        handle.seek(0)
        handle.truncate()
        handle.write(str(os.getpid()).encode("ascii"))
        handle.flush()
    except OSError as exc:
        handle.close()
        try:
            _reject_running()
        except InstanceRunningError as error:
            raise error from exc
    else:
        return handle


def release_instance_lock(handle: Any) -> None:
    """Release a lifetime lock without deleting the stale-safe lock file."""
    try:
        if os.name == "nt":
            handle.seek(0)
            _locker.locking(handle.fileno(), _locker.LK_UNLCK, 1)
        else:
            _locker.flock(handle.fileno(), _locker.LOCK_UN)
    finally:
        handle.close()
