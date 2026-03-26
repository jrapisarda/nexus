"""Agent/persona endpoints for the NEXUS Observatory API."""

from __future__ import annotations

from uuid import UUID

import sqlalchemy as sa
from fastapi import APIRouter, HTTPException, Query

from nexus_core.database import get_connection
from nexus_core.models.civilization import persona_capability_scores
from nexus_core.economy.ledger import balance_expression
from nexus_core.models.personas import agent_personas
from nexus_core.models.objectives import objectives
from nexus_core.models.instances import agent_instances

from nexus_api.schemas import PersonaResponse, PersonaListResponse

router = APIRouter(prefix="/api/agents", tags=["agents"])


def _current_assignment_lateral():
    assignment_rank = sa.case(
        (agent_instances.c.status == "running", 0),
        (agent_instances.c.status == "pending", 1),
        (agent_instances.c.status == "completed", 2),
        else_=3,
    )
    return (
        sa.select(
            objectives.c.title.label("current_assignment"),
            agent_instances.c.status.label("current_assignment_status"),
            agent_instances.c.started_at.label("current_assignment_started_at"),
            agent_instances.c.spawn_reason.label("current_assignment_reason"),
        )
        .join(objectives, agent_instances.c.objective_id == objectives.c.objective_id)
        .where(
            agent_instances.c.persona_id == agent_personas.c.persona_id,
            agent_instances.c.status.in_(["running", "pending", "completed"]),
        )
        .order_by(assignment_rank, agent_instances.c.started_at.desc())
        .limit(1)
        .lateral("current_assignment")
    )


def _persona_query():
    current_assignment = _current_assignment_lateral()
    return (
        sa.select(
            *agent_personas.c,
            balance_expression(agent_personas.c.persona_id).label("credit_balance"),
            current_assignment.c.current_assignment,
            current_assignment.c.current_assignment_status,
            current_assignment.c.current_assignment_started_at,
            current_assignment.c.current_assignment_reason,
        )
        .select_from(agent_personas.outerjoin(current_assignment, sa.true()))
    )


async def _load_capability_map(conn, persona_ids: list[UUID]) -> dict[UUID, dict[str, float]]:
    if not persona_ids:
        return {}
    rows = (
        await conn.execute(
            sa.select(
                persona_capability_scores.c.persona_id,
                persona_capability_scores.c.capability,
                persona_capability_scores.c.active_score,
                persona_capability_scores.c.persistent_score,
            ).where(persona_capability_scores.c.persona_id.in_(persona_ids))
        )
    ).fetchall()
    capabilities: dict[UUID, dict[str, float]] = {}
    for row in rows:
        capabilities.setdefault(row.persona_id, {})[row.capability] = round(
            float(row.active_score) * 0.65 + float(row.persistent_score) * 0.35,
            3,
        )
    return capabilities


def _row_to_persona(row, capability_scores: dict[str, float] | None = None) -> PersonaResponse:
    """Convert a DB row to PersonaResponse, coercing Decimal fields to float."""
    d = dict(row._mapping)
    # Remove specialization_vector -- it's a pgvector type that doesn't serialise to JSON.
    d.pop("specialization_vector", None)
    for key in ("credit_balance", "reputation_score", "compute_budget"):
        if d.get(key) is not None:
            d[key] = float(d[key])
    d["capability_scores"] = capability_scores or {}
    return PersonaResponse(**d)


@router.get("", response_model=PersonaListResponse)
async def list_agents(
    status: str | None = Query(None, description="Filter by status (active, deprecated)"),
    role_class: str | None = Query(None, description="Filter by role_class"),
):
    """List all agent personas with optional filters."""
    async with get_connection() as conn:
        query = _persona_query().order_by(
            sa.literal_column("current_assignment_started_at").desc().nullslast(),
            agent_personas.c.created_at.desc(),
        )
        if status:
            query = query.where(agent_personas.c.status == status)
        if role_class:
            query = query.where(agent_personas.c.role_class == role_class)

        result = await conn.execute(query)
        rows = result.fetchall()
        capability_map = await _load_capability_map(conn, [row.persona_id for row in rows])
        personas = [_row_to_persona(row, capability_map.get(row.persona_id)) for row in rows]

    return PersonaListResponse(personas=personas, count=len(personas))


@router.get("/{persona_id}", response_model=PersonaResponse)
async def get_agent(persona_id: UUID):
    """Get detailed info for a single persona, including current assignment."""
    async with get_connection() as conn:
        result = await conn.execute(
            _persona_query().where(agent_personas.c.persona_id == persona_id)
        )
        row = result.first()
        if row is None:
            raise HTTPException(status_code=404, detail="Persona not found")
        capability_map = await _load_capability_map(conn, [persona_id])

    return _row_to_persona(row, capability_map.get(persona_id))
