"""Unit tests for nexus_core.utils.events — emit_event()."""

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID, uuid4

import pytest

from nexus_core.utils.events import emit_event


class TestEmitEvent:
    """Test emit_event with a mocked database connection."""

    @pytest.fixture
    def mock_conn(self):
        """Create a mock AsyncConnection with an async execute method."""
        conn = AsyncMock()
        conn.execute = AsyncMock()
        return conn

    async def test_emit_event_calls_execute(self, mock_conn):
        """emit_event should call conn.execute exactly once."""
        await emit_event(mock_conn, event_type="objective.created")
        mock_conn.execute.assert_called_once()

    async def test_emit_event_inserts_row(self, mock_conn):
        """Verify the insert statement carries the correct values."""
        entity_id = uuid4()
        await emit_event(
            mock_conn,
            event_type="objective.created",
            entity_id=entity_id,
            entity_type="objective",
            payload={"title": "Test Objective"},
        )
        # Retrieve the Insert clause that was passed to execute
        mock_conn.execute.assert_called_once()
        call_args = mock_conn.execute.call_args
        insert_clause = call_args[0][0]

        # The clause should be a SQLAlchemy Insert compiled against the events table
        from nexus_core.models.events import events

        assert insert_clause.table is events

    async def test_emit_event_with_payload(self, mock_conn):
        """Verify that the payload dict is passed through to the insert."""
        payload = {"key": "value", "count": 42}
        await emit_event(
            mock_conn,
            event_type="finding.submitted",
            payload=payload,
        )
        mock_conn.execute.assert_called_once()
        call_args = mock_conn.execute.call_args
        insert_clause = call_args[0][0]

        # Extract the compiled parameters from the insert clause
        compiled = insert_clause.compile()
        params = compiled.params
        assert params["payload"] == payload
        assert params["event_type"] == "finding.submitted"

    async def test_emit_event_minimal(self, mock_conn):
        """When entity_id, entity_type, and payload are None, payload defaults to {}."""
        await emit_event(mock_conn, event_type="system.heartbeat")
        mock_conn.execute.assert_called_once()
        call_args = mock_conn.execute.call_args
        insert_clause = call_args[0][0]

        compiled = insert_clause.compile()
        params = compiled.params
        assert params["event_type"] == "system.heartbeat"
        assert params["entity_id"] is None
        assert params["entity_type"] is None
        # payload defaults to {} when None is passed
        assert params["payload"] == {}

    async def test_emit_event_with_entity_id_as_uuid(self, mock_conn):
        """Verify entity_id accepts a UUID object."""
        uid = UUID("12345678-1234-5678-1234-567812345678")
        await emit_event(
            mock_conn,
            event_type="persona.spawned",
            entity_id=uid,
            entity_type="persona",
        )
        mock_conn.execute.assert_called_once()
        call_args = mock_conn.execute.call_args
        insert_clause = call_args[0][0]
        compiled = insert_clause.compile()
        params = compiled.params
        assert params["entity_id"] == uid
        assert params["entity_type"] == "persona"

    async def test_emit_event_with_none_entity_id(self, mock_conn):
        """entity_id=None should pass through as None."""
        await emit_event(
            mock_conn,
            event_type="cycle.complete",
            entity_id=None,
        )
        mock_conn.execute.assert_called_once()
        call_args = mock_conn.execute.call_args
        insert_clause = call_args[0][0]
        compiled = insert_clause.compile()
        params = compiled.params
        assert params["entity_id"] is None
