"""Objective endpoints for the NEXUS Observatory API."""

from __future__ import annotations

from uuid import UUID

import sqlalchemy as sa
from fastapi import APIRouter, HTTPException, Query

from nexus_core.database import get_connection
from nexus_core.models.objectives import objectives
from nexus_core.models.decomposition import objective_decomposition
from nexus_core.models.attachments import objective_attachments
from nexus_core.utils.events import emit_event

from nexus_api.schemas import (
    ObjectiveResponse,
    ObjectiveCreateRequest,
    ObjectiveListResponse,
    ObjectiveDAGNode,
    ObjectiveDAGEdge,
    ObjectiveDAGResponse,
)

router = APIRouter(prefix="/api/objectives", tags=["objectives"])

STATUS_COLORS = {
    "proposed": "#6b7280",
    "approved": "#3b82f6",
    "in_progress": "#f59e0b",
    "completed": "#10b981",
    "failed": "#ef4444",
    "escalated": "#8b5cf6",
}


def _row_to_objective(row) -> ObjectiveResponse:
    """Convert a DB row to ObjectiveResponse, coercing Decimal fields."""
    d = dict(row._mapping)
    if d.get("compute_budget_allocated") is not None:
        d["compute_budget_allocated"] = float(d["compute_budget_allocated"])
    return ObjectiveResponse(**d)


VALID_TYPES = {"strategic", "tactical", "exploratory"}


@router.post("", response_model=ObjectiveResponse, status_code=201)
async def create_objective(body: ObjectiveCreateRequest):
    """Submit a new research objective, optionally with file attachments."""
    if body.objective_type not in VALID_TYPES:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid type '{body.objective_type}'. Must be one of: {', '.join(sorted(VALID_TYPES))}",
        )
    if not 1 <= body.priority <= 10:
        raise HTTPException(
            status_code=422,
            detail="Priority must be between 1 and 10",
        )

    attachment_id_strs = [str(aid) for aid in body.attachment_ids]

    async with get_connection() as conn:
        async with conn.begin():
            # Create objective
            result = await conn.execute(
                objectives.insert()
                .values(
                    title=body.title[:500],
                    description=body.description,
                    objective_type=body.objective_type,
                    priority=body.priority,
                    status="proposed",
                    proposed_by_type="human",
                    file_attachment_ids=attachment_id_strs,
                )
                .returning(objectives)
            )
            row = result.first()

            # Link attachments to this objective
            if body.attachment_ids:
                await conn.execute(
                    objective_attachments.update()
                    .where(
                        objective_attachments.c.attachment_id.in_(body.attachment_ids),
                        objective_attachments.c.objective_id.is_(None),
                    )
                    .values(objective_id=row.objective_id)
                )

            await emit_event(
                conn,
                "objective.created",
                entity_id=row.objective_id,
                entity_type="objective",
                payload={
                    "title": body.title[:500],
                    "type": body.objective_type,
                    "priority": body.priority,
                    "attachment_count": len(body.attachment_ids),
                },
            )

    return _row_to_objective(row)


@router.get("", response_model=ObjectiveListResponse)
async def list_objectives(
    status: str | None = Query(None, description="Filter by status"),
    objective_type: str | None = Query(None, description="Filter by type"),
    limit: int = Query(200, ge=1, le=1000),
):
    """List objectives with optional status/type filter."""
    async with get_connection() as conn:
        query = objectives.select().order_by(objectives.c.created_at.desc()).limit(limit)
        if status:
            query = query.where(objectives.c.status == status)
        if objective_type:
            query = query.where(objectives.c.objective_type == objective_type)

        result = await conn.execute(query)
        objs = [_row_to_objective(row) for row in result]

    return ObjectiveListResponse(objectives=objs, count=len(objs))


@router.get("/{objective_id}", response_model=ObjectiveResponse)
async def get_objective(objective_id: UUID):
    """Get a single objective by ID."""
    async with get_connection() as conn:
        result = await conn.execute(
            objectives.select().where(objectives.c.objective_id == objective_id)
        )
        row = result.first()
        if row is None:
            raise HTTPException(status_code=404, detail="Objective not found")

    return _row_to_objective(row)


@router.get("/{objective_id}/dag", response_model=ObjectiveDAGResponse)
async def get_objective_dag(objective_id: UUID):
    """Get the decomposition DAG for an objective (nodes + edges for ReactFlow).

    Returns the root objective plus all of its descendants through the
    ``objective_decomposition`` table.
    """
    async with get_connection() as conn:
        # Recursive CTE to gather the full subtree starting from the given objective.
        tree_q = sa.text("""
            WITH RECURSIVE subtree AS (
                SELECT objective_id, parent_objective_id, title, status,
                       objective_type, priority, 0 AS depth
                FROM objectives
                WHERE objective_id = :root_id

                UNION ALL

                SELECT o.objective_id, o.parent_objective_id, o.title, o.status,
                       o.objective_type, o.priority, s.depth + 1
                FROM objectives o
                JOIN subtree s ON o.parent_objective_id = s.objective_id
                WHERE s.depth < 10
            )
            SELECT * FROM subtree ORDER BY depth, priority
        """)
        rows = (await conn.execute(tree_q, {"root_id": objective_id})).fetchall()

        if not rows:
            raise HTTPException(status_code=404, detail="Objective not found")

        # Build ReactFlow-compatible nodes and edges.
        nodes: list[ObjectiveDAGNode] = []
        edges: list[ObjectiveDAGEdge] = []

        for i, row in enumerate(rows):
            oid = str(row.objective_id)
            color = STATUS_COLORS.get(row.status, "#6b7280")
            nodes.append(ObjectiveDAGNode(
                id=oid,
                data={
                    "label": row.title,
                    "status": row.status,
                    "type": row.objective_type,
                    "priority": row.priority,
                    "color": color,
                },
                position={"x": (i % 4) * 250, "y": row.depth * 150},
            ))

            if row.parent_objective_id is not None:
                edges.append(ObjectiveDAGEdge(
                    id=f"e-{row.parent_objective_id}-{oid}",
                    source=str(row.parent_objective_id),
                    target=oid,
                    animated=row.status == "in_progress",
                ))

        # Also add explicit decomposition edges (dependency_type labels).
        decomp_q = (
            objective_decomposition.select()
            .where(
                sa.or_(
                    objective_decomposition.c.parent_objective_id.in_(
                        [r.objective_id for r in rows]
                    ),
                    objective_decomposition.c.child_objective_id.in_(
                        [r.objective_id for r in rows]
                    ),
                )
            )
        )
        decomp_rows = (await conn.execute(decomp_q)).fetchall()
        existing_edge_ids = {e.id for e in edges}
        for dr in decomp_rows:
            eid = f"d-{dr.parent_objective_id}-{dr.child_objective_id}"
            if eid not in existing_edge_ids:
                edges.append(ObjectiveDAGEdge(
                    id=eid,
                    source=str(dr.parent_objective_id),
                    target=str(dr.child_objective_id),
                    label=dr.dependency_type,
                ))

    return ObjectiveDAGResponse(nodes=nodes, edges=edges)
