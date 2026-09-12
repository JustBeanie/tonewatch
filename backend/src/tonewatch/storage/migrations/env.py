"""Alembic environment for async SQLite migrations."""

from alembic import context
from sqlalchemy import engine_from_config, pool

from tonewatch.storage.models import Base

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(
        url=context.config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    configuration = context.config.get_section(context.config.config_ini_section, {})
    connectable = engine_from_config(configuration, prefix="sqlalchemy.", poolclass=pool.NullPool)
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


def run_migrations() -> None:
    """Run under Alembic while remaining safe for runtime import discovery."""
    try:
        offline = context.is_offline_mode()
    except (AttributeError, NameError):
        return
    if offline:
        run_migrations_offline()
    else:
        run_migrations_online()


run_migrations()
