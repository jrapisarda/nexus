"""KG node and edge CRUD with deduplication."""

import json
import re
from uuid import UUID
from decimal import Decimal
from typing import Optional

import sqlalchemy as sa
from nexus_core.models.knowledge_graph import knowledge_graph_nodes, knowledge_graph_edges
from nexus_core.utils.embeddings import EmbeddingService
from nexus_core.utils.events import emit_event
import structlog

logger = structlog.get_logger(__name__)

_CANONICAL_LABEL_AVAILABLE: bool | None = None
_CANONICAL_LABEL_WARNING_EMITTED = False


def normalize_canonical_label(label: str) -> str:
    """Normalize a node label into a deterministic canonical lookup key."""
    normalized = re.sub(r"[\s\-_]+", " ", (label or "").strip().lower())
    normalized = re.sub(r"[^\w\s/]", "", normalized)
    return re.sub(r"\s+", " ", normalized).strip()


async def create_node(
    conn,
    label: str,
    node_type: str,
    properties: dict,
    confidence: float,
    objective_id: UUID,
    instance_id: UUID,
    embedding_service=None,
    dedup_threshold: float = 0.92,
) -> tuple[UUID, bool]:
    """Create a KG node with deduplication check.

    Returns: (node_id, is_new) -- is_new=False if merged with existing.
    """
    has_canonical_label = await _has_canonical_label_column(conn)
    canonical_label = normalize_canonical_label(label)
    embedding_text = _build_node_embedding_text(label, node_type, properties)
    embedding = _encode_embedding(embedding_text, embedding_service)

    exact_match_columns = [
        knowledge_graph_nodes.c.node_id,
        knowledge_graph_nodes.c.label,
        knowledge_graph_nodes.c.node_type,
        knowledge_graph_nodes.c.properties,
        knowledge_graph_nodes.c.confidence_score,
    ]
    if has_canonical_label:
        exact_match_columns.insert(2, knowledge_graph_nodes.c.canonical_label)

    exact_match_filters = [
        knowledge_graph_nodes.c.node_type == node_type,
        knowledge_graph_nodes.c.status != "retracted",
    ]
    if has_canonical_label:
        exact_match_filters.append(
            knowledge_graph_nodes.c.canonical_label == canonical_label
        )
    else:
        exact_match_filters.append(
            sa.func.lower(knowledge_graph_nodes.c.label)
            == str(label or "").strip().lower()
        )

    exact_match = await conn.execute(
        sa.select(*exact_match_columns)
        .where(*exact_match_filters)
        .limit(1)
    )
    existing = exact_match.first()
    if existing is not None:
        existing = dict(existing._mapping)
    if existing is None:
        existing = await find_similar_node(
            conn,
            embedding,
            node_type=node_type,
            threshold=dedup_threshold,
        )
    if existing is not None:
        await merge_nodes(
            conn,
            existing["node_id"],
            {
                "label": label,
                "properties": properties,
                "confidence_score": confidence,
                "validation_count_increment": 1,
                **(
                    {"canonical_label": canonical_label}
                    if has_canonical_label
                    else {}
                ),
            },
        )
        logger.info("kg_node_merged", existing_id=str(existing["node_id"]), label=label)
        return existing["node_id"], False

    # Create new node
    insert_values = {
        "node_type": node_type,
        "label": label,
        "properties": properties,
        "properties_embedding": embedding.tolist(),
        "confidence_score": confidence,
        "discovered_by_objective_id": objective_id,
        "discovered_by_instance_id": instance_id,
        "status": "proposed",
    }
    if has_canonical_label:
        insert_values["canonical_label"] = canonical_label

    result = await conn.execute(
        knowledge_graph_nodes.insert().values(**insert_values).returning(
            knowledge_graph_nodes.c.node_id
        )
    )
    node_id = result.scalar_one()

    await emit_event(conn, "kg_node_created", entity_id=node_id, entity_type="kg_node",
                     payload={"label": label, "type": node_type})

    logger.info("kg_node_created", node_id=str(node_id), label=label, type=node_type)
    return node_id, True


async def find_similar_node(
    conn,
    embedding,
    *,
    node_type: str | None = None,
    threshold: float = 0.92,
) -> Optional[dict]:
    """Find the most similar existing node by embedding cosine similarity.

    Uses pgvector if available, otherwise returns None.
    """
    try:
        has_canonical_label = await _has_canonical_label_column(conn)
        vector = embedding.tolist() if hasattr(embedding, "tolist") else list(embedding)
        distance = knowledge_graph_nodes.c.properties_embedding.cosine_distance(vector)
        select_columns = [
            knowledge_graph_nodes.c.node_id,
            knowledge_graph_nodes.c.label,
            knowledge_graph_nodes.c.node_type,
            knowledge_graph_nodes.c.properties,
            knowledge_graph_nodes.c.confidence_score,
            (1 - distance).label("similarity"),
        ]
        if has_canonical_label:
            select_columns.insert(2, knowledge_graph_nodes.c.canonical_label)
        result = await conn.execute(
            sa.select(*select_columns)
            .where(
                knowledge_graph_nodes.c.status != "retracted",
                knowledge_graph_nodes.c.properties_embedding.isnot(None),
                *(
                    [knowledge_graph_nodes.c.node_type == node_type]
                    if node_type is not None
                    else []
                ),
            )
            .order_by(distance)
            .limit(1)
        )
        row = result.first()
        if row and row.similarity >= threshold:
            return dict(row._mapping)
    except Exception as e:
        logger.warning("kg_vector_dedup_failed", error=str(e))

    return None


