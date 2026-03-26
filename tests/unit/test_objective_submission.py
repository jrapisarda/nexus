"""Unit tests for POST /api/objectives endpoint — objective submission."""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from nexus_api.main import app


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_objective_row(
    *,
    title: str = "Test Objective",
    description: str = "Test description",
    objective_type: str = "strategic",
    priority: int = 5,
    attachment_ids: list | None = None,
):
    """Create a SimpleNamespace that mimics a DB row returned by INSERT ... RETURNING."""
    oid = uuid4()
    now = datetime.now(timezone.utc)
    mapping = {
        "objective_id": oid,
        "parent_objective_id": None,
        "title": title,
        "description": description,
        "objective_type": objective_type,
        "impact_level": None,
        "priority": priority,
        "status": "proposed",
        "proposed_by_type": "human",
        "proposed_by_id": None,
        "approved_by_type": None,
        "approved_by_id": None,
        "assigned_to": None,
        "acceptance_criteria": None,
        "knowledge_graph_anchor": None,
        "compute_budget_allocated": None,
        "output_type": None,
        "created_at": now,
        "completed_at": None,
        "escalated_at": None,
        "escalation_reason": None,
        "file_attachment_ids": attachment_ids or [],
    }
    row = SimpleNamespace(**mapping)
    row._mapping = mapping
    return row


class _FakeAsyncCtx:
    """Minimal async context manager that yields a fixed value."""
    def __init__(self, value):
        self._value = value
    async def __aenter__(self):
        return self._value
    async def __aexit__(self, *args):
        return False


def _mock_connection_context(mock_conn):
    """Build the async context manager chain: get_connection -> conn.begin -> conn.

    The endpoint does::

        async with get_connection() as conn:
            async with conn.begin():
                ...

    ``get_connection()`` must return an async-ctx that yields ``mock_conn``.
    ``conn.begin()`` is a regular (non-async) call that returns an async-ctx.
    """
    # begin() must be a plain function returning an async context manager
    mock_conn.begin = MagicMock(return_value=_FakeAsyncCtx(None))
    return _FakeAsyncCtx(mock_conn)


# ---------------------------------------------------------------------------
# POST /api/objectives — valid submission
# ---------------------------------------------------------------------------

class TestCreateObjectiveSuccess:
    """Verify successful objective creation via POST /api/objectives."""

    @patch("nexus_api.routers.objectives.emit_event", new_callable=AsyncMock)
    @patch("nexus_api.routers.objectives.get_connection")
    async def test_valid_submission_returns_201(self, mock_get_conn, mock_emit):
        """A valid objective submission returns 201 with objective data."""
        row = _make_objective_row(
            title="Investigate BRCA1 mechanisms",
            description="Research BRCA1 gene interactions in breast cancer",
            objective_type="strategic",
            priority=7,
        )

        mock_conn = AsyncMock()
        mock_result = MagicMock()
        mock_result.first.return_value = row
        mock_conn.execute = AsyncMock(return_value=mock_result)
        mock_get_conn.return_value = _mock_connection_context(mock_conn)

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                "/api/objectives",
                json={
                    "title": "Investigate BRCA1 mechanisms",
                    "description": "Research BRCA1 gene interactions in breast cancer",
                    "objective_type": "strategic",
                    "priority": 7,
                },
            )

        assert response.status_code == 201
        data = response.json()
        assert data["title"] == "Investigate BRCA1 mechanisms"
        assert data["status"] == "proposed"
        assert data["objective_type"] == "strategic"
        assert data["priority"] == 7
        assert data["proposed_by_type"] == "human"

    @patch("nexus_api.routers.objectives.emit_event", new_callable=AsyncMock)
    @patch("nexus_api.routers.objectives.get_connection")
    async def test_tactical_objective_returns_201(self, mock_get_conn, mock_emit):
        """A tactical objective type is accepted."""
        row = _make_objective_row(objective_type="tactical")

        mock_conn = AsyncMock()
        mock_result = MagicMock()
        mock_result.first.return_value = row
        mock_conn.execute = AsyncMock(return_value=mock_result)
        mock_get_conn.return_value = _mock_connection_context(mock_conn)

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                "/api/objectives",
                json={
                    "title": "Tactical task",
                    "description": "A quick tactical objective",
                    "objective_type": "tactical",
                    "priority": 3,
                },
            )

        assert response.status_code == 201

    @patch("nexus_api.routers.objectives.emit_event", new_callable=AsyncMock)
    @patch("nexus_api.routers.objectives.get_connection")
    async def test_exploratory_objective_returns_201(self, mock_get_conn, mock_emit):
        """An exploratory objective type is accepted."""
        row = _make_objective_row(objective_type="exploratory")

        mock_conn = AsyncMock()
        mock_result = MagicMock()
        mock_result.first.return_value = row
        mock_conn.execute = AsyncMock(return_value=mock_result)
        mock_get_conn.return_value = _mock_connection_context(mock_conn)

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                "/api/objectives",
                json={
                    "title": "Explore novel targets",
                    "description": "Exploratory research",
                    "objective_type": "exploratory",
                    "priority": 5,
                },
            )

        assert response.status_code == 201

    @patch("nexus_api.routers.objectives.emit_event", new_callable=AsyncMock)
    @patch("nexus_api.routers.objectives.get_connection")
    async def test_default_values_used(self, mock_get_conn, mock_emit):
        """Default priority and objective_type are used when not provided."""
        row = _make_objective_row()

        mock_conn = AsyncMock()
        mock_result = MagicMock()
        mock_result.first.return_value = row
        mock_conn.execute = AsyncMock(return_value=mock_result)
        mock_get_conn.return_value = _mock_connection_context(mock_conn)

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                "/api/objectives",
                json={
                    "title": "Simple objective",
                    "description": "Minimal submission",
                },
            )

        assert response.status_code == 201

    @patch("nexus_api.routers.objectives.emit_event", new_callable=AsyncMock)
    @patch("nexus_api.routers.objectives.get_connection")
    async def test_response_contains_objective_id(self, mock_get_conn, mock_emit):
        """Response includes the generated objective_id."""
        row = _make_objective_row()

        mock_conn = AsyncMock()
        mock_result = MagicMock()
        mock_result.first.return_value = row
        mock_conn.execute = AsyncMock(return_value=mock_result)
        mock_get_conn.return_value = _mock_connection_context(mock_conn)

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                "/api/objectives",
                json={
                    "title": "Objective with ID",
                    "description": "Test",
                    "objective_type": "strategic",
                    "priority": 5,
                },
            )

        assert response.status_code == 201
        data = response.json()
        assert "objective_id" in data
        assert data["objective_id"] is not None


