"""Knowledge graph query operations: traversal, search, subgraph extraction, and stats."""

from dataclasses import dataclass, field
from typing import Optional
from uuid import UUID

import sqlalchemy as sa
from nexus_core.knowledge.graph_ops import normalize_canonical_label
from nexus_core.models.knowledge_graph import knowledge_graph_nodes, knowledge_graph_edges
import structlog

logger = structlog.get_logger(__name__)


@dataclass
class PathStep:
    """A single step in a KG path traversal."""
    node_id: UUID
    label: str
    node_type: str
    confidence: float
    edge_type: Optional[str] = None
    edge_weight: Optional[float] = None
    depth: int = 0


@dataclass
class SubgraphData:
    """A subgraph centered on a node."""
    center_node_id: UUID
    nodes: list[dict] = field(default_factory=list)
    edges: list[dict] = field(default_factory=list)


@dataclass
class KGStats:
    """Knowledge graph statistics."""
    node_count: int = 0
    edge_count: int = 0
    avg_confidence: float = 0.0
    validated_count: int = 0
    proposed_count: int = 0
    contested_count: int = 0
    node_type_counts: dict = field(default_factory=dict)
    relationship_type_counts: dict = field(default_factory=dict)


async def traverse_path(
    conn,
    start_id: UUID,
    max_depth: int = 6,
    min_confidence: float = 0.0,
) -> list[PathStep]:
    """Traverse the KG from a starting node, following edges up to max_depth."""
    result = await conn.execute(sa.text("""
        WITH RECURSIVE kg_path AS (
            -- Base: the start node
            SELECT
                n.node_id, n.label, n.node_type,
                n.confidence_score::float AS confidence,
                NULL::varchar AS edge_type,
                NULL::float AS edge_weight,
                0 AS depth,
                ARRAY[n.node_id] AS visited
            FROM knowledge_graph_nodes n
            WHERE n.node_id = :start_id

            UNION ALL

            -- Recursive: follow outgoing edges
            SELECT
                n.node_id, n.label, n.node_type,
                n.confidence_score::float AS confidence,
                e.relationship_type AS edge_type,
                e.weight::float AS edge_weight,
                p.depth + 1 AS depth,
                p.visited || n.node_id
            FROM kg_path p
            JOIN knowledge_graph_edges e ON e.source_node_id = p.node_id
            JOIN knowledge_graph_nodes n ON n.node_id = e.target_node_id
            WHERE p.depth < :max_depth
              AND n.node_id != ALL(p.visited)
              AND n.confidence_score >= :min_conf
              AND n.status != 'retracted'
              AND e.status != 'refuted'
        )
        SELECT node_id, label, node_type, confidence, edge_type, edge_weight, depth
        FROM kg_path
        ORDER BY depth ASC
    """), {
        "start_id": start_id,
        "max_depth": max_depth,
        "min_conf": min_confidence,
    })

    steps = []
    for row in result:
        steps.append(PathStep(
            node_id=row.node_id,
            label=row.label,
            node_type=row.node_type,
            confidence=row.confidence,
            edge_type=row.edge_type,
            edge_weight=row.edge_weight,
            depth=row.depth,
        ))
    return steps


async def find_similar_nodes(
    conn,
    embedding,
    threshold: float = 0.92,
    limit: int = 5,
) -> list[dict]:
    """Find nodes similar to an embedding using pgvector cosine similarity."""
    try:
        vector = embedding.tolist() if hasattr(embedding, "tolist") else list(embedding)
        distance = knowledge_graph_nodes.c.properties_embedding.cosine_distance(vector)
        result = await conn.execute(
            sa.select(
                knowledge_graph_nodes.c.node_id,
                knowledge_graph_nodes.c.label,
                knowledge_graph_nodes.c.node_type,
                knowledge_graph_nodes.c.properties,
                knowledge_graph_nodes.c.confidence_score,
                (1 - distance).label("similarity"),
            )
            .where(
                knowledge_graph_nodes.c.status != "retracted",
                knowledge_graph_nodes.c.properties_embedding.isnot(None),
            )
            .order_by(distance)
            .limit(limit)
        )

        nodes = []
        for row in result:
            if row.similarity >= threshold:
                nodes.append(dict(row._mapping))
        return nodes
    except Exception as e:
        logger.warning("kg_vector_search_failed", error=str(e))
        return []


