"""Evolution / lineage endpoints for the NEXUS Observatory API."""

from __future__ import annotations

import sqlalchemy as sa
from fastapi import APIRouter

from nexus_core.database import get_connection
from nexus_core.economy.ledger import balance_expression
from nexus_core.models.personas import agent_personas

from nexus_api.schemas import LineageNode, EvolutionLineageResponse

router = APIRouter(prefix="/api/evolution", tags=["evolution"])


@router.get("/lineage", response_model=EvolutionLineageResponse)
async def evolution_lineage():
    """Return the full evolutionary tree (parent->child persona relationships)."""
    async with get_connection() as conn:
        result = await conn.execute(
            sa.select(
                agent_personas.c.persona_id,
                agent_personas.c.persona_name,
                agent_personas.c.role_class,
                agent_personas.c.generation,
                agent_personas.c.status,
                agent_personas.c.parent_persona_id,
                balance_expression(agent_personas.c.persona_id).label("credit_balance"),
            ).order_by(agent_personas.c.generation, agent_personas.c.created_at)
        )

        nodes = []
        for row in result:
            nodes.append(LineageNode(
                persona_id=row.persona_id,
                persona_name=row.persona_name,
                role_class=row.role_class,
                generation=row.generation,
                status=row.status,
                parent_persona_id=row.parent_persona_id,
                credit_balance=float(row.credit_balance) if row.credit_balance is not None else 0.0,
            ))

    return EvolutionLineageResponse(nodes=nodes)
