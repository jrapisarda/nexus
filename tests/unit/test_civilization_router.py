from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from nexus_api.routers import civilization


class _FakeAsyncContextManager:
    def __init__(self, conn):
        self._conn = conn

    async def __aenter__(self):
        return self._conn

    async def __aexit__(self, exc_type, exc, tb):
        return False


class _FakeResult:
    def __init__(self, rows):
        self._rows = rows

    def fetchall(self):
        return self._rows


@pytest.mark.asyncio
async def test_civilization_overview_uses_table_records_not_route_function(monkeypatch):
    conn = AsyncMock()
    conn.scalar = AsyncMock(side_effect=[2, 3, 4, 1, 5])

    monkeypatch.setattr(
        civilization,
        "get_connection",
        lambda: _FakeAsyncContextManager(conn),
    )
    monkeypatch.setattr(
        civilization,
        "get_concentration_metrics",
        AsyncMock(
            return_value={
                "wealth_gini": 0.41,
                "top_balance_share": 0.58,
                "role_concentration": 0.27,
            }
        ),
    )

    response = await civilization.civilization_overview()

    assert response.pending_challenges == 2
    assert response.pending_holdbacks == 3
    assert response.slow_science_objectives == 4
    assert response.degraded_scout_sources == 1
    assert response.open_breaker_incidents == 5
    assert response.wealth_gini == 0.41


@pytest.mark.asyncio
async def test_civilization_challenges_view_returns_rows(monkeypatch):
    challenge_id = uuid4()
    finding_id = uuid4()
    challenger_persona_id = uuid4()
    opened_at = datetime.now(timezone.utc)
    due_at = datetime.now(timezone.utc)

    conn = AsyncMock()
    conn.execute = AsyncMock(
        return_value=_FakeResult(
            [
                SimpleNamespace(
                    _mapping={
                        "challenge_id": challenge_id,
                        "finding_id": finding_id,
                        "finding_title": "Red Queen adaptation loop",
                        "challenger_persona_id": challenger_persona_id,
                        "challenger_name": "Sentinel Red Team",
                        "flaw_type": "logical",
                        "severity": "major",
                        "status": "open",
                        "summary": "The conclusion overstates adaptation pressure.",
                        "opened_at": opened_at,
                        "resolution_due_at": due_at,
                        "resolved_at": None,
                    }
                )
            ]
        )
    )

    monkeypatch.setattr(
        civilization,
        "get_connection",
        lambda: _FakeAsyncContextManager(conn),
    )

    response = await civilization.civilization_challenges_view(limit=5)

    assert response.count == 1
    assert response.items[0].challenge_id == challenge_id
    assert response.items[0].challenger_name == "Sentinel Red Team"
