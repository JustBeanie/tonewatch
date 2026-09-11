"""M1.3 database tests."""

import asyncio
from datetime import UTC, datetime
from pathlib import Path

from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from sqlalchemy import create_engine, inspect
from sqlalchemy.engine import URL

from tonewatch.storage.models import Base, create_database
from tonewatch.storage.repository import create_call


def test_async_sqlite_wal_and_repository(tmp_path: Path) -> None:
    async def run() -> None:
        engine, sessions = create_database(f"sqlite+aiosqlite:///{tmp_path / 'db.sqlite'}")
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
            assert await connection.run_sync(lambda conn: inspect(conn).get_table_names()) == [
                "alert_attempts",
                "call_tone_sets",
                "calls",
                "recordings",
            ]
        async with sessions() as session:
            record = await create_call(session, source_id="scanner", started_at=datetime.now(UTC))
            await session.commit()
            assert record.source_id == "scanner"
        await engine.dispose()

    asyncio.run(run())


def test_initial_migration_matches_metadata(tmp_path: Path) -> None:
    """Upgrade an empty database and ensure Alembic sees no schema drift."""
    database = tmp_path / "migration.sqlite"
    config = Config(str(Path(__file__).parents[2] / "alembic.ini"))
    config.set_main_option(
        "script_location",
        str(Path(__file__).parents[2] / "src" / "tonewatch" / "storage" / "migrations"),
    )
    config.set_main_option(
        "sqlalchemy.url",
        URL.create("sqlite", database=str(database)).render_as_string(hide_password=False),
    )
    command.upgrade(config, "head")
    engine = create_engine(f"sqlite:///{database}")
    with engine.connect() as connection:
        migration_context = MigrationContext.configure(connection)
        assert compare_metadata(migration_context, Base.metadata) == []
    engine.dispose()
