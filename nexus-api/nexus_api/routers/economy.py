"""Economy endpoints for the NEXUS Observatory API."""

from __future__ import annotations

from decimal import Decimal
from typing import Any
from uuid import UUID

import sqlalchemy as sa
from fastapi import APIRouter, Query

from nexus_core.database import get_connection
from nexus_core.economy.diversity import get_economy_summary
from nexus_core.economy.ledger import get_all_balances, get_ledger_entries
from nexus_core.market.node_ownership import compute_node_value
from nexus_core.models.knowledge_graph import knowledge_graph_nodes
from nexus_core.models.market import market_positions, market_reservations
from nexus_core.models.personas import agent_personas

from nexus_api.schemas import EconomySummaryResponse, LedgerEntryResponse

router = APIRouter(prefix="/api/economy", tags=["economy"])


@router.get("/summary", response_model=EconomySummaryResponse)
async def economy_summary():
    """Get economy health metrics: Gini coefficient, balances, totals."""
    async with get_connection() as conn:
        summary = await get_economy_summary(conn)

    return EconomySummaryResponse(**summary)


@router.get("/ledger", response_model=list[LedgerEntryResponse])
async def economy_ledger(
    persona_id: UUID | None = Query(None, description="Filter by persona"),
    transaction_type: str | None = Query(None, description="Filter by type"),
    limit: int = Query(100, ge=1, le=1000),
):
    """Get recent ledger entries with optional filters."""
    async with get_connection() as conn:
        entries = await get_ledger_entries(
            conn,
            persona_id=persona_id,
            transaction_type=transaction_type,
            limit=limit,
        )

    responses = []
    for entry in entries:
        # Coerce Decimal amount to float
        if entry.get("amount") is not None:
            entry["amount"] = float(entry["amount"])
        responses.append(LedgerEntryResponse(**entry))

    return responses


@router.get("/net-worth")
async def get_net_worth_leaderboard() -> list[dict[str, Any]]:
    """Get net worth for all active agents: liquid + positions + owned nodes - reservations."""
    async with get_connection() as conn:
        # 1. Liquid balances
        balances = await get_all_balances(conn)

        # 2. System personas to exclude
        system_q = await conn.execute(
            sa.select(agent_personas.c.persona_id)
            .where(agent_personas.c.role_class == "system")
        )
        system_ids = {row.persona_id for row in system_q}

        # 3. Position values per persona
        pos_result = await conn.execute(
            sa.select(
                market_positions.c.persona_id,
                sa.func.coalesce(sa.func.sum(market_positions.c.market_value), Decimal("0")).label("total_positions"),
            )
            .where(market_positions.c.net_quantity > 0)
            .group_by(market_positions.c.persona_id)
        )
        position_values = {row.persona_id: Decimal(str(row.total_positions)) for row in pos_result}

        # 4. Owned node values per persona
        owned_result = await conn.execute(
            sa.select(
                knowledge_graph_nodes.c.node_id,
                knowledge_graph_nodes.c.owner_persona_id,
            ).where(knowledge_graph_nodes.c.owner_persona_id.isnot(None))
        )
        node_values_by_persona: dict[UUID, Decimal] = {}
        for row in owned_result:
            value = await compute_node_value(conn, row.node_id)
            node_values_by_persona[row.owner_persona_id] = (
                node_values_by_persona.get(row.owner_persona_id, Decimal("0")) + value
            )

        # 5. Reservations per persona
        res_result = await conn.execute(
            sa.select(
                market_reservations.c.persona_id,
                sa.func.coalesce(sa.func.sum(market_reservations.c.remaining_amount), Decimal("0")).label("total_reserved"),
            )
            .where(market_reservations.c.status == "open")
            .group_by(market_reservations.c.persona_id)
        )
        reservations = {row.persona_id: Decimal(str(row.total_reserved)) for row in res_result}

        # 6. Persona names
        name_result = await conn.execute(
            sa.select(
                agent_personas.c.persona_id,
                agent_personas.c.persona_name,
                agent_personas.c.role_class,
            ).where(agent_personas.c.status == "active")
        )
        personas = {row.persona_id: {"name": row.persona_name, "role": row.role_class} for row in name_result}

    # Build results
    results = []
    all_pids = set(balances.keys()) | set(personas.keys())
    for pid in all_pids:
        if pid in system_ids:
            continue
        info = personas.get(pid, {})
        liquid = float(balances.get(pid, Decimal("0")))
        positions = float(position_values.get(pid, Decimal("0")))
        nodes = float(node_values_by_persona.get(pid, Decimal("0")))
        reserved = float(reservations.get(pid, Decimal("0")))
        net = liquid + positions + nodes - reserved

        results.append({
            "persona_id": str(pid),
            "name": info.get("name", "Unknown"),
            "role_class": info.get("role", ""),
            "liquid_balance": round(liquid, 2),
            "position_value": round(positions, 2),
            "node_value": round(nodes, 2),
            "reserved": round(reserved, 2),
            "net_worth": round(net, 2),
        })

    results.sort(key=lambda x: x["net_worth"], reverse=True)
    return results