# ---------------------------------------------------------------------------
# POST /api/objectives — invalid objective_type
# ---------------------------------------------------------------------------

class TestCreateObjectiveInvalidType:
    """Verify 422 for invalid objective_type."""

    async def test_invalid_objective_type_returns_422(self):
        """An unrecognized objective_type returns 422."""
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                "/api/objectives",
                json={
                    "title": "Bad type",
                    "description": "This should fail",
                    "objective_type": "unknown_type",
                    "priority": 5,
                },
            )

        assert response.status_code == 422
        assert "Invalid type" in response.json()["detail"]

    async def test_empty_objective_type_returns_422(self):
        """An empty string objective_type returns 422."""
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                "/api/objectives",
                json={
                    "title": "Empty type",
                    "description": "Desc",
                    "objective_type": "",
                    "priority": 5,
                },
            )

        assert response.status_code == 422

    async def test_numeric_objective_type_returns_422(self):
        """A numeric objective_type value returns 422."""
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                "/api/objectives",
                json={
                    "title": "Numeric type",
                    "description": "Desc",
                    "objective_type": "123",
                    "priority": 5,
                },
            )

        assert response.status_code == 422


# ---------------------------------------------------------------------------
# POST /api/objectives — priority out of range
# ---------------------------------------------------------------------------

class TestCreateObjectivePriorityRange:
    """Verify 422 for priority outside [1, 10] range."""

    async def test_priority_zero_returns_422(self):
        """Priority 0 is below the allowed range."""
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                "/api/objectives",
                json={
                    "title": "Low priority",
                    "description": "Desc",
                    "objective_type": "strategic",
                    "priority": 0,
                },
            )

        assert response.status_code == 422
        assert "Priority" in response.json()["detail"]

    async def test_priority_eleven_returns_422(self):
        """Priority 11 is above the allowed range."""
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                "/api/objectives",
                json={
                    "title": "High priority",
                    "description": "Desc",
                    "objective_type": "strategic",
                    "priority": 11,
                },
            )

        assert response.status_code == 422
        assert "Priority" in response.json()["detail"]

    async def test_negative_priority_returns_422(self):
        """Negative priority values are rejected."""
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                "/api/objectives",
                json={
                    "title": "Negative",
                    "description": "Desc",
                    "objective_type": "strategic",
                    "priority": -5,
                },
            )

        assert response.status_code == 422

    @patch("nexus_api.routers.objectives.emit_event", new_callable=AsyncMock)
    @patch("nexus_api.routers.objectives.get_connection")
    async def test_priority_one_is_valid(self, mock_get_conn, mock_emit):
        """Priority 1 (boundary) is accepted."""
        row = _make_objective_row(priority=1)

        mock_conn = AsyncMock()
        mock_result = MagicMock()
        mock_result.first.return_value = row
        mock_conn.execute = AsyncMock(return_value=mock_result)
        mock_get_conn.return_value = _mock_connection_context(mock_conn)

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                "/api/objectives",
                json={
                    "title": "Min priority",
                    "description": "Desc",
                    "objective_type": "strategic",
                    "priority": 1,
                },
            )

        assert response.status_code == 201

    @patch("nexus_api.routers.objectives.emit_event", new_callable=AsyncMock)
    @patch("nexus_api.routers.objectives.get_connection")
    async def test_priority_ten_is_valid(self, mock_get_conn, mock_emit):
        """Priority 10 (boundary) is accepted."""
        row = _make_objective_row(priority=10)

        mock_conn = AsyncMock()
        mock_result = MagicMock()
        mock_result.first.return_value = row
        mock_conn.execute = AsyncMock(return_value=mock_result)
        mock_get_conn.return_value = _mock_connection_context(mock_conn)

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                "/api/objectives",
                json={
                    "title": "Max priority",
                    "description": "Desc",
                    "objective_type": "strategic",
                    "priority": 10,
                },
            )

        assert response.status_code == 201


