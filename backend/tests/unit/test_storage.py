"""M1.3 database tests."""

import asyncio
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from sqlalchemy import create_engine, inspect, text
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
                "audit_events",
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


def test_upgrade_from_0001_database_adds_phase_column(tmp_path: Path) -> None:
    """An installation stamped at 0001 receives phase without losing old rows."""
    database = tmp_path / "upgrade.sqlite"
    config = Config(str(Path(__file__).parents[2] / "alembic.ini"))
    config.set_main_option(
        "script_location",
        str(Path(__file__).parents[2] / "src" / "tonewatch" / "storage" / "migrations"),
    )
    config.set_main_option(
        "sqlalchemy.url",
        URL.create("sqlite", database=str(database)).render_as_string(hide_password=False),
    )
    command.upgrade(config, "0001_initial")

    call_id = uuid4().hex
    engine = create_engine(f"sqlite:///{database}")
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO calls (id, started_at, source_id, status) "
                "VALUES (:id, :started_at, :source_id, :status)"
            ),
            {
                "id": call_id,
                "started_at": datetime.now(UTC).isoformat(),
                "source_id": "legacy",
                "status": "active",
            },
        )
        connection.execute(
            text(
                "INSERT INTO alert_attempts "
                "(call_id, target_id, attempt_no, ok, status_code, error, created_at) "
                "VALUES (:call_id, :target_id, :attempt_no, :ok, :status_code, :error, :created_at)"
            ),
            {
                "call_id": call_id,
                "target_id": "legacy-target",
                "attempt_no": 1,
                "ok": 1,
                "status_code": 200,
                "error": None,
                "created_at": datetime.now(UTC).isoformat(),
            },
        )
    engine.dispose()

    command.upgrade(config, "head")
    engine = create_engine(f"sqlite:///{database}")
    with engine.connect() as connection:
        columns = {column["name"] for column in inspect(connection).get_columns("alert_attempts")}
        assert "phase" in columns
        old_row = connection.execute(
            text("SELECT phase FROM alert_attempts WHERE target_id = 'legacy-target'")
        ).one()
        assert old_row.phase == "unknown"
        connection.execute(
            text(
                "INSERT INTO alert_attempts "
                "(call_id, target_id, phase, attempt_no, ok, created_at) "
                "VALUES (:call_id, :target_id, :phase, :attempt_no, :ok, :created_at)"
            ),
            {
                "call_id": call_id,
                "target_id": "new-target",
                "phase": "pre_alert",
                "attempt_no": 1,
                "ok": 1,
                "created_at": datetime.now(UTC).isoformat(),
            },
        )
        assert (
            connection.execute(
                text("SELECT phase FROM alert_attempts WHERE target_id = 'new-target'")
            ).scalar_one()
            == "pre_alert"
        )
    engine.dispose()
