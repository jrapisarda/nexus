"""Unit tests for nexus_api.websocket — ConnectionManager and EventMessage."""

import asyncio
from datetime import datetime, timezone

import pytest

from nexus_api.websocket import ConnectionManager
from nexus_api.schemas import EventMessage


class TestConnectionManager:
    """Test ConnectionManager without real WebSocket connections."""

    def test_initial_count(self):
        mgr = ConnectionManager()
        assert mgr.active_count == 0

    @pytest.mark.asyncio
    async def test_broadcast_with_no_connections(self):
        """broadcast_json should not raise when there are no connections."""
        mgr = ConnectionManager()
        await mgr.broadcast_json({"type": "test", "data": {}})
        assert mgr.active_count == 0


class TestEventMessage:
    def test_serialise_round_trip(self):
        msg = EventMessage(
            type="kg_node_created",
            data={"node_id": "abc-123", "label": "Test"},
            timestamp=datetime.now(timezone.utc).isoformat(),
        )
        d = msg.model_dump()
        assert d["type"] == "kg_node_created"
        assert "node_id" in d["data"]
        restored = EventMessage(**d)
        assert restored.type == msg.type
        assert restored.data == msg.data

    def test_event_message_fields(self):
        msg = EventMessage(
            type="connected",
            data={"message": "hello"},
            timestamp="2025-01-01T00:00:00Z",
        )
        assert msg.type == "connected"
        assert msg.timestamp == "2025-01-01T00:00:00Z"
