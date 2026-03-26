"""Shared fixtures for NEXUS unit and integration tests."""

from __future__ import annotations

import asyncio
import os
import threading
from decimal import Decimal
from pathlib import Path

from alembic import command
from alembic.config import Config
import pytest
import pytest_asyncio
import sqlalchemy as sa
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import create_async_engine


ROOT = Path(__file__).resolve().parents[1]
TRUNCATE_TABLES = [
    "events",
    "agent_telemetry",
    "circuit_breaker_incidents",
    "circuit_breaker_rules",
    "evolution_metric_snapshots",
    "scout_source_health",
    "civilization_quality_holdbacks",
    "civilization_challenges",
    "civilization_bonds",
    "persona_capability_scores",
    "objective_incentive_profiles",
    "market_reservations",
    "market_price_history",
    "market_positions",
    "market_trades",
    "market_orders",
    "market_instruments",
    "service_contracts",
    "marketplace_listings",
    "market_assets",
    "market_templates",
    "persona_market_profiles",
    "tool_registry",
    "institutional_memory",
    "messages",
    "governance_votes",
    "governance_proposals",
    "economy_ledger",
    "peer_reviews",
    "findings",
    "knowledge_graph_edges",
    "knowledge_graph_nodes",
    "objective_decomposition",
    "agent_instances",
    "objectives",
    "agent_personas",
]


def _derive_test_database_url() -> str:
    from nexus_core.config import get_settings

    base = make_url(get_settings().DATABASE_URL)
    database_name = base.database or "nexus"
    if not database_name.endswith("_test"):
        database_name = f"{database_name}_test"
    return base.set(database=database_name).render_as_string(hide_password=False)


async def _recreate_database(database_url: str) -> None:
    target = make_url(database_url)
    admin_url = target.set(database="postgres").render_as_string(hide_password=False)
    engine = create_async_engine(
        admin_url,
        isolation_level="AUTOCOMMIT",
        pool_pre_ping=True,
    )
    try:
        async with engine.connect() as conn:
            safe_name = str(target.database).replace('"', '""')
            await conn.execute(
                sa.text(
                    """
                    SELECT pg_terminate_backend(pid)
                    FROM pg_stat_activity
                    WHERE datname = :dbname AND pid <> pg_backend_pid()
                    """
                ),
                {"dbname": target.database},
            )
            exists = await conn.execute(
                sa.text("SELECT 1 FROM pg_database WHERE datname = :dbname"),
                {"dbname": target.database},
            )
            if exists.scalar_one_or_none():
                await conn.execute(sa.text(f'DROP DATABASE "{safe_name}"'))
            await conn.execute(sa.text(f'CREATE DATABASE "{safe_name}"'))
    finally:
        await engine.dispose()


async def _prepare_test_database(database_url: str) -> None:
    engine = create_async_engine(
        database_url,
        isolation_level="AUTOCOMMIT",
        pool_pre_ping=True,
    )
    try:
        async with engine.connect() as conn:
            await conn.execute(sa.text('CREATE EXTENSION IF NOT EXISTS "uuid-ossp"'))
            await conn.execute(sa.text("CREATE EXTENSION IF NOT EXISTS vector"))
            await conn.execute(sa.text("CREATE EXTENSION IF NOT EXISTS pg_trgm"))
    finally:
        await engine.dispose()


def _run_alembic_upgrade(database_url: str) -> None:
    config = Config(str(ROOT / "alembic.ini"))
    previous_url = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = database_url
    try:
        command.upgrade(config, "head")
    finally:
        if previous_url is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = previous_url


def _run_in_thread(fn, *args):
    result: dict[str, object] = {}

    def _target():
        try:
            result["value"] = fn(*args)
        except Exception as exc:  # pragma: no cover - only used on failure
            result["error"] = exc

    thread = threading.Thread(target=_target, daemon=True)
    thread.start()
    thread.join()
    if "error" in result:
        raise result["error"]  # type: ignore[misc]
    return result.get("value")


async def _truncate_database(engine) -> None:
    async with engine.begin() as conn:
        await conn.execute(
            sa.text(
                "TRUNCATE TABLE "
                + ", ".join(TRUNCATE_TABLES)
                + " RESTART IDENTITY CASCADE"
            )
        )


@pytest.fixture
def settings():
    """Create test settings based on the local .env, but pointed at the test DB."""
    from nexus_core.config import get_settings

    return get_settings().model_copy(
        update={
            "DATABASE_URL": _derive_test_database_url(),
            "MOONSHOT_API_KEY": "test-key",
            "BUDGET_CEILING_USD": Decimal("38.25"),
        }
    )


@pytest.fixture
def cost_guard(settings):
    """Create a CostGuard for testing."""
    from nexus_core.utils.cost import CostGuard

    return CostGuard.from_settings(settings)


@pytest.fixture(scope="session")
def integration_database_url() -> str:
    return _derive_test_database_url()


@pytest.fixture(scope="session")
def prepared_test_database(integration_database_url):
    try:
        _run_in_thread(asyncio.run, _recreate_database(integration_database_url))
        _run_in_thread(asyncio.run, _prepare_test_database(integration_database_url))
        _run_in_thread(_run_alembic_upgrade, integration_database_url)
    except Exception as exc:
        pytest.skip(f"PostgreSQL integration environment unavailable: {exc}")
    return integration_database_url


@pytest_asyncio.fixture
async def integration_engine(prepared_test_database):
    engine = create_async_engine(
        prepared_test_database,
        pool_pre_ping=True,
    )
    try:
        yield engine
    finally:
        await engine.dispose()


@pytest_asyncio.fixture
async def clean_database(integration_engine):
    await _truncate_database(integration_engine)
    try:
        yield integration_engine
    finally:
        await _truncate_database(integration_engine)
