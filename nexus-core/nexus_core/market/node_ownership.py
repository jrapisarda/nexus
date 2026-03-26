"""KG Node Ownership — real estate for the NEXUS agent civilization.

Agents can purchase KG nodes as appreciating assets. Nodes generate yield
from traversal frequency, appreciate from research activity, and depreciate
from neglect or red team challenges.
"""

from __future__ import annotations

from decimal import Decimal
from uuid import UUID

import sqlalchemy as sa
import structlog

from nexus_core.economy.ledger import mint_credits, get_balance
from nexus_core.models.economy import economy_ledger
from nexus_core.models.knowledge_graph import knowledge_graph_nodes, knowledge_graph_edges
from nexus_core.models.market import kg_node_bids
from nexus_core.models.personas import agent_personas
from nexus_core.utils.events import emit_event

logger = structlog.get_logger(__name__)

MONEY_QUANT = Decimal("0.01")
FEE_POOL_PERSONA_ID = UUID("00000000-0000-0000-0000-000000000002")


def _money(v) -> Decimal:
    if v is None:
        return Decimal("0.00")
    return Decimal(str(v)).quantize(MONEY_QUANT)


async def compute_node_value(
    conn,
    node_id: UUID,
    *,
    base_price: Decimal = Decimal("5.00"),
    edge_value_multiplier: Decimal = Decimal("10.00"),
    centrality_multiplier: Decimal = Decimal("50.00"),
    min_price: Decimal = Decimal("5.00"),
    max_price: Decimal = Decimal("500.00"),
) -> Decimal:
    """Compute the fair value of a KG node based on multi-dimensional quality.

    value = base + (edge_count × mean_edge_weight × confidence) × multiplier
            + betweenness_score × centrality_multiplier
    """
    # Get node info
    node_row = await conn.execute(
        sa.select(
            knowledge_graph_nodes.c.confidence_score,
            knowledge_graph_nodes.c.betweenness_score,
            knowledge_graph_nodes.c.validation_count,
        ).where(knowledge_graph_nodes.c.node_id == node_id)
    )
    node = node_row.first()
    if node is None:
        return min_price

    confidence = Decimal(str(node.confidence_score or "0.5"))
    betweenness = Decimal(str(node.betweenness_score or "0"))
    validation_bonus = Decimal(str(node.validation_count or 0)) * Decimal("1.5")

    # Count edges and mean weight
    edge_result = await conn.execute(
        sa.select(
            sa.func.count().label("edge_count"),
            sa.func.coalesce(sa.func.avg(knowledge_graph_edges.c.weight), Decimal("0.5")).label("mean_weight"),
        ).where(
            sa.or_(
                knowledge_graph_edges.c.source_node_id == node_id,
                knowledge_graph_edges.c.target_node_id == node_id,
            )
        )
    )
    erow = edge_result.first()
    edge_count = Decimal(str(erow.edge_count or 0))
    mean_weight = Decimal(str(erow.mean_weight or "0.5"))

    # Edge quality: count × mean_weight × confidence
    edge_quality = edge_count * mean_weight * confidence

    # Centrality premium
    centrality_premium = betweenness * centrality_multiplier

    # Total
    value = base_price + (edge_quality * edge_value_multiplier) + centrality_premium + validation_bonus
    return _money(max(min_price, min(value, max_price)))


