"""Database setup and migration helpers."""

from __future__ import annotations

import asyncio
import sqlite3
import time
from pathlib import Path
from typing import TYPE_CHECKING

from alembic import command
from alembic.config import Config
from sqlalchemy.engine import make_url

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncEngine

from tonewatch.storage.models import Base, create_database

__all__ = [
    "Base",
    "DatabaseCheckpointError",
    "checkpoint_database",
    "create_database",
    "create_database_schema",
    "upgrade_database",
    "vacuum_database",
]
CHECKPOINT_COLUMNS = 3


class DatabaseCheckpointError(RuntimeError):
    """The live SQLite database could not be checkpointed in time."""

    def __init__(self) -> None:
        """Build the generic checkpoint failure message."""
        super().__init__("database checkpoint failed")


class DatabaseFileMissingError(DatabaseCheckpointError):
    """The configured SQLite file does not exist."""

    def __init__(self) -> None:
        super().__init__()
        self.args = ("database checkpoint file does not exist",)


class DatabaseCheckpointTimeoutError(DatabaseCheckpointError):
    """The SQLite writer did not release the database before the deadline."""

    def __init__(self) -> None:
        """Build the bounded timeout message."""
        super().__init__()
        self.args = ("database checkpoint timed out: database is busy",)


class DatabaseCheckpointInvalidTimeoutError(DatabaseCheckpointError):
    """The checkpoint timeout is not usable."""

    def __init__(self) -> None:
        """Build the invalid timeout message."""
        super().__init__()
        self.args = ("database checkpoint timeout must be positive",)


def checkpoint_database(path: Path, timeout_s: float = 10.0) -> tuple[int, int, int]:
    """Checkpoint a live WAL database, retrying transient writer contention."""
    if not path.is_file():
        raise DatabaseFileMissingError
    if timeout_s <= 0:
        raise DatabaseCheckpointInvalidTimeoutError
    deadline = time.monotonic() + timeout_s
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise DatabaseCheckpointTimeoutError
        try:
            connection = sqlite3.connect(path, timeout=min(remaining, 0.25))
            try:
                row = connection.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()
            finally:
                connection.close()
            if row is not None and len(row) == CHECKPOINT_COLUMNS and int(row[0]) == 0:
                return int(row[0]), int(row[1]), int(row[2])
        except sqlite3.OperationalError as exc:
            if "busy" not in str(exc).casefold() and "locked" not in str(exc).casefold():
                raise DatabaseCheckpointError from exc
        time.sleep(min(0.05, max(0.0, deadline - time.monotonic())))


def vacuum_database(path: Path) -> tuple[int, int]:
    """Vacuum SQLite in a worker thread and return file size before/after."""
    if not path.is_file():
        raise DatabaseFileMissingError
    before = path.stat().st_size
    connection = sqlite3.connect(path, timeout=0.25)
    try:
        connection.execute("VACUUM")
    except sqlite3.OperationalError as exc:
        if "busy" in str(exc).casefold() or "locked" in str(exc).casefold():
            raise DatabaseCheckpointTimeoutError from exc
        raise DatabaseCheckpointError from exc
    finally:
        connection.close()
    return before, path.stat().st_size


async def create_database_schema(engine: AsyncEngine) -> None:
    """Create the current schema for a fresh test or development database."""
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)


async def upgrade_database(engine: AsyncEngine) -> None:
    """Run Alembic's head migration for an async engine in a worker thread."""
    url = make_url(str(engine.url)).set(drivername="sqlite")
    project_root = Path(__file__).parents[3]
    alembic_ini = project_root / "alembic.ini"
    if not alembic_ini.is_file():
        alembic_ini = project_root / "_internal" / "alembic.ini"
    config = Config(str(alembic_ini))
    config.set_main_option("script_location", str(Path(__file__).parent / "migrations"))
    config.set_main_option("sqlalchemy.url", url.render_as_string(hide_password=False))
    await asyncio.to_thread(command.upgrade, config, "head")