async def create_edge(
    conn,
    source_node_id: UUID,
    target_node_id: UUID,
    relationship_type: str,
    weight: float = 0.5,
    confidence: float = 0.5,
    evidence_ids: list = None,
    objective_id: UUID = None,
) -> UUID:
    """Create a KG edge between two nodes."""
    existing_result = await conn.execute(
        sa.select(
            knowledge_graph_edges.c.edge_id,
            knowledge_graph_edges.c.weight,
            knowledge_graph_edges.c.confidence_score,
            knowledge_graph_edges.c.evidence_ids,
        ).where(
            knowledge_graph_edges.c.source_node_id == source_node_id,
            knowledge_graph_edges.c.target_node_id == target_node_id,
            knowledge_graph_edges.c.relationship_type == relationship_type,
            knowledge_graph_edges.c.status.notin_(["retracted", "refuted"]),
        ).limit(1)
    )
    existing = existing_result.first()
    if existing is not None:
        merged_evidence_ids = _merge_string_list(existing.evidence_ids, evidence_ids or [])
        await conn.execute(
            knowledge_graph_edges.update()
            .where(knowledge_graph_edges.c.edge_id == existing.edge_id)
            .values(
                weight=Decimal(str(max(float(existing.weight or 0), float(weight)))),
                confidence_score=Decimal(
                    str(max(float(existing.confidence_score or 0), float(confidence)))
                ),
                evidence_ids=merged_evidence_ids,
            )
        )
        await emit_event(
            conn,
            "kg_edge_merged",
            entity_id=existing.edge_id,
            entity_type="kg_edge",
            payload={
                "source": str(source_node_id),
                "target": str(target_node_id),
                "type": relationship_type,
            },
        )
        return existing.edge_id

    result = await conn.execute(
        knowledge_graph_edges.insert().values(
            source_node_id=source_node_id,
            target_node_id=target_node_id,
            relationship_type=relationship_type,
            weight=Decimal(str(weight)),
            confidence_score=Decimal(str(confidence)),
            evidence_ids=evidence_ids or [],
            discovered_by_objective_id=objective_id,
            status="proposed",
        ).returning(knowledge_graph_edges.c.edge_id)
    )
    edge_id = result.scalar_one()

    await emit_event(conn, "kg_edge_created", entity_id=edge_id, entity_type="kg_edge",
                     payload={"source": str(source_node_id), "target": str(target_node_id),
                              "type": relationship_type})

    return edge_id


async def merge_nodes(conn, existing_node_id: UUID, new_data: dict):
    """Merge new data into an existing node (dedup merge)."""
    has_canonical_label = await _has_canonical_label_column(conn)
    select_columns = [
        knowledge_graph_nodes.c.label,
        knowledge_graph_nodes.c.properties,
        knowledge_graph_nodes.c.confidence_score,
    ]
    if has_canonical_label:
        select_columns.insert(1, knowledge_graph_nodes.c.canonical_label)
    current_result = await conn.execute(
        sa.select(*select_columns).where(
            knowledge_graph_nodes.c.node_id == existing_node_id
        )
    )
    current = current_result.first()
    if current is None:
        return

    current_properties = dict(current.properties or {})
    merged_properties = dict(current_properties)
    props_data = new_data.get("properties")
    if isinstance(props_data, dict):
        merged_properties.update(props_data)

    aliases = {
        str(item).strip()
        for item in current_properties.get("aliases", [])
        if str(item).strip()
    }
    current_label = str(current.label or "").strip()
    if current_label:
        aliases.add(current_label)
    incoming_label = str(new_data.get("label", "")).strip()
    if incoming_label:
        aliases.add(incoming_label)
    if aliases:
        merged_properties["aliases"] = sorted(aliases)

    updates = {
        "properties": merged_properties,
    }
    if "confidence_score" in new_data:
        updates["confidence_score"] = Decimal(
            str(max(float(current.confidence_score or 0), float(new_data["confidence_score"])))
        )
    if "validation_count_increment" in new_data:
        updates["validation_count"] = (
            knowledge_graph_nodes.c.validation_count + new_data["validation_count_increment"]
        )
    if has_canonical_label and new_data.get("canonical_label"):
        updates["canonical_label"] = str(new_data["canonical_label"]).strip() or getattr(
            current,
            "canonical_label",
            "",
        )

    await conn.execute(
        knowledge_graph_nodes.update()
        .where(knowledge_graph_nodes.c.node_id == existing_node_id)
        .values(**updates)
    )


