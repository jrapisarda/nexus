"""WebSocket connection manager and NOTIFY relay for the NEXUS Observatory API."""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from fastapi.encoders import jsonable_encoder
import sqlalchemy as sa

from nexus_api.schemas import EventMessage

router = APIRouter()


class ConnectionManager:
    """Track active WebSocket connections and broadcast JSON messages."""

    def __init__(self):
        self._connections: list[WebSocket] = []
        self._lock = asyncio.Lock()

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        async with self._lock:
            self._connections.append(websocket)

    async def disconnect(self, websocket: WebSocket):
        async with self._lock:
            if websocket in self._connections:
                self._connections.remove(websocket)

    async def broadcast_json(self, data: dict):
        """Send a JSON payload to every connected client."""
        async with self._lock:
            stale: list[WebSocket] = []
            for ws in self._connections:
                try:
                    await ws.send_json(data)
                except Exception:
                    stale.append(ws)
            for ws in stale:
                self._connections.remove(ws)

    @property
    def active_count(self) -> int:
        return len(self._connections)


manager = ConnectionManager()


async def _hydrate_event_message(event_id: str | None) -> EventMessage | None:
    """Load a full business event row from the outbox for WebSocket clients."""
    if not event_id:
        return None

    try:
        parsed_event_id = UUID(str(event_id))
    except (TypeError, ValueError):
        return None

    from nexus_core.database import get_connection
    from nexus_core.models.events import events

    async with get_connection() as conn:
        result = await conn.execute(
            sa.select(events).where(events.c.event_id == parsed_event_id)
        )
        row = result.first()

    if row is None:
        return None

    payload = dict(row.payload or {})
    payload.setdefault("event_id", str(row.event_id))
    if row.entity_id is not None:
        payload.setdefault("entity_id", str(row.entity_id))
    if row.entity_type is not None:
        payload.setdefault("entity_type", row.entity_type)

    return EventMessage(
        type=row.event_type,
        data=jsonable_encoder(payload),
        timestamp=row.created_at.isoformat(),
    )


async def _pg_notify_listener():
    """Background task that listens for PostgreSQL NOTIFY events on the
    ``nexus_events`` channel and broadcasts them to connected WebSocket clients.

    Uses asyncpg-listen for robust reconnection behaviour.
    """
    try:
        from nexus_core.config import get_settings

        settings = get_settings()
        # Convert the SQLAlchemy async URL to a raw asyncpg DSN.
        dsn = settings.DATABASE_URL.replace("postgresql+asyncpg://", "postgresql://")

        from asyncpg_listen import NotificationListener, connect_func

        listener = NotificationListener(connect_func(dsn))

        async def _handle(notification):
            try:
                payload = json.loads(notification.payload) if notification.payload else {}
            except json.JSONDecodeError:
                payload = {"raw": notification.payload}

            if payload.get("table") == "events" and payload.get("action") == "INSERT":
                message = await _hydrate_event_message(payload.get("id"))
                if message is not None:
                    await manager.broadcast_json(message.model_dump())
                    return

            msg = EventMessage(
                type=payload.get("event_type", notification.channel),
                data=jsonable_encoder(payload),
                timestamp=datetime.now(timezone.utc).isoformat(),
            )
            await manager.broadcast_json(msg.model_dump())

        listener.register("nexus_events", _handle)
        await listener.run()
    except Exception:
        # If PG NOTIFY is unavailable (e.g. no trigger installed yet) we
        # silently fall back to API-only mode.  The WebSocket endpoint still
        # works -- clients just won't receive push events until the trigger is
        # configured.
        pass


@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """WebSocket endpoint for real-time dashboard updates."""
    await manager.connect(websocket)

    # Send an initial connection-established message.
    welcome = EventMessage(
        type="connected",
        data={"message": "Connected to NEXUS Observatory"},
        timestamp=datetime.now(timezone.utc).isoformat(),
    )
    await websocket.send_json(welcome.model_dump())

    try:
        while True:
            # Keep the connection alive by reading (and ignoring) client messages.
            await websocket.receive_text()
    except WebSocketDisconnect:
        await manager.disconnect(websocket)


# ── Startup helper ────────────────────────────────────────────────────────

_listener_task: asyncio.Task | None = None


async def start_notify_listener():
    """Start the PG NOTIFY listener as a background task.

    Called from the FastAPI lifespan.
    """
    global _listener_task
    _listener_task = asyncio.create_task(_pg_notify_listener())


async def stop_notify_listener():
    """Cancel the listener task on shutdown."""
    global _listener_task
    if _listener_task is not None:
        _listener_task.cancel()
        try:
            await _listener_task
        except (asyncio.CancelledError, Exception):
            pass
        _listener_task = None
