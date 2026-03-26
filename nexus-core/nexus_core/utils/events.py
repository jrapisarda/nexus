"""Event outbox helper for NEXUS."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncConnection


async def emit_event(
    conn: AsyncConnection,
    event_type: str,
    entity_id: UUID | None = None,
    entity_type: str | None = None,
    payload: dict[str, Any] | None = None,
) -> None:
    """Insert an event into the outbox within the caller's transaction.

    This must be called inside an existing transaction so the event is
    atomically committed alongside the business data change.

    Args:
        conn: An active ``AsyncConnection`` (inside a transaction).
        event_type: A dot-separated event name, e.g. ``"objective.created"``.
        entity_id: Optional UUID of the primary entity the event concerns.
        entity_type: Optional entity type label (e.g. ``"objective"``).
        payload: Arbitrary JSON-serialisable dict with event details.
    """
    from nexus_core.models.events import events

    await conn.execute(
        events.insert().values(
            event_type=event_type,
            entity_id=entity_id,
            entity_type=entity_type,
            payload=payload or {},
        )
    )
