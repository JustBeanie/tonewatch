"""Safe, atomic YAML configuration persistence."""

import asyncio
import hashlib
import os
import tempfile
from contextlib import suppress
from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

from tonewatch.config.models import AppConfig

_file_locker: Any = __import__("msvcrt" if os.name == "nt" else "fcntl")


class ConfigError(ValueError):
    """Raised when the YAML configuration cannot be read or validated."""


class ConfigConflictError(ConfigError):
    """Raised when a write is based on an obsolete configuration revision."""


_PROCESS_LOCKS: dict[str, asyncio.Lock] = {}


def _process_lock(path: Path) -> asyncio.Lock:
    return _PROCESS_LOCKS.setdefault(str(path.resolve()), asyncio.Lock())


def _acquire_file_lock(handle: Any) -> None:
    if os.name == "nt":
        handle.seek(0)
        _file_locker.locking(handle.fileno(), _file_locker.LK_LOCK, 1)
        return
    _file_locker.flock(handle.fileno(), _file_locker.LOCK_EX)


def _release_file_lock(handle: Any) -> None:
    if os.name == "nt":
        handle.seek(0)
        _file_locker.locking(handle.fileno(), _file_locker.LK_UNLCK, 1)
        return
    _file_locker.flock(handle.fileno(), _file_locker.LOCK_UN)


class ConfigStore:
    """Load and atomically save the application YAML configuration."""

    def __init__(self, data_dir: Path) -> None:
        self.data_dir = data_dir
        self.path = data_dir / "config.yaml"

    def load(self) -> AppConfig:
        """Load config, creating a default file on first run."""
        if not self.path.exists():
            config = AppConfig()
            self.save(config)
            return config
        try:
            with self.path.open(encoding="utf-8") as handle:
                raw: Any = yaml.safe_load(handle)
            return AppConfig.model_validate(raw or {})
        except yaml.YAMLError as exc:
            raise ConfigError(f"invalid YAML in {self.path}: {exc}") from exc
        except ValidationError as exc:
            raise ConfigError(f"invalid configuration in {self.path}: {exc}") from exc

    def etag(self) -> str:
        """Return the strong revision for the current on-disk configuration."""
        if not self.path.exists():
            return '"empty"'
        return '"sha256-' + hashlib.sha256(self.path.read_bytes()).hexdigest() + '"'

    async def save_async(self, config: AppConfig, *, expected_etag: str | None = None) -> str:
        """Save under process and inter-process locks with optimistic concurrency."""
        async with _process_lock(self.path):
            self.data_dir.mkdir(parents=True, exist_ok=True)
            lock_path = self.path.with_suffix(".yaml.lock")
            with lock_path.open("a+b") as lock_handle:
                await asyncio.to_thread(_acquire_file_lock, lock_handle)
                try:
                    current = self.etag()
                    if expected_etag is not None and expected_etag != current:
                        raise ConfigConflictError("configuration revision does not match If-Match")
                    self._save_unlocked(config)
                    return self.etag()
                finally:
                    await asyncio.to_thread(_release_file_lock, lock_handle)

    def save(self, config: AppConfig) -> None:
        """Write config, retaining a backup and replacing atomically."""
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self._save_unlocked(config)

    def _save_unlocked(self, config: AppConfig) -> None:
        payload = yaml.safe_dump(config.model_dump(mode="json"), sort_keys=False)
        if self.path.exists():
            backup = self.path.with_suffix(".yaml.bak")
            backup.write_bytes(self.path.read_bytes())
        fd, temporary = tempfile.mkstemp(prefix=".config.", suffix=".tmp", dir=self.data_dir)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self.path)
        except OSError as exc:
            with suppress(OSError):
                Path(temporary).unlink(missing_ok=True)
            raise ConfigError(f"could not atomically save {self.path}: {exc}") from exc