async def purchase_node(
    conn,
    persona_id: UUID,
    node_id: UUID,
    *,
    base_price: Decimal = Decimal("5.00"),
    edge_value_multiplier: Decimal = Decimal("10.00"),
    centrality_multiplier: Decimal = Decimal("50.00"),
    min_price: Decimal = Decimal("5.00"),
    max_price: Decimal = Decimal("500.00"),
    max_owned: int = 5,
    max_portfolio_pct: Decimal = Decimal("0.15"),
    capability_gate: Decimal = Decimal("0.50"),
    superlinear_factor: Decimal = Decimal("0.20"),
) -> dict:
    """Agent purchases an unowned KG node.

    Returns dict with purchase details or raises ValueError on failure.
    """
    # 1. Verify node exists and is unowned
    node_row = await conn.execute(
        sa.select(
            knowledge_graph_nodes.c.node_id,
            knowledge_graph_nodes.c.label,
            knowledge_graph_nodes.c.owner_persona_id,
            knowledge_graph_nodes.c.status,
        ).where(knowledge_graph_nodes.c.node_id == node_id)
    )
    node = node_row.first()
    if node is None:
        raise ValueError(f"Node {node_id} does not exist")
    if node.owner_persona_id is not None:
        raise ValueError(f"Node {node_id} is already owned")
    if node.status not in ("validated", "proposed"):
        raise ValueError(f"Node {node_id} has status '{node.status}' — only validated/proposed nodes can be purchased")

    # 2. Check persona is not a system persona
    persona_row = await conn.execute(
        sa.select(
            agent_personas.c.role_class,
            agent_personas.c.reputation_score,
        ).where(agent_personas.c.persona_id == persona_id)
    )
    persona = persona_row.first()
    if persona is None:
        raise ValueError(f"Persona {persona_id} not found")
    if persona.role_class == "system":
        raise ValueError("System personas cannot own KG nodes")

    # 3. Capability gate
    rep = Decimal(str(persona.reputation_score or 0))
    if rep < capability_gate:
        raise ValueError(f"Reputation {rep} below capability gate {capability_gate}")

    # 4. Portfolio cap
    owned_count_result = await conn.execute(
        sa.select(sa.func.count()).select_from(knowledge_graph_nodes)
        .where(knowledge_graph_nodes.c.owner_persona_id == persona_id)
    )
    owned_count = owned_count_result.scalar_one()
    if owned_count >= max_owned:
        raise ValueError(f"Portfolio cap reached: already owns {owned_count}/{max_owned} nodes")

    # 5. Compute value with superlinear pricing
    base_value = await compute_node_value(
        conn, node_id,
        base_price=base_price,
        edge_value_multiplier=edge_value_multiplier,
        centrality_multiplier=centrality_multiplier,
        min_price=min_price,
        max_price=max_price,
    )
    superlinear_markup = Decimal("1") + (Decimal(str(owned_count)) * superlinear_factor)
    purchase_price = _money(base_value * superlinear_markup)

    # 6. Check balance
    balance = await get_balance(conn, persona_id)
    if balance < purchase_price:
        raise ValueError(f"Insufficient balance: {balance} < {purchase_price}")

    # 7. Debit credits (agent → burn, value stored in the node itself)
    await conn.execute(
        economy_ledger.insert().values(
            from_persona_id=persona_id,
            to_persona_id=None,  # Credits invested in node (removed from circulation)
            amount=purchase_price,
            transaction_type="node_purchase",
            memo=f"Purchased KG node: {node.label[:60]}",
        )
    )

    # 8. Set ownership
    await conn.execute(
        knowledge_graph_nodes.update()
        .where(knowledge_graph_nodes.c.node_id == node_id)
        .values(
            owner_persona_id=persona_id,
            purchase_price=purchase_price,
            acquired_at=sa.func.now(),
        )
    )

    await emit_event(
        conn, "node_acquired",
        entity_id=node_id, entity_type="kg_node",
        payload={
            "persona_id": str(persona_id),
            "purchase_price": str(purchase_price),
            "node_label": node.label[:60],
        },
    )

    logger.info(
        "node_purchased",
        persona_id=str(persona_id),
        node_id=str(node_id),
        price=str(purchase_price),
    )

    return {
        "node_id": str(node_id),
        "label": node.label,
        "purchase_price": str(purchase_price),
        "owned_count": owned_count + 1,
    }


async def sell_node(
    conn,
    persona_id: UUID,
    node_id: UUID,
    **value_kwargs,
) -> dict:
    """Owner sells their KG node back to the system at current market value."""
    # Verify ownership
    node_row = await conn.execute(
        sa.select(
            knowledge_graph_nodes.c.node_id,
            knowledge_graph_nodes.c.label,
            knowledge_graph_nodes.c.owner_persona_id,
            knowledge_graph_nodes.c.purchase_price,
        ).where(knowledge_graph_nodes.c.node_id == node_id)
    )
    node = node_row.first()
    if node is None:
        raise ValueError(f"Node {node_id} does not exist")
    if node.owner_persona_id != persona_id:
        raise ValueError(f"Node {node_id} is not owned by {persona_id}")

    # Compute current value
    current_value = await compute_node_value(conn, node_id, **value_kwargs)

    # Credit seller (mint from system — value was created by research activity)
    await mint_credits(
        conn,
        amount=current_value,
        to_persona_id=persona_id,
        memo=f"Sold KG node: {node.label[:60]}",
    )
    # Update transaction type
    await conn.execute(
        economy_ledger.update()
        .where(
            economy_ledger.c.to_persona_id == persona_id,
            economy_ledger.c.transaction_type == "mint",
            economy_ledger.c.memo == f"Sold KG node: {node.label[:60]}",
        )
        .values(transaction_type="node_sale")
    )

    # Clear ownership
    await conn.execute(
        knowledge_graph_nodes.update()
        .where(knowledge_graph_nodes.c.node_id == node_id)
        .values(
            owner_persona_id=None,
            purchase_price=None,
            acquired_at=None,
        )
    )

    realized_pnl = current_value - _money(node.purchase_price or 0)

    await emit_event(
        conn, "node_sold",
        entity_id=node_id, entity_type="kg_node",
        payload={
            "persona_id": str(persona_id),
            "sale_price": str(current_value),
            "realized_pnl": str(realized_pnl),
        },
    )

    return {
        "node_id": str(node_id),
        "sale_price": str(current_value),
        "purchase_price": str(node.purchase_price),
        "realized_pnl": str(realized_pnl),
    }


