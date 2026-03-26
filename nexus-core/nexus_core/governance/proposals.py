"""Governance proposal management for NEXUS."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional
from uuid import UUID

import sqlalchemy as sa
import structlog

from nexus_core.models.governance import governance_proposals
from nexus_core.utils.events import emit_event

logger = structlog.get_logger(__name__)

# Default voting window
DEFAULT_VOTING_WINDOW_HOURS = 24


async def create_proposal(
    conn,
    proposer_id: UUID,
    proposal_type: str,
    title: str,
    description: str,
    rationale: str,
    target_persona_id: UUID | None = None,
) -> UUID:
    """Create a new governance proposal.

    Args:
        conn: Active database connection.
        proposer_id: persona_id of the proposing agent.
        proposal_type: Type of proposal (e.g. ``"deprecate_persona"``,
            ``"activate_persona"``, ``"rule_change"``, ``"parameter_update"``).
        title: Short proposal title.
        description: Full description of what the proposal would change.
        rationale: Why the proposal is being made.
        target_persona_id: Optional persona affected by the proposal.

    Returns:
        The ``proposal_id`` of the newly created proposal.
    """
    voting_deadline = datetime.now(timezone.utc) + timedelta(hours=DEFAULT_VOTING_WINDOW_HOURS)

    result = await conn.execute(
        governance_proposals.insert().values(
            proposed_by_persona_id=proposer_id,
            proposal_type=proposal_type,
            title=title,
            description=description,
            rationale=rationale,
            target_persona_id=target_persona_id,
            status="proposed",
            voting_deadline=voting_deadline,
        ).returning(governance_proposals.c.proposal_id)
    )
    proposal_id = result.scalar_one()

    await emit_event(
        conn, "governance_proposal_created",
        entity_id=proposal_id, entity_type="proposal",
        payload={
            "proposer_id": str(proposer_id),
            "proposal_type": proposal_type,
            "title": title,
            "target_persona_id": str(target_persona_id) if target_persona_id else None,
        },
    )

    logger.info(
        "governance_proposal_created",
        proposal_id=str(proposal_id),
        proposal_type=proposal_type,
        title=title,
    )
    return proposal_id


async def get_pending_proposals(conn) -> list[dict]:
    """Get all proposals with status ``"proposed"`` that are still within the voting window.

    Returns a list of dicts, one per proposal.
    """
    now = datetime.now(timezone.utc)

    result = await conn.execute(
        governance_proposals.select()
        .where(
            governance_proposals.c.status == "proposed",
            sa.or_(
                governance_proposals.c.voting_deadline.is_(None),
                governance_proposals.c.voting_deadline >= now,
            ),
        )
        .order_by(governance_proposals.c.created_at.asc())
    )
    return [dict(row._mapping) for row in result]


async def get_proposal(conn, proposal_id: UUID) -> Optional[dict]:
    """Fetch a single proposal by ID.

    Returns ``None`` if not found.
    """
    result = await conn.execute(
        governance_proposals.select()
        .where(governance_proposals.c.proposal_id == proposal_id)
    )
    row = result.one_or_none()
    if row is None:
        return None
    return dict(row._mapping)


async def update_proposal_status(
    conn,
    proposal_id: UUID,
    status: str,
) -> None:
    """Update the status of a governance proposal.

    Valid statuses: ``"proposed"``, ``"voting"``, ``"approved"``,
    ``"rejected"``, ``"executed"``, ``"expired"``.
    """
    values: dict = {"status": status}
    if status in ("approved", "rejected", "executed", "expired"):
        values["resolved_at"] = sa.func.now()

    await conn.execute(
        governance_proposals.update()
        .where(governance_proposals.c.proposal_id == proposal_id)
        .values(**values)
    )

    await emit_event(
        conn, "governance_proposal_status_changed",
        entity_id=proposal_id, entity_type="proposal",
        payload={"new_status": status},
    )

    logger.info(
        "governance_proposal_status_updated",
        proposal_id=str(proposal_id),
        new_status=status,
    )
