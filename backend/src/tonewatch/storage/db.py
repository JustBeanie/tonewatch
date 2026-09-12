"""Database setup and migration helpers."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import TYPE_CHECKING

from alembic import command
from alembic.config import Config
from sqlalchemy.engine import make_url

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncEngine

from tonewatch.storage.models import Base, create_database

__all__ = ["Base", "create_database", "create_database_schema", "upgrade_database"]


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
