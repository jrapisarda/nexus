"""Async SQLAlchemy engine and connection management for NEXUS."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager, contextmanager
import os
from pathlib import Path
import time
from typing import AsyncIterator

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, create_async_engine

from nexus_core.config import NexusSettings

_engine: AsyncEngine | None = None
_schema_compatibility_ensured = False


def get_engine(settings: NexusSettings | None = None) -> AsyncEngine:
    """Get or create the async engine singleton.

    Args:
        settings: Optional NexusSettings. If *None* on first call the global
                  singleton from :func:`get_settings` is used.
    """
    global _engine
    if _engine is None:
        if settings is None:
            from nexus_core.config import get_settings

            settings = get_settings()
        _engine = create_async_engine(
            settings.DATABASE_URL,
            pool_size=10,
            max_overflow=20,
            pool_pre_ping=True,
            pool_recycle=3600,
            echo=False,
        )
    return _engine


async def dispose_engine() -> None:
    """Dispose the engine on shutdown."""
    global _engine, _schema_compatibility_ensured
    if _engine:
        await _engine.dispose()
        _engine = None
    _schema_compatibility_ensured = False


@asynccontextmanager
async def get_connection(
    settings: NexusSettings | None = None,
) -> AsyncIterator[AsyncConnection]:
    """Async context manager that yields an ``AsyncConnection``.

    Usage::

        async with get_connection() as conn:
            result = await conn.execute(text("SELECT 1"))
    """
    engine = get_engine(settings)
    async with engine.connect() as conn:
        yield conn


async def ensure_database_compatibility(
    settings: NexusSettings | None = None,
) -> None:
    """Ensure the live database schema is safe for the current application."""
    global _schema_compatibility_ensured
    if _schema_compatibility_ensured:
        return

    engine = get_engine(settings)
    async with engine.connect() as lock_conn:
        await lock_conn.execute(sa.text("SELECT pg_advisory_lock(987654321)"))
        try:
            await _upgrade_database_schema(
                engine.url.render_as_string(hide_password=False)
            )
            await _apply_runtime_compatibility_fixes(engine)
        finally:
            await lock_conn.execute(sa.text("SELECT pg_advisory_unlock(987654321)"))

    _schema_compatibility_ensured = True


async def _upgrade_database_schema(database_url: str) -> None:
    """Run Alembic to head in a background thread."""

    def _run_upgrade() -> None:
        from alembic import command
        from alembic.config import Config

        root = Path(__file__).resolve().parents[2]
        config = Config(str(root / "alembic.ini"))
        previous_url = os.environ.get("DATABASE_URL")
        os.environ["DATABASE_URL"] = database_url
        try:
            with _startup_migration_file_lock(root / ".nexus_startup_migration.lock"):
                command.upgrade(config, "head")
        finally:
            if previous_url is None:
                os.environ.pop("DATABASE_URL", None)
            else:
                os.environ["DATABASE_URL"] = previous_url

    await asyncio.to_thread(_run_upgrade)


@contextmanager
def _startup_migration_file_lock(lock_path: Path, poll_interval_secs: float = 0.25):
    """Serialize startup migrations across local processes."""
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with open(lock_path, "a+b") as lock_file:
        if lock_file.tell() == 0:
            lock_file.write(b"0")
            lock_file.flush()
        lock_file.seek(0)

        if os.name == "nt":
            import msvcrt

            locked = False
            while not locked:
                try:
                    msvcrt.locking(lock_file.fileno(), msvcrt.LK_NBLCK, 1)
                    locked = True
                except OSError:
                    time.sleep(poll_interval_secs)
            try:
                yield
            finally:
                lock_file.seek(0)
                msvcrt.locking(lock_file.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl

            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


async def _apply_runtime_compatibility_fixes(engine: AsyncEngine) -> None:
    """Apply non-breaking compatibility fixes that are not full migrations."""
    async with engine.begin() as conn:
        column_exists = await conn.scalar(
            sa.text(
                """
                SELECT EXISTS (
                    SELECT 1
                    FROM information_schema.columns
                    WHERE table_name = 'knowledge_graph_nodes'
                      AND column_name = 'canonical_label'
                )
                """
            )
        )
        if not column_exists:
            await conn.execute(
                sa.text(
                    """
                    ALTER TABLE knowledge_graph_nodes
                    ADD COLUMN IF NOT EXISTS canonical_label VARCHAR(500)
                    """
                )
            )
            await conn.execute(
                sa.text(
                    """
                    UPDATE knowledge_graph_nodes
                    SET canonical_label = trim(
                        regexp_replace(
                            regexp_replace(
                                regexp_replace(lower(label), '[\\s\\-_]+', ' ', 'g'),
                                '[^\\w\\s/]',
                                '',
                                'g'
                            ),
                            '\\s+',
                            ' ',
                            'g'
                        )
                    )
                    WHERE canonical_label IS NULL OR canonical_label = ''
                    """
                )
            )
            await conn.execute(
                sa.text(
                    """
                    ALTER TABLE knowledge_graph_nodes
                    ALTER COLUMN canonical_label SET NOT NULL
                    """
                )
            )

        await conn.execute(
            sa.text(
                """
                CREATE INDEX IF NOT EXISTS ix_kg_nodes_canonical_label
                ON knowledge_graph_nodes (canonical_label)
                """
            )
        )
        await conn.execute(
            sa.text(
                """
                CREATE INDEX IF NOT EXISTS ix_kg_nodes_type_canonical_label
                ON knowledge_graph_nodes (node_type, canonical_label)
                """
            )
        )
