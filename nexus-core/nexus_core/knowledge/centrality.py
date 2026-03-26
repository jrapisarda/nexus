"""Betweenness centrality computation for KG node valuation."""

from __future__ import annotations

from decimal import Decimal

import networkx as nx
import sqlalchemy as sa
import structlog

from nexus_core.models.knowledge_graph import knowledge_graph_nodes, knowledge_graph_edges

logger = structlog.get_logger(__name__)


async def refresh_betweenness_scores(conn) -> int:
    """Recompute betweenness centrality for all KG nodes and store results.

    Uses NetworkX for graph analysis. Called once per scheduler cycle.
    Returns count of nodes updated.
    """
    # Load all edges into a NetworkX graph
    edge_rows = await conn.execute(
        sa.select(
            knowledge_graph_edges.c.source_node_id,
            knowledge_graph_edges.c.target_node_id,
            knowledge_graph_edges.c.weight,
        ).where(knowledge_graph_edges.c.status != "rejected")
    )
    edges = edge_rows.fetchall()

    if not edges:
        return 0

    G = nx.DiGraph()
    for edge in edges:
        G.add_edge(
            str(edge.source_node_id),
            str(edge.target_node_id),
            weight=float(edge.weight or 0.5),
        )

    if G.number_of_nodes() == 0:
        return 0

    # Compute betweenness centrality
    # For large graphs (>1000 nodes), use approximate betweenness with k samples
    if G.number_of_nodes() > 1000:
        centrality = nx.betweenness_centrality(G, k=min(100, G.number_of_nodes()), weight="weight")
    else:
        centrality = nx.betweenness_centrality(G, weight="weight")

    # Update all nodes with their centrality scores
    updated = 0
    for node_str, score in centrality.items():
        try:
            from uuid import UUID
            node_uuid = UUID(node_str)
        except (ValueError, AttributeError):
            continue

        await conn.execute(
            knowledge_graph_nodes.update()
            .where(knowledge_graph_nodes.c.node_id == node_uuid)
            .values(betweenness_score=Decimal(str(round(score, 6))))
        )
        updated += 1

    if updated > 0:
        logger.info("betweenness_centrality_refreshed", nodes_updated=updated, graph_nodes=G.number_of_nodes(), graph_edges=G.number_of_edges())

    return updated