async def distribute_node_yields(
    conn,
    yield_pool: Decimal,
) -> int:
    """Distribute yield to node owners based on traversal frequency.

    Returns count of owners who received yield.
    """
    if yield_pool <= Decimal("0"):
        return 0

    # Get all owned nodes with traversal counts
    result = await conn.execute(
        sa.select(
            knowledge_graph_nodes.c.node_id,
            knowledge_graph_nodes.c.owner_persona_id,
            knowledge_graph_nodes.c.last_traversal_count,
        ).where(
            knowledge_graph_nodes.c.owner_persona_id.isnot(None),
            knowledge_graph_nodes.c.last_traversal_count > 0,
        )
    )
    owned_nodes = result.fetchall()

    if not owned_nodes:
        return 0

    total_traversals = sum(n.last_traversal_count for n in owned_nodes)
    if total_traversals == 0:
        return 0

    recipients = 0
    for node in owned_nodes:
        share = Decimal(str(node.last_traversal_count)) / Decimal(str(total_traversals))
        yield_amount = _money(yield_pool * share)
        if yield_amount < Decimal("0.01"):
            continue

        await conn.execute(
            economy_ledger.insert().values(
                from_persona_id=None,  # Minted from system
                to_persona_id=node.owner_persona_id,
                amount=yield_amount,
                transaction_type="node_yield",
                memo=f"Traversal yield for KG node {node.node_id}",
            )
        )
        recipients += 1

    if recipients > 0:
        await emit_event(
            conn, "node_yields_distributed",
            payload={
                "recipients": recipients,
                "total_yield": str(yield_pool),
                "total_traversals": total_traversals,
            },
        )

    return recipients


async def apply_node_depreciation(
    conn,
    depreciation_rate: Decimal = Decimal("0.01"),
    neglect_threshold_cycles: int = 5,
) -> int:
    """Apply knowledge decay to owned nodes without recent traversals.

    Nodes not traversed reduce in confidence. Heavily neglected nodes are
    flagged for potential hostile takeover.
    """
    # Nodes with owner but 0 traversals this cycle
    result = await conn.execute(
        sa.select(
            knowledge_graph_nodes.c.node_id,
            knowledge_graph_nodes.c.confidence_score,
            knowledge_graph_nodes.c.owner_persona_id,
        ).where(
            knowledge_graph_nodes.c.owner_persona_id.isnot(None),
            knowledge_graph_nodes.c.last_traversal_count == 0,
        )
    )
    neglected = result.fetchall()

    depreciated = 0
    for node in neglected:
        new_confidence = max(
            Decimal("0.001"),
            Decimal(str(node.confidence_score)) - depreciation_rate,
        )
        await conn.execute(
            knowledge_graph_nodes.update()
            .where(knowledge_graph_nodes.c.node_id == node.node_id)
            .values(confidence_score=new_confidence)
        )
        depreciated += 1

    return depreciated


async def reset_traversal_counts(conn) -> None:
    """Reset all traversal counts to 0 at the start of each cycle."""
    await conn.execute(
        knowledge_graph_nodes.update()
        .where(knowledge_graph_nodes.c.last_traversal_count > 0)
        .values(last_traversal_count=0)
    )


async def get_owned_nodes(conn, persona_id: UUID) -> list[dict]:
    """Get all nodes owned by a persona with their current values."""
    result = await conn.execute(
        sa.select(
            knowledge_graph_nodes.c.node_id,
            knowledge_graph_nodes.c.label,
            knowledge_graph_nodes.c.node_type,
            knowledge_graph_nodes.c.confidence_score,
            knowledge_graph_nodes.c.purchase_price,
            knowledge_graph_nodes.c.last_traversal_count,
            knowledge_graph_nodes.c.betweenness_score,
            knowledge_graph_nodes.c.acquired_at,
        ).where(knowledge_graph_nodes.c.owner_persona_id == persona_id)
    )
    nodes = []
    for row in result:
        current_value = await compute_node_value(conn, row.node_id)
        unrealized_pnl = current_value - _money(row.purchase_price or 0)
        nodes.append({
            "node_id": str(row.node_id),
            "label": row.label,
            "node_type": row.node_type,
            "confidence": float(row.confidence_score or 0),
            "purchase_price": str(row.purchase_price),
            "current_value": str(current_value),
            "unrealized_pnl": str(unrealized_pnl),
            "traversals": row.last_traversal_count,
            "betweenness": float(row.betweenness_score or 0),
            "acquired_at": row.acquired_at.isoformat() if row.acquired_at else None,
        })
    return nodes