# ---------------------------------------------------------------------------
# POST /api/objectives — with attachment_ids
# ---------------------------------------------------------------------------

class TestCreateObjectiveWithAttachments:
    """Verify attachment linking during objective creation."""

    @patch("nexus_api.routers.objectives.emit_event", new_callable=AsyncMock)
    @patch("nexus_api.routers.objectives.get_connection")
    async def test_attachment_ids_linked(self, mock_get_conn, mock_emit):
        """Submission with attachment_ids triggers an UPDATE to link them."""
        att_id_1 = uuid4()
        att_id_2 = uuid4()
        row = _make_objective_row(attachment_ids=[str(att_id_1), str(att_id_2)])

        mock_conn = AsyncMock()
        mock_result = MagicMock()
        mock_result.first.return_value = row
        mock_conn.execute = AsyncMock(return_value=mock_result)
        mock_get_conn.return_value = _mock_connection_context(mock_conn)

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                "/api/objectives",
                json={
                    "title": "With attachments",
                    "description": "Objective with files",
                    "objective_type": "strategic",
                    "priority": 5,
                    "attachment_ids": [str(att_id_1), str(att_id_2)],
                },
            )

        assert response.status_code == 201
        data = response.json()
        assert data["file_attachment_ids"] == [str(att_id_1), str(att_id_2)]

        # The connection should have been called twice:
        # 1. INSERT into objectives
        # 2. UPDATE objective_attachments (linking)
        # (emit_event is mocked separately)
        assert mock_conn.execute.call_count == 2

    @patch("nexus_api.routers.objectives.emit_event", new_callable=AsyncMock)
    @patch("nexus_api.routers.objectives.get_connection")
    async def test_no_attachment_ids_skips_link(self, mock_get_conn, mock_emit):
        """Submission without attachment_ids does not attempt to link."""
        row = _make_objective_row(attachment_ids=[])

        mock_conn = AsyncMock()
        mock_result = MagicMock()
        mock_result.first.return_value = row
        mock_conn.execute = AsyncMock(return_value=mock_result)
        mock_get_conn.return_value = _mock_connection_context(mock_conn)

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                "/api/objectives",
                json={
                    "title": "No attachments",
                    "description": "Plain objective",
                    "objective_type": "strategic",
                    "priority": 5,
                },
            )

        assert response.status_code == 201
        # Only 1 execute call: INSERT (emit_event is mocked, no UPDATE for attachments)
        assert mock_conn.execute.call_count == 1

    @patch("nexus_api.routers.objectives.emit_event", new_callable=AsyncMock)
    @patch("nexus_api.routers.objectives.get_connection")
    async def test_emit_event_includes_attachment_count(self, mock_get_conn, mock_emit):
        """The emitted event payload should include the attachment_count."""
        att_id = uuid4()
        row = _make_objective_row(attachment_ids=[str(att_id)])

        mock_conn = AsyncMock()
        mock_result = MagicMock()
        mock_result.first.return_value = row
        mock_conn.execute = AsyncMock(return_value=mock_result)
        mock_get_conn.return_value = _mock_connection_context(mock_conn)

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            await client.post(
                "/api/objectives",
                json={
                    "title": "With one attachment",
                    "description": "Test",
                    "objective_type": "strategic",
                    "priority": 5,
                    "attachment_ids": [str(att_id)],
                },
            )

        mock_emit.assert_called_once()
        call_kwargs = mock_emit.call_args
        # emit_event is called with positional args: conn, event_type
        # and keyword args: entity_id, entity_type, payload
        payload = call_kwargs.kwargs["payload"]
        assert payload["attachment_count"] == 1


# ---------------------------------------------------------------------------
# POST /api/objectives — missing required fields
# ---------------------------------------------------------------------------

class TestCreateObjectiveMissingFields:
    """Verify Pydantic validation rejects missing required fields."""

    async def test_missing_title_returns_422(self):
        """Missing title field returns 422 from Pydantic validation."""
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                "/api/objectives",
                json={
                    "description": "No title given",
                    "objective_type": "strategic",
                    "priority": 5,
                },
            )

        assert response.status_code == 422

    async def test_missing_description_returns_422(self):
        """Missing description field returns 422 from Pydantic validation."""
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                "/api/objectives",
                json={
                    "title": "No description",
                    "objective_type": "strategic",
                    "priority": 5,
                },
            )

        assert response.status_code == 422

    async def test_empty_body_returns_422(self):
        """An empty JSON body returns 422."""
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                "/api/objectives",
                json={},
            )

        assert response.status_code == 422