async def search_nodes(
    conn,
    query_text: str,
    limit: int = 10,
) -> list[dict]:
    """Search nodes by human-entered labels using exact, prefix, and fuzzy matching."""
    query = (query_text or "").strip()
    if not query:
        return []
    canonical_query = normalize_canonical_label(query)
    try:
        result = await conn.execute(sa.text("""
            SELECT
                node_id,
                label,
                node_type,
                properties,
                confidence_score,
                status,
                GREATEST(
                    CASE
                        WHEN lower(label) = lower(:query) THEN 1.000
                        WHEN canonical_label = :canonical_query THEN 0.995
                        WHEN lower(label) LIKE lower(:prefix_query) THEN 0.970
                        WHEN canonical_label LIKE :canonical_prefix_query THEN 0.960
                        WHEN lower(label) LIKE lower(:contains_query) THEN 0.900
                        WHEN canonical_label LIKE :canonical_contains_query THEN 0.880
                        ELSE 0.000
                    END,
                    similarity(label, :query),
                    similarity(canonical_label, :canonical_query)
                ) AS sim_score
            FROM knowledge_graph_nodes
            WHERE status != 'retracted'
              AND (
                    lower(label) LIKE lower(:contains_query)
                    OR canonical_label LIKE :canonical_contains_query
                    OR similarity(label, :query) > 0.08
                    OR similarity(canonical_label, :canonical_query) > 0.08
                  )
            ORDER BY sim_score DESC, confidence_score DESC, label ASC
            LIMIT :limit
        """), {
            "query": query,
            "canonical_query": canonical_query,
            "prefix_query": f"{query}%",
            "canonical_prefix_query": f"{canonical_query}%",
            "contains_query": f"%{query}%",
            "canonical_contains_query": f"%{canonical_query}%",
            "limit": limit,
        })

        return [dict(row._mapping) for row in result]
    except Exception:
        # Fallback to ILIKE if pg_trgm not available
        result = await conn.execute(
            knowledge_graph_nodes.select()
            .where(
                sa.or_(
                    knowledge_graph_nodes.c.label.ilike(f"%{query}%"),
                    knowledge_graph_nodes.c.canonical_label.ilike(f"%{canonical_query}%"),
                ),
                knowledge_graph_nodes.c.status != "retracted",
            )
            .order_by(knowledge_graph_nodes.c.confidence_score.desc(), knowledge_graph_nodes.c.label.asc())
            .limit(limit)
        )
        return [dict(row._mapping) for row in result]


async def get_subgraph(
    conn,
    center_id: UUID,
    radius: int = 2,
) -> SubgraphData:
    """Get a subgraph centered on a node, including all nodes and edges within radius hops."""
    # Get all nodes within radius
    path_steps = await traverse_path(conn, center_id, max_depth=radius)
    node_ids = {step.node_id for step in path_steps}

    # Get full node data
    nodes = []
    for nid in node_ids:
        result = await conn.execute(
            knowledge_graph_nodes.select()
            .where(knowledge_graph_nodes.c.node_id == nid)
        )
        row = result.first()
        if row:
            nodes.append(dict(row._mapping))

    # Get all edges between these nodes
    if node_ids:
        node_id_list = list(node_ids)
        result = await conn.execute(
            knowledge_graph_edges.select()
            .where(
                knowledge_graph_edges.c.source_node_id.in_(node_id_list),
                knowledge_graph_edges.c.target_node_id.in_(node_id_list),
            )
        )
        edges = [dict(row._mapping) for row in result]
    else:
        edges = []

    return SubgraphData(center_node_id=center_id, nodes=nodes, edges=edges)


async def get_kg_stats(conn) -> KGStats:
    """Get comprehensive KG statistics."""
    # Node count
    node_count_q = await conn.execute(
        sa.select(sa.func.count()).select_from(knowledge_graph_nodes)
    )
    node_count = node_count_q.scalar_one()

    # Edge count
    edge_count_q = await conn.execute(
        sa.select(sa.func.count()).select_from(knowledge_graph_edges)
    )
    edge_count = edge_count_q.scalar_one()

    # Average confidence
    avg_conf_q = await conn.execute(
        sa.select(sa.func.avg(knowledge_graph_nodes.c.confidence_score))
    )
    avg_conf = avg_conf_q.scalar_one()

    # Status counts
    status_q = await conn.execute(
        sa.select(
            knowledge_graph_nodes.c.status,
            sa.func.count().label("count"),
        ).group_by(knowledge_graph_nodes.c.status)
    )
    status_counts = {row.status: row.count for row in status_q}

    # Node type counts
    type_q = await conn.execute(
        sa.select(
            knowledge_graph_nodes.c.node_type,
            sa.func.count().label("count"),
        ).group_by(knowledge_graph_nodes.c.node_type)
    )
    node_type_counts = {row.node_type: row.count for row in type_q}

    # Relationship type counts
    rel_q = await conn.execute(
        sa.select(
            knowledge_graph_edges.c.relationship_type,
            sa.func.count().label("count"),
        ).group_by(knowledge_graph_edges.c.relationship_type)
    )
    rel_type_counts = {row.relationship_type: row.count for row in rel_q}

    return KGStats(
        node_count=node_count,
        edge_count=edge_count,
        avg_confidence=float(avg_conf) if avg_conf else 0.0,
        validated_count=status_counts.get("validated", 0),
        proposed_count=status_counts.get("proposed", 0),
        contested_count=status_counts.get("contested", 0),
        node_type_counts=node_type_counts,
        relationship_type_counts=rel_type_counts,
    )


async def get_recent_nodes(conn, limit: int = 50) -> list[dict]:
    """Get the most recently created KG nodes."""
    result = await conn.execute(
        knowledge_graph_nodes.select()
        .order_by(knowledge_graph_nodes.c.first_seen.desc())
        .limit(limit)
    )
    return [dict(row._mapping) for row in result]


async def get_context_for_objective(
    conn,
    anchor_node_ids: list[UUID],
    max_depth: int = 2,
) -> str:
    """Build a text summary of KG context around anchor nodes, for injection into agent prompts."""
    if not anchor_node_ids:
        return ""

    context_parts = []
    seen_nodes = set()

    for anchor_id in anchor_node_ids:
        steps = await traverse_path(conn, anchor_id, max_depth=max_depth)
        for step in steps:
            if step.node_id not in seen_nodes:
                seen_nodes.add(step.node_id)
                edge_info = f" (via {step.edge_type})" if step.edge_type else ""
                context_parts.append(
                    f"- [{step.node_type}] {step.label} "
                    f"(confidence: {step.confidence:.2f}){edge_info}"
                )

    return "\n".join(context_parts) if context_parts else "No relevant knowledge graph context."