async def update_node_status(conn, node_id: UUID, status: str):
    """Update a node's status (proposed -> validated, contested, refuted, retracted)."""
    values = {"status": status}
    if status == "validated":
        values["last_validated"] = sa.func.now()

    await conn.execute(
        knowledge_graph_nodes.update()
        .where(knowledge_graph_nodes.c.node_id == node_id)
        .values(**values)
    )
    await emit_event(conn, "kg_node_status_changed", entity_id=node_id, entity_type="kg_node",
                     payload={"new_status": status})


async def update_edge_status(conn, edge_id: UUID, status: str):
    """Update an edge's status."""
    await conn.execute(
        knowledge_graph_edges.update()
        .where(knowledge_graph_edges.c.edge_id == edge_id)
        .values(status=status)
    )


async def get_node(conn, node_id: UUID) -> Optional[dict]:
    """Get a single node by ID."""
    result = await conn.execute(
        knowledge_graph_nodes.select()
        .where(knowledge_graph_nodes.c.node_id == node_id)
    )
    row = result.first()
    return dict(row._mapping) if row else None


async def get_edges(conn, node_id: UUID, direction: str = "both") -> list[dict]:
    """Get edges connected to a node. direction: 'outgoing', 'incoming', or 'both'."""
    if direction == "outgoing":
        query = knowledge_graph_edges.select().where(
            knowledge_graph_edges.c.source_node_id == node_id
        )
    elif direction == "incoming":
        query = knowledge_graph_edges.select().where(
            knowledge_graph_edges.c.target_node_id == node_id
        )
    else:  # both
        query = knowledge_graph_edges.select().where(
            sa.or_(
                knowledge_graph_edges.c.source_node_id == node_id,
                knowledge_graph_edges.c.target_node_id == node_id,
            )
        )

    result = await conn.execute(query)
    return [dict(row._mapping) for row in result]


async def get_all_nodes(conn, status: str = None, node_type: str = None, limit: int = 1000) -> list[dict]:
    """Get nodes with optional filters."""
    query = knowledge_graph_nodes.select().limit(limit)
    if status:
        query = query.where(knowledge_graph_nodes.c.status == status)
    if node_type:
        query = query.where(knowledge_graph_nodes.c.node_type == node_type)
    result = await conn.execute(query)
    return [dict(row._mapping) for row in result]


async def get_all_edges(conn, status: str = None, limit: int = 5000) -> list[dict]:
    """Get edges with optional filter."""
    query = knowledge_graph_edges.select().limit(limit)
    if status:
        query = query.where(knowledge_graph_edges.c.status == status)
    result = await conn.execute(query)
    return [dict(row._mapping) for row in result]


def _merge_string_list(existing_values, incoming_values) -> list[str]:
    merged: list[str] = []
    seen: set[str] = set()
    for value in list(existing_values or []) + list(incoming_values or []):
        text = str(value).strip()
        if not text or text in seen:
            continue
        seen.add(text)
        merged.append(text)
    return merged


async def _has_canonical_label_column(conn) -> bool:
    """Detect whether the live database has the canonical_label migration applied."""
    global _CANONICAL_LABEL_AVAILABLE, _CANONICAL_LABEL_WARNING_EMITTED

    if _CANONICAL_LABEL_AVAILABLE is None:
        try:
            _CANONICAL_LABEL_AVAILABLE = bool(
                await conn.run_sync(
                    lambda sync_conn: any(
                        column["name"] == "canonical_label"
                        for column in sa.inspect(sync_conn).get_columns("knowledge_graph_nodes")
                    )
                )
            )
        except Exception as exc:
            logger.warning(
                "kg_schema_inspection_failed",
                error=str(exc),
            )
            _CANONICAL_LABEL_AVAILABLE = True

    if not _CANONICAL_LABEL_AVAILABLE and not _CANONICAL_LABEL_WARNING_EMITTED:
        logger.warning(
            "kg_schema_outdated",
            detail=(
                "knowledge_graph_nodes.canonical_label is missing; "
                "falling back to legacy label dedup. Run migrations."
            ),
        )
        _CANONICAL_LABEL_WARNING_EMITTED = True

    return _CANONICAL_LABEL_AVAILABLE


async def increment_challenge_count(conn, node_id: UUID, success: bool = False):
    """Increment challenge count on a node. If success=True, also increment challenge_failures."""
    updates = {"challenge_count": knowledge_graph_nodes.c.challenge_count + 1}
    if success:
        updates["challenge_failures"] = knowledge_graph_nodes.c.challenge_failures + 1

    await conn.execute(
        knowledge_graph_nodes.update()
        .where(knowledge_graph_nodes.c.node_id == node_id)
        .values(**updates)
    )


def _build_node_embedding_text(label: str, node_type: str, properties: dict) -> str:
    properties_text = json.dumps(properties or {}, sort_keys=True)
    return f"{node_type} {label} {properties_text}".strip()


def _encode_embedding(text: str, embedding_service=None):
    if embedding_service is not None:
        try:
            return embedding_service.encode(text)
        except Exception as exc:
            logger.warning("embedding_service_fallback_to_hash", error=str(exc))
    return EmbeddingService.hash_encode(text)
