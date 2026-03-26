"""Alembic async environment configuration for NEXUS."""

from __future__ import annotations

import asyncio
import os
import sys
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool
from sqlalchemy.ext.asyncio import create_async_engine

# ---------------------------------------------------------------------------
# Ensure the project root is importable so ``nexus_core`` resolves.
# ---------------------------------------------------------------------------
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "nexus-core"))

from nexus_core.models import metadata  # noqa: E402

# Alembic Config object — gives access to values in alembic.ini.
config = context.config

# Interpret the config file for Python logging.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = metadata


def _get_url() -> str:
    """Resolve the database URL from the environment or .env file."""
    url = os.environ.get("DATABASE_URL")
    if url:
        return url
    # Fall back to dotenv
    try:
        from dotenv import dotenv_values

        values = dotenv_values(os.path.join(os.path.dirname(__file__), "..", ".env"))
        url = values.get("DATABASE_URL")
        if url:
            return url
    except ImportError:
        pass
    # Ultimate fallback
    return "postgresql+asyncpg://claudeai:Magic123@localhost:5432/nexus"


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode — emit SQL to stdout."""
    url = _get_url()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection):  # type: ignore[no-untyped-def]
    """Shared migration runner used by both sync and async paths."""
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    """Create an async engine and run migrations in an async context."""
    connectable = create_async_engine(
        _get_url(),
        poolclass=pool.NullPool,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode with an async engine."""
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
