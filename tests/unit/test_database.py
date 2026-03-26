from __future__ import annotations

from contextlib import asynccontextmanager
from contextlib import contextmanager
import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import nexus_core.database as database


@pytest.fixture(autouse=True)
def reset_schema_flag():
    original = database._schema_compatibility_ensured
    database._schema_compatibility_ensured = False
    try:
        yield
    finally:
        database._schema_compatibility_ensured = original


@pytest.mark.asyncio
async def test_ensure_database_compatibility_runs_schema_upgrade_once():
    lock_conn = MagicMock()
    lock_conn.execute = AsyncMock()

    @asynccontextmanager
    async def _connect():
        yield lock_conn

    engine = MagicMock()
    engine.connect = _connect
    engine.url.render_as_string.return_value = "postgresql+asyncpg://test:test@localhost/test"

    with patch("nexus_core.database.get_engine", return_value=engine), patch(
        "nexus_core.database._upgrade_database_schema",
        new=AsyncMock(),
    ) as upgrade_schema, patch(
        "nexus_core.database._apply_runtime_compatibility_fixes",
        new=AsyncMock(),
    ) as apply_fixes:
        await database.ensure_database_compatibility()
        await database.ensure_database_compatibility()

    upgrade_schema.assert_awaited_once_with(
        "postgresql+asyncpg://test:test@localhost/test"
    )
    apply_fixes.assert_awaited_once_with(engine)
    assert lock_conn.execute.await_count == 2


@pytest.mark.asyncio
async def test_upgrade_database_schema_restores_database_url_environment():
    observed_urls: list[str | None] = []
    previous = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = "postgresql+asyncpg://before:test@localhost/before"

    try:
        with patch("alembic.config.Config") as config_cls, patch(
            "alembic.command.upgrade"
        ) as upgrade, patch(
            "nexus_core.database._startup_migration_file_lock"
        ) as file_lock:
            @contextmanager
            def _fake_file_lock(*args, **kwargs):
                yield

            file_lock.side_effect = _fake_file_lock

            def _capture_upgrade(config, revision):
                observed_urls.append(os.environ.get("DATABASE_URL"))
                assert revision == "head"

            upgrade.side_effect = _capture_upgrade

            await database._upgrade_database_schema(
                "postgresql+asyncpg://after:test@localhost/after"
            )

        config_cls.assert_called_once()
        file_lock.assert_called_once()
        assert observed_urls == ["postgresql+asyncpg://after:test@localhost/after"]
        assert os.environ.get("DATABASE_URL") == "postgresql+asyncpg://before:test@localhost/before"
    finally:
        if previous is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = previous
