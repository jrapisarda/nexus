"""Confidence propagation through the knowledge graph."""

from uuid import UUID
from decimal import Decimal

import sqlalchemy as sa
from nexus_core.models.knowledge_graph import knowledge_graph_nodes, knowledge_graph_edges
import structlog

logger = structlog.get_logger(__name__)


async def propagate_confidence(
    conn,
    challenged_node_id: UUID,
    new_confidence: float,
    decay_per_hop: float = 0.7,
    max_depth: int = 6,
):
    """Propagate confidence changes through the KG when a node is challenged.

    Uses a recursive approach: find all downstream nodes connected via edges,
    reduce their confidence by the dampened factor at each hop.
    """
    # Update the challenged node directly
    await conn.execute(
        knowledge_graph_nodes.update()
        .where(knowledge_graph_nodes.c.node_id == challenged_node_id)
        .values(confidence_score=Decimal(str(new_confidence)))
    )

    # Find and update all downstream nodes using recursive CTE
    # The confidence impact decreases by decay_per_hop at each level
    await _propagate_downstream(conn, challenged_node_id, new_confidence, decay_per_hop, max_depth)

    logger.info("confidence_propagated",
                challenged_node=str(challenged_node_id),
                new_confidence=new_confidence,
                decay=decay_per_hop,
                max_depth=max_depth)


async def _propagate_downstream(
    conn,
    source_node_id: UUID,
    source_confidence: float,
    decay_per_hop: float,
    max_depth: int,
):
    """Propagate confidence reduction to downstream nodes via edges."""
    # Use recursive CTE to find all descendants
    descendants_query = sa.text("""
        WITH RECURSIVE downstream AS (
            -- Base case: direct children of the challenged node
            SELECT
                e.target_node_id AS node_id,
                e.edge_id,
                e.confidence_score AS edge_confidence,
                1 AS depth,
                ARRAY[e.source_node_id, e.target_node_id] AS path
            FROM knowledge_graph_edges e
            WHERE e.source_node_id = :source_id
              AND e.status != 'refuted'

            UNION ALL

            -- Recursive case: follow edges from found nodes
            SELECT
                e.target_node_id,
                e.edge_id,
                e.confidence_score,
                d.depth + 1,
                d.path || e.target_node_id
            FROM knowledge_graph_edges e
            JOIN downstream d ON e.source_node_id = d.node_id
            WHERE d.depth < :max_depth
              AND e.target_node_id != ALL(d.path)  -- Prevent cycles
              AND e.status != 'refuted'
        )
        SELECT DISTINCT ON (node_id) node_id, depth
        FROM downstream
        ORDER BY node_id, depth ASC
    """)

    result = await conn.execute(descendants_query, {
        "source_id": source_node_id,
        "max_depth": max_depth,
    })

    descendants = result.fetchall()

    for row in descendants:
        descendant_id = row.node_id
        depth = row.depth

        # Calculate dampened confidence factor
        dampening = decay_per_hop ** depth

        # Get current confidence of the descendant
        current_q = await conn.execute(
            sa.select(knowledge_graph_nodes.c.confidence_score)
            .where(knowledge_graph_nodes.c.node_id == descendant_id)
        )
        current_conf = float(current_q.scalar_one())

        # New confidence = current * (1 - (1 - source_confidence/original) * dampening)
        # Simplified: reduce proportionally to how much the source was reduced
        confidence_reduction = (1.0 - source_confidence) * dampening
        new_conf = max(current_conf * (1.0 - confidence_reduction), 0.0)

        await conn.execute(
            knowledge_graph_nodes.update()
            .where(knowledge_graph_nodes.c.node_id == descendant_id)
            .values(confidence_score=Decimal(str(round(new_conf, 3))))
        )

        logger.debug("confidence_propagated_to_descendant",
                      node_id=str(descendant_id),
                      depth=depth,
                      new_confidence=new_conf)


async def recalculate_node_confidence(conn, node_id: UUID) -> float:
    """Recalculate a node's confidence based on its validation and challenge history.

    Formula: base_confidence * (validations / (validations + challenge_failures + 1))
    """
    result = await conn.execute(
        sa.select(
            knowledge_graph_nodes.c.confidence_score,
            knowledge_graph_nodes.c.validation_count,
            knowledge_graph_nodes.c.challenge_count,
            knowledge_graph_nodes.c.challenge_failures,
        ).where(knowledge_graph_nodes.c.node_id == node_id)
    )
    row = result.first()
    if row is None:
        return 0.0

    base_conf = float(row.confidence_score)
    validations = row.validation_count
    failures = row.challenge_failures

    # Bayesian-inspired update
    if validations + failures == 0:
        new_conf = base_conf
    else:
        # More validations increase confidence, more failures decrease it
        success_ratio = validations / (validations + failures + 1)
        new_conf = base_conf * (0.5 + 0.5 * success_ratio)

    new_conf = round(max(min(new_conf, 1.0), 0.0), 3)

    await conn.execute(
        knowledge_graph_nodes.update()
        .where(knowledge_graph_nodes.c.node_id == node_id)
        .values(confidence_score=Decimal(str(new_conf)))
    )

    return new_conf
