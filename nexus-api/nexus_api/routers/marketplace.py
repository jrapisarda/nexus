"""Marketplace read APIs for the NEXUS observatory."""

from __future__ import annotations

from decimal import Decimal
from typing import Any
from uuid import UUID

import sqlalchemy as sa
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from nexus_core.database import get_connection
from nexus_core.market.node_ownership import (
    compute_node_value,
    get_owned_nodes,
    purchase_node,
    sell_node,
)
from nexus_core.models.knowledge_graph import knowledge_graph_nodes
from nexus_core.models.personas import agent_personas
from nexus_core.market.service import (
    get_market_activity,
    get_marketplace_listings,
    get_marketplace_overview,
    get_service_contracts,
)

from nexus_api.schemas import (
    MarketActivityItemResponse,
    MarketActivityResponse,
    MarketOverviewResponse,
    MarketplaceListingResponse,
    ServiceContractResponse,
)


router = APIRouter(prefix="/api/marketplace", tags=["marketplace"])


@router.get("/overview", response_model=MarketOverviewResponse)
async def marketplace_overview():
    async with get_connection() as conn:
        payload = await get_marketplace_overview(conn)
    return MarketOverviewResponse(**payload)


@router.get("/listings", response_model=list[MarketplaceListingResponse])
async def marketplace_listings(limit: int = Query(50, ge=1, le=200)):
    async with get_connection() as conn:
        rows = await get_marketplace_listings(conn, limit=limit)
    return [MarketplaceListingResponse(**row) for row in rows]


@router.get("/contracts", response_model=list[ServiceContractResponse])
async def marketplace_contracts(limit: int = Query(50, ge=1, le=200)):
    async with get_connection() as conn:
        rows = await get_service_contracts(conn, limit=limit)
    return [ServiceContractResponse(**row) for row in rows]


@router.get("/activity", response_model=MarketActivityResponse)
async def marketplace_activity(limit: int = Query(50, ge=1, le=200)):
    async with get_connection() as conn:
        rows = await get_market_activity(conn, limit=limit)
    return MarketActivityResponse(
        items=[MarketActivityItemResponse(**row) for row in rows],
        count=len(rows),
    )


# ── KG Node Ownership ────────────────────────────────────────────────────


class NodePurchaseRequest(BaseModel):
    persona_id: UUID


@router.get("/kg-nodes")
async def list_kg_nodes(
    owned_only: bool = Query(False),
    persona_id: UUID | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
) -> list[dict[str, Any]]:
    """List KG nodes with ownership and valuation info."""
    async with get_connection() as conn:
        query = (
            sa.select(
                knowledge_graph_nodes.c.node_id,
                knowledge_graph_nodes.c.label,
                knowledge_graph_nodes.c.node_type,
                knowledge_graph_nodes.c.confidence_score,
                knowledge_graph_nodes.c.validation_count,
                knowledge_graph_nodes.c.betweenness_score,
                knowledge_graph_nodes.c.last_traversal_count,
                knowledge_graph_nodes.c.owner_persona_id,
                knowledge_graph_nodes.c.purchase_price,
                knowledge_graph_nodes.c.acquired_at,
                knowledge_graph_nodes.c.status,
            )
            .where(knowledge_graph_nodes.c.status.in_(["validated", "proposed"]))
            .order_by(
                knowledge_graph_nodes.c.betweenness_score.desc(),
                knowledge_graph_nodes.c.confidence_score.desc(),
            )
            .limit(limit)
        )

        if owned_only:
            query = query.where(knowledge_graph_nodes.c.owner_persona_id.isnot(None))
        if persona_id is not None:
            query = query.where(knowledge_graph_nodes.c.owner_persona_id == persona_id)

        result = await conn.execute(query)
        nodes = result.fetchall()

        # Get owner names
        owner_ids = {n.owner_persona_id for n in nodes if n.owner_persona_id}
        owner_map: dict = {}
        if owner_ids:
            name_result = await conn.execute(
                sa.select(agent_personas.c.persona_id, agent_personas.c.persona_name, agent_personas.c.role_class)
                .where(agent_personas.c.persona_id.in_(list(owner_ids)))
            )
            for row in name_result:
                owner_map[row.persona_id] = {"name": row.persona_name, "role": row.role_class}

        items = []
        for n in nodes:
            current_value = await compute_node_value(conn, n.node_id)
            owner = owner_map.get(n.owner_persona_id, {})
            unrealized_pnl = float(current_value - Decimal(str(n.purchase_price or 0))) if n.owner_persona_id else None

            items.append({
                "node_id": str(n.node_id),
                "label": n.label,
                "node_type": n.node_type,
                "status": n.status,
                "confidence": float(n.confidence_score or 0),
                "validation_count": n.validation_count or 0,
                "betweenness": float(n.betweenness_score or 0),
                "traversals": n.last_traversal_count or 0,
                "current_value": float(current_value),
                "owner_persona_id": str(n.owner_persona_id) if n.owner_persona_id else None,
                "owner_name": owner.get("name"),
                "owner_role": owner.get("role"),
                "purchase_price": float(n.purchase_price) if n.purchase_price else None,
                "unrealized_pnl": round(unrealized_pnl, 2) if unrealized_pnl is not None else None,
                "acquired_at": n.acquired_at.isoformat() if n.acquired_at else None,
            })

    return items


@router.get("/kg-nodes/portfolio/{persona_id}")
async def get_node_portfolio(persona_id: UUID) -> list[dict[str, Any]]:
    """Get a persona's KG node portfolio with current valuations."""
    async with get_connection() as conn:
        return await get_owned_nodes(conn, persona_id)


@router.post("/kg-nodes/{node_id}/purchase")
async def purchase_kg_node(node_id: UUID, body: NodePurchaseRequest) -> dict[str, Any]:
    """Purchase an unowned KG node for a persona."""
    async with get_connection() as conn:
        try:
            result = await purchase_node(conn, body.persona_id, node_id)
            return result
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))


@router.post("/kg-nodes/{node_id}/sell")
async def sell_kg_node(node_id: UUID, body: NodePurchaseRequest) -> dict[str, Any]:
    """Sell an owned KG node back to the system."""
    async with get_connection() as conn:
        try:
            result = await sell_node(conn, body.persona_id, node_id)
            return result
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
