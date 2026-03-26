"""Knowledge graph workbench endpoints for the NEXUS Observatory API."""

from __future__ import annotations

from collections import deque
from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB
from fastapi import APIRouter, HTTPException, Query

from nexus_core.config import get_settings
from nexus_core.database import get_connection
from nexus_core.knowledge.graph_ops import get_all_edges, get_all_nodes, get_edges, get_node
from nexus_core.knowledge.query import get_kg_stats, get_subgraph, search_nodes
from nexus_core.models.events import events
from nexus_core.models.findings import findings
from nexus_core.models.knowledge_graph import knowledge_graph_edges, knowledge_graph_nodes
from nexus_core.models.objectives import objectives
from nexus_core.reporting.artifacts import list_question_artifacts

from nexus_api.routers.activity import _load_context_maps, _summarize_event
from nexus_api.schemas import (
    CitationResponse,
    KGChangeFeedResponse,
    KGChangeItemResponse,
    KGEdgeResponse,
    KGEvidenceFindingResponse,
    KGEvidenceRecordResponse,
    KGFindingSearchResultResponse,
    KGNodeDetailResponse,
    KGNodeResponse,
    KGObjectiveSearchResultResponse,
    KGPathResponse,
    KGPathStepResponse,
    KGStatsResponse,
    KGSubgraphResponse,
    KGWorkbenchObjectiveTouchResponse,
    KGWorkbenchOverviewResponse,
    LinkedObjectiveResponse,
    ReportArtifactSummaryResponse,
)

router = APIRouter(prefix="/api/kg", tags=["knowledge-graph"])


def _node_to_response(d: dict) -> KGNodeResponse:
    if d.get("confidence_score") is not None:
        d["confidence_score"] = float(d["confidence_score"])
    return KGNodeResponse(**d)


def _edge_to_response(d: dict) -> KGEdgeResponse:
    for key in ("weight", "confidence_score"):
        if d.get(key) is not None:
            d[key] = float(d[key])
    return KGEdgeResponse(**d)


def _citation_to_response(item: dict[str, Any], *, finding_id: UUID | None = None) -> CitationResponse:
    return CitationResponse(
        title=str(item.get("title", "")).strip() or "Untitled source",
        source_type=str(item.get("source_type", "")).strip(),
        source_name=str(item.get("source_name", "")).strip(),
        url=str(item.get("url", "")).strip(),
        doi=str(item.get("doi", "")).strip(),
        published_date=str(item.get("published_date", "")).strip(),
        authors=_coerce_authors(item.get("authors")),
        supporting_snippet=str(item.get("supporting_snippet", "")).strip(),
        source_finding_id=finding_id,
        derived=bool(item.get("derived", False)),
    )


@router.get("/nodes", response_model=list[KGNodeResponse])
async def list_kg_nodes(
    node_type: str | None = Query(None, description="Filter by node_type"),
    status: str | None = Query(None, description="Filter by status"),
    limit: int = Query(500, ge=1, le=5000),
):
    async with get_connection() as conn:
        nodes = await get_all_nodes(conn, status=status, node_type=node_type, limit=limit)
    return [_node_to_response(n) for n in nodes]


@router.get("/edges", response_model=list[KGEdgeResponse])
async def list_kg_edges(
    status: str | None = Query(None, description="Filter by status"),
    limit: int = Query(2000, ge=1, le=10000),
):
    async with get_connection() as conn:
        edges = await get_all_edges(conn, status=status, limit=limit)
    return [_edge_to_response(e) for e in edges]


@router.get("/stats", response_model=KGStatsResponse)
async def kg_stats():
    async with get_connection() as conn:
        stats = await get_kg_stats(conn)
    return KGStatsResponse(
        node_count=stats.node_count,
        edge_count=stats.edge_count,
        avg_confidence=stats.avg_confidence,
        validated_count=stats.validated_count,
        proposed_count=stats.proposed_count,
        contested_count=stats.contested_count,
        node_type_counts=stats.node_type_counts,
        relationship_type_counts=stats.relationship_type_counts,
    )


@router.get("/overview", response_model=KGWorkbenchOverviewResponse)
async def kg_workbench_overview(window_hours: int = Query(24, ge=1, le=168)):
    since = datetime.now(UTC) - timedelta(hours=window_hours)
    async with get_connection() as conn:
        stats = await get_kg_stats(conn)
        challenged_node_count = await conn.scalar(
            sa.select(sa.func.count())
            .select_from(knowledge_graph_nodes)
            .where(knowledge_graph_nodes.c.challenge_count > 0)
        )
        challenged_edge_count = await conn.scalar(
            sa.select(sa.func.count())
            .select_from(knowledge_graph_edges)
            .where(knowledge_graph_edges.c.status.in_(["contested", "refuted"]))
        )
        recent_change_count = await conn.scalar(
            sa.select(sa.func.count())
            .select_from(events)
            .where(
                events.c.created_at >= since,
                sa.or_(
                    events.c.event_type.like("kg_%"),
                    events.c.event_type.like("red_team_%"),
                    events.c.event_type.in_(["finding_report_written", "recommendation_report_written", "recommendation_report_repaired"]),
                ),
            )
        )
        report_linked_node_count = await _count_distinct_report_refs(conn, "kg_nodes_created")
        report_linked_edge_count = await _count_distinct_report_refs(conn, "kg_edges_created")
        top_objectives = await _load_top_objective_touches(conn)

    return KGWorkbenchOverviewResponse(
        node_count=stats.node_count,
        edge_count=stats.edge_count,
        avg_confidence=stats.avg_confidence,
        challenged_node_count=int(challenged_node_count or 0),
        challenged_edge_count=int(challenged_edge_count or 0),
        recent_change_count=int(recent_change_count or 0),
        report_linked_node_count=report_linked_node_count,
        report_linked_edge_count=report_linked_edge_count,
        top_objectives=top_objectives,
    )


@router.get("/subgraph", response_model=KGSubgraphResponse)
async def kg_subgraph(
    node_id: UUID | None = Query(None),
    objective_id: UUID | None = Query(None),
    finding_id: UUID | None = Query(None),
    depth: int = Query(2, ge=1, le=4),
    status: str | None = Query(None),
    node_types: list[str] | None = Query(None),
    relationship_types: list[str] | None = Query(None),
):
    async with get_connection() as conn:
        if node_id is not None:
            subgraph = await get_subgraph(conn, node_id, radius=depth)
            scope_label = "node"
            center_node_id = node_id
            nodes = subgraph.nodes
            edges = subgraph.edges
        elif objective_id is not None:
            tree_ids = await _load_objective_tree_ids(conn, objective_id)
            nodes, edges = await _load_graph_for_objective_tree(conn, tree_ids)
            scope_label = "objective"
            center_node_id = None
        elif finding_id is not None:
            nodes, edges = await _load_graph_for_finding(conn, finding_id)
            scope_label = "finding"
            center_node_id = None
        else:
            nodes = await get_all_nodes(conn, status=status, limit=500)
            edges = await get_all_edges(conn, status=status, limit=1500)
            scope_label = "global"
            center_node_id = None

    node_type_filter = set(node_types or [])
    relationship_filter = set(relationship_types or [])
    filtered_nodes = [
        node for node in nodes
        if (status is None or node.get("status") == status)
        and (not node_type_filter or node.get("node_type") in node_type_filter)
    ]
    node_ids = {node["node_id"] for node in filtered_nodes}
    filtered_edges = [
        edge for edge in edges
        if edge.get("source_node_id") in node_ids
        and edge.get("target_node_id") in node_ids
        and (status is None or edge.get("status") == status)
        and (not relationship_filter or edge.get("relationship_type") in relationship_filter)
    ]

    return KGSubgraphResponse(
        center_node_id=center_node_id,
        scope_label=scope_label,
        nodes=[_node_to_response(dict(node)) for node in filtered_nodes],
        edges=[_edge_to_response(dict(edge)) for edge in filtered_edges],
    )


@router.get("/search", response_model=list[KGNodeResponse])
async def kg_search(
    q: str = Query(..., min_length=1, description="Search text"),
    limit: int = Query(10, ge=1, le=100),
):
    async with get_connection() as conn:
        results = await search_nodes(conn, query_text=q, limit=limit)
    return [_node_to_response(n) for n in results]


@router.get("/objectives/search", response_model=list[KGObjectiveSearchResultResponse])
async def kg_objective_search(
    q: str = Query(..., min_length=1, description="Objective search text"),
    limit: int = Query(8, ge=1, le=50),
):
    query = q.strip()
    async with get_connection() as conn:
        result = await conn.execute(
            sa.select(
                objectives.c.objective_id,
                objectives.c.title,
                objectives.c.status,
                objectives.c.objective_type,
                objectives.c.impact_level,
            )
            .where(objectives.c.title.ilike(f"%{query}%"))
            .order_by(
                sa.case(
                    (sa.func.lower(objectives.c.title) == query.lower(), 0),
                    (sa.func.lower(objectives.c.title).like(f"{query.lower()}%"), 1),
                    else_=2,
                ),
                objectives.c.priority.desc(),
                objectives.c.created_at.desc(),
            )
            .limit(limit)
        )
    return [
        KGObjectiveSearchResultResponse(
            objective_id=row.objective_id,
            title=row.title,
            status=row.status,
            objective_type=row.objective_type,
            impact_level=row.impact_level,
        )
        for row in result
    ]


@router.get("/findings/search", response_model=list[KGFindingSearchResultResponse])
async def kg_finding_search(
    q: str = Query(..., min_length=1, description="Finding search text"),
    objective_id: UUID | None = Query(None),
    limit: int = Query(8, ge=1, le=50),
):
    query = q.strip()
    stmt = (
        sa.select(
            findings.c.finding_id,
            findings.c.title,
            findings.c.objective_id,
            objectives.c.title.label("objective_title"),
            findings.c.status,
            findings.c.impact_level,
        )
        .join(objectives, objectives.c.objective_id == findings.c.objective_id)
        .where(
            sa.or_(
                findings.c.title.ilike(f"%{query}%"),
                objectives.c.title.ilike(f"%{query}%"),
            )
        )
        .order_by(
            sa.case(
                (sa.func.lower(findings.c.title) == query.lower(), 0),
                (sa.func.lower(findings.c.title).like(f"{query.lower()}%"), 1),
                else_=2,
            ),
            findings.c.created_at.desc(),
        )
        .limit(limit)
    )
    if objective_id is not None:
        stmt = stmt.where(findings.c.objective_id == objective_id)

    async with get_connection() as conn:
        result = await conn.execute(stmt)
    return [
        KGFindingSearchResultResponse(
            finding_id=row.finding_id,
            title=row.title,
            objective_id=row.objective_id,
            objective_title=row.objective_title,
            status=row.status,
            impact_level=row.impact_level or "routine",
        )
        for row in result
    ]


@router.get("/nodes/{node_id}", response_model=KGNodeDetailResponse)
async def kg_node_detail(node_id: UUID):
    async with get_connection() as conn:
        node = await get_node(conn, node_id)
        if node is None:
            raise HTTPException(status_code=404, detail="Knowledge graph node not found")

        adjacent_edges = await get_edges(conn, node_id)
        linked_findings = await _load_linked_findings_for_node(conn, node_id)
        linked_objectives = await _load_linked_objectives(conn, linked_findings)
        linked_reports = await _load_reports_for_findings(conn, linked_findings)
        linked_citations = _dedupe_citation_responses(
            citation
            for finding in linked_findings
            for citation in finding.citations
        )
        node_lookup = await _load_node_lookup(conn)
        relationship_groups = _group_relationships(node_id=node_id, edges=adjacent_edges, node_lookup=node_lookup)
        timeline = await _load_change_items(conn, window_hours=168, entity_id=node_id)

    return KGNodeDetailResponse(
        node=_node_to_response(node),
        adjacent_edges=[_edge_to_response(edge) for edge in adjacent_edges],
        linked_findings=linked_findings,
        linked_objectives=linked_objectives,
        linked_reports=linked_reports,
        linked_citations=linked_citations,
        relationship_groups=relationship_groups,
        timeline=timeline,
    )


@router.get("/path", response_model=KGPathResponse)
async def kg_path(
    start_node_id: UUID = Query(...),
    end_node_id: UUID = Query(...),
    max_depth: int = Query(4, ge=1, le=6),
):
    async with get_connection() as conn:
        path_edge_rows = await _find_path_edges(conn, start_node_id, end_node_id, max_depth=max_depth)
        node_lookup = await _load_node_lookup(conn)
        if not path_edge_rows:
            return KGPathResponse(
                start_node_id=start_node_id,
                end_node_id=end_node_id,
                found=False,
                steps=[],
                evidence=[],
            )

        steps = [
            KGPathStepResponse(
                node_id=start_node_id,
                label=node_lookup.get(start_node_id, {}).get("label", "Unknown node"),
                node_type=node_lookup.get(start_node_id, {}).get("node_type", "concept"),
                confidence=float(node_lookup.get(start_node_id, {}).get("confidence_score", 0.0) or 0.0),
                depth=0,
            )
        ]
        supporting_finding_ids: set[UUID] = set()
        current_node_id = start_node_id
        for depth_index, edge in enumerate(path_edge_rows, start=1):
            next_node_id = edge["target_node_id"] if edge["source_node_id"] == current_node_id else edge["source_node_id"]
            supporting_ids = _coerce_uuid_list(edge.get("evidence_ids"))
            supporting_finding_ids.update(supporting_ids)
            node_data = node_lookup.get(next_node_id, {})
            steps.append(
                KGPathStepResponse(
                    node_id=next_node_id,
                    label=node_data.get("label", "Unknown node"),
                    node_type=node_data.get("node_type", "concept"),
                    confidence=float(node_data.get("confidence_score", 0.0) or 0.0),
                    depth=depth_index,
                    edge_type=edge.get("relationship_type"),
                    edge_weight=float(edge.get("weight", 0.0) or 0.0),
                    supporting_finding_ids=supporting_ids,
                )
            )
            current_node_id = next_node_id

        evidence = await _load_findings_by_ids(conn, supporting_finding_ids)

    return KGPathResponse(
        start_node_id=start_node_id,
        end_node_id=end_node_id,
        found=True,
        steps=steps,
        evidence=evidence,
    )


@router.get("/evidence", response_model=KGEvidenceRecordResponse)
async def kg_evidence(
    node_id: UUID | None = Query(None),
    edge_id: UUID | None = Query(None),
    objective_id: UUID | None = Query(None),
    finding_id: UUID | None = Query(None),
):
    filters_used = [value is not None for value in (node_id, edge_id, objective_id, finding_id)]
    if sum(filters_used) != 1:
        raise HTTPException(status_code=400, detail="Provide exactly one of node_id, edge_id, objective_id, or finding_id")

    async with get_connection() as conn:
        if node_id is not None:
            linked_findings = await _load_linked_findings_for_node(conn, node_id)
            query_type = "node"
        elif edge_id is not None:
            linked_findings = await _load_linked_findings_for_edge(conn, edge_id)
            query_type = "edge"
        elif objective_id is not None:
            linked_findings = await _load_linked_findings_for_objective(conn, objective_id)
            query_type = "objective"
        else:
            linked_findings = await _load_findings_by_ids(conn, {finding_id})
            query_type = "finding"

        linked_objectives = await _load_linked_objectives(conn, linked_findings)
        reports = await _load_reports_for_findings(conn, linked_findings)
        citations = _dedupe_citation_responses(
            citation
            for finding in linked_findings
            for citation in finding.citations
        )
        challenged_count = sum(1 for finding in linked_findings if finding.status == "challenged")

    return KGEvidenceRecordResponse(
        query_type=query_type,
        findings=linked_findings,
        reports=reports,
        citations=citations,
        linked_objectives=linked_objectives,
        challenged_count=challenged_count,
    )


@router.get("/changes", response_model=KGChangeFeedResponse)
async def kg_changes(
    window_hours: int = Query(24, ge=1, le=336),
):
    async with get_connection() as conn:
        items = await _load_change_items(conn, window_hours=window_hours)
    return KGChangeFeedResponse(items=items, count=len(items), window_hours=window_hours)


async def _count_distinct_report_refs(conn, column_name: str) -> int:
    result = await conn.execute(
        sa.text(
            f"""
            SELECT COUNT(DISTINCT value::text)
            FROM findings,
            LATERAL jsonb_array_elements_text(CAST({column_name} AS jsonb)) AS value
            WHERE status IN ('validated', 'challenged')
            """
        )
    )
    return int(result.scalar_one() or 0)


async def _load_top_objective_touches(conn) -> list[KGWorkbenchObjectiveTouchResponse]:
    result = await conn.execute(
        sa.text(
            """
            WITH node_counts AS (
                SELECT discovered_by_objective_id AS objective_id, COUNT(*) AS node_count
                FROM knowledge_graph_nodes
                WHERE discovered_by_objective_id IS NOT NULL
                GROUP BY discovered_by_objective_id
            ),
            edge_counts AS (
                SELECT discovered_by_objective_id AS objective_id, COUNT(*) AS edge_count
                FROM knowledge_graph_edges
                WHERE discovered_by_objective_id IS NOT NULL
                GROUP BY discovered_by_objective_id
            )
            SELECT
                o.objective_id,
                o.title,
                o.status,
                COALESCE(n.node_count, 0) AS node_count,
                COALESCE(e.edge_count, 0) AS edge_count
            FROM objectives o
            LEFT JOIN node_counts n ON n.objective_id = o.objective_id
            LEFT JOIN edge_counts e ON e.objective_id = o.objective_id
            WHERE COALESCE(n.node_count, 0) + COALESCE(e.edge_count, 0) > 0
            ORDER BY (COALESCE(n.node_count, 0) + COALESCE(e.edge_count, 0)) DESC, o.created_at DESC
            LIMIT 6
            """
        )
    )
    return [
        KGWorkbenchObjectiveTouchResponse(
            objective_id=row.objective_id,
            title=row.title,
            status=row.status,
            node_count=int(row.node_count or 0),
            edge_count=int(row.edge_count or 0),
        )
        for row in result
    ]


async def _load_objective_tree_ids(conn, root_objective_id: UUID) -> list[UUID]:
    result = await conn.execute(
        sa.text(
            """
            WITH RECURSIVE objective_tree AS (
                SELECT objective_id
                FROM objectives
                WHERE objective_id = :root_id
                UNION ALL
                SELECT o.objective_id
                FROM objectives o
                JOIN objective_tree t ON o.parent_objective_id = t.objective_id
            )
            SELECT objective_id FROM objective_tree
            """
        ),
        {"root_id": root_objective_id},
    )
    return [row.objective_id for row in result]


async def _load_graph_for_objective_tree(conn, objective_ids: list[UUID]) -> tuple[list[dict], list[dict]]:
    finding_result = await conn.execute(
        sa.select(findings.c.kg_nodes_created, findings.c.kg_edges_created).where(
            findings.c.objective_id.in_(objective_ids)
        )
    )
    node_ids: set[UUID] = set()
    edge_ids: set[UUID] = set()
    for row in finding_result:
        node_ids.update(_coerce_uuid_list(row.kg_nodes_created))
        edge_ids.update(_coerce_uuid_list(row.kg_edges_created))

    nodes = []
    edges = []
    if node_ids:
        node_result = await conn.execute(
            knowledge_graph_nodes.select().where(knowledge_graph_nodes.c.node_id.in_(node_ids))
        )
        nodes = [dict(row._mapping) for row in node_result]
    if edge_ids:
        edge_result = await conn.execute(
            knowledge_graph_edges.select().where(knowledge_graph_edges.c.edge_id.in_(edge_ids))
        )
        edges = [dict(row._mapping) for row in edge_result]
    return nodes, edges


async def _load_graph_for_finding(conn, finding_id: UUID) -> tuple[list[dict], list[dict]]:
    row = (
        await conn.execute(
            sa.select(findings.c.kg_nodes_created, findings.c.kg_edges_created).where(
                findings.c.finding_id == finding_id
            )
        )
    ).first()
    if row is None:
        return [], []
    node_ids = _coerce_uuid_list(row.kg_nodes_created)
    edge_ids = _coerce_uuid_list(row.kg_edges_created)
    nodes = []
    edges = []
    if node_ids:
        node_result = await conn.execute(
            knowledge_graph_nodes.select().where(knowledge_graph_nodes.c.node_id.in_(node_ids))
        )
        nodes = [dict(item._mapping) for item in node_result]
    if edge_ids:
        edge_result = await conn.execute(
            knowledge_graph_edges.select().where(knowledge_graph_edges.c.edge_id.in_(edge_ids))
        )
        edges = [dict(item._mapping) for item in edge_result]
    return nodes, edges


async def _load_linked_findings_for_node(conn, node_id: UUID) -> list[KGEvidenceFindingResponse]:
    result = await conn.execute(
        sa.select(
            findings.c.finding_id,
            findings.c.objective_id,
            objectives.c.title.label("objective_title"),
            findings.c.title,
            findings.c.finding_type,
            findings.c.status,
            findings.c.impact_level,
            findings.c.review_round,
            findings.c.created_at,
            findings.c.structured_data,
            findings.c.kg_nodes_created,
            findings.c.kg_edges_created,
        )
        .join(objectives, objectives.c.objective_id == findings.c.objective_id)
        .where(sa.cast(findings.c.kg_nodes_created, JSONB).contains([str(node_id)]))
        .order_by(findings.c.created_at.desc())
        .limit(12)
    )
    return [_finding_row_to_response(row) for row in result]


async def _load_linked_findings_for_edge(conn, edge_id: UUID) -> list[KGEvidenceFindingResponse]:
    result = await conn.execute(
        sa.select(
            findings.c.finding_id,
            findings.c.objective_id,
            objectives.c.title.label("objective_title"),
            findings.c.title,
            findings.c.finding_type,
            findings.c.status,
            findings.c.impact_level,
            findings.c.review_round,
            findings.c.created_at,
            findings.c.structured_data,
            findings.c.kg_nodes_created,
            findings.c.kg_edges_created,
        )
        .join(objectives, objectives.c.objective_id == findings.c.objective_id)
        .where(sa.cast(findings.c.kg_edges_created, JSONB).contains([str(edge_id)]))
        .order_by(findings.c.created_at.desc())
        .limit(12)
    )
    return [_finding_row_to_response(row) for row in result]


async def _load_linked_findings_for_objective(conn, objective_id: UUID) -> list[KGEvidenceFindingResponse]:
    tree_ids = await _load_objective_tree_ids(conn, objective_id)
    result = await conn.execute(
        sa.select(
            findings.c.finding_id,
            findings.c.objective_id,
            objectives.c.title.label("objective_title"),
            findings.c.title,
            findings.c.finding_type,
            findings.c.status,
            findings.c.impact_level,
            findings.c.review_round,
            findings.c.created_at,
            findings.c.structured_data,
            findings.c.kg_nodes_created,
            findings.c.kg_edges_created,
        )
        .join(objectives, objectives.c.objective_id == findings.c.objective_id)
        .where(findings.c.objective_id.in_(tree_ids))
        .order_by(findings.c.created_at.desc())
        .limit(24)
    )
    return [_finding_row_to_response(row) for row in result]


async def _load_findings_by_ids(conn, finding_ids: set[UUID]) -> list[KGEvidenceFindingResponse]:
    if not finding_ids:
        return []
    result = await conn.execute(
        sa.select(
            findings.c.finding_id,
            findings.c.objective_id,
            objectives.c.title.label("objective_title"),
            findings.c.title,
            findings.c.finding_type,
            findings.c.status,
            findings.c.impact_level,
            findings.c.review_round,
            findings.c.created_at,
            findings.c.structured_data,
            findings.c.kg_nodes_created,
            findings.c.kg_edges_created,
        )
        .join(objectives, objectives.c.objective_id == findings.c.objective_id)
        .where(findings.c.finding_id.in_(finding_ids))
        .order_by(findings.c.created_at.desc())
    )
    return [_finding_row_to_response(row) for row in result]


async def _load_linked_objectives(
    conn,
    linked_findings: list[KGEvidenceFindingResponse],
) -> list[LinkedObjectiveResponse]:
    objective_ids = {finding.objective_id for finding in linked_findings}
    if not objective_ids:
        return []
    result = await conn.execute(
        sa.select(
            objectives.c.objective_id,
            objectives.c.title,
            objectives.c.status,
            objectives.c.objective_type,
            objectives.c.impact_level,
        ).where(objectives.c.objective_id.in_(objective_ids))
    )
    return [
        LinkedObjectiveResponse(
            objective_id=row.objective_id,
            title=row.title,
            status=row.status,
            objective_type=row.objective_type,
            impact_level=row.impact_level,
        )
        for row in result
    ]


async def _load_reports_for_findings(
    conn,
    linked_findings: list[KGEvidenceFindingResponse],
) -> list[ReportArtifactSummaryResponse]:
    root_cache: dict[UUID, tuple[UUID, str]] = {}
    artifact_map: dict[str, ReportArtifactSummaryResponse] = {}
    for finding in linked_findings:
        if finding.objective_id not in root_cache:
            root_cache[finding.objective_id] = await _load_root_objective(conn, finding.objective_id)
        root_objective_id, root_title = root_cache[finding.objective_id]
        for artifact in list_question_artifacts(
            settings=get_settings(),
            objective_id=root_objective_id,
            objective_title=root_title,
        ):
            artifact_response = ReportArtifactSummaryResponse(**asdict(artifact))
            artifact_map[artifact_response.slug] = artifact_response
    return sorted(artifact_map.values(), key=lambda item: item.updated_at, reverse=True)[:16]


async def _load_root_objective(conn, objective_id: UUID) -> tuple[UUID, str]:
    current_id = objective_id
    while True:
        row = (
            await conn.execute(
                sa.select(
                    objectives.c.objective_id,
                    objectives.c.parent_objective_id,
                    objectives.c.title,
                ).where(objectives.c.objective_id == current_id)
            )
        ).first()
        if row is None:
            return objective_id, "Unknown objective"
        if row.parent_objective_id is None:
            return row.objective_id, row.title
        current_id = row.parent_objective_id


async def _load_change_items(
    conn,
    *,
    window_hours: int,
    entity_id: UUID | None = None,
) -> list[KGChangeItemResponse]:
    since = datetime.now(UTC) - timedelta(hours=window_hours)
    query = (
        events.select()
        .where(
            events.c.created_at >= since,
            sa.or_(
                events.c.event_type.like("kg_%"),
                events.c.event_type.like("red_team_%"),
                events.c.event_type.in_(["finding_report_written", "recommendation_report_written", "recommendation_report_repaired"]),
            ),
        )
        .order_by(events.c.created_at.desc())
        .limit(60)
    )
    if entity_id is not None:
        query = query.where(events.c.entity_id == entity_id)
    rows = (await conn.execute(query)).fetchall()
    context = await _load_context_maps(conn, rows)
    items: list[KGChangeItemResponse] = []
    for row in rows:
        title, summary = _summarize_event(row, context)
        items.append(
            KGChangeItemResponse(
                event_id=row.event_id,
                event_type=row.event_type,
                entity_id=row.entity_id,
                entity_type=row.entity_type,
                title=title,
                summary=summary,
                payload=dict(row.payload or {}),
                created_at=row.created_at,
            )
        )
    return items


async def _find_path_edges(conn, start_node_id: UUID, end_node_id: UUID, *, max_depth: int) -> list[dict]:
    edges = await get_all_edges(conn, limit=5000)
    adjacency: dict[UUID, list[dict]] = {}
    for edge in edges:
        adjacency.setdefault(edge["source_node_id"], []).append(edge)
        adjacency.setdefault(edge["target_node_id"], []).append(edge)

    queue = deque([(start_node_id, [], {start_node_id})])
    while queue:
        current_node, path, visited = queue.popleft()
        if len(path) >= max_depth:
            continue
        for edge in adjacency.get(current_node, []):
            next_node = edge["target_node_id"] if edge["source_node_id"] == current_node else edge["source_node_id"]
            if next_node == end_node_id:
                return [*path, edge]
            if next_node in visited:
                continue
            queue.append((next_node, [*path, edge], {*visited, next_node}))
    return []


async def _load_node_lookup(conn) -> dict[UUID, dict[str, Any]]:
    result = await conn.execute(
        sa.select(
            knowledge_graph_nodes.c.node_id,
            knowledge_graph_nodes.c.label,
            knowledge_graph_nodes.c.node_type,
            knowledge_graph_nodes.c.confidence_score,
        )
    )
    return {row.node_id: dict(row._mapping) for row in result}


def _finding_row_to_response(row) -> KGEvidenceFindingResponse:
    payload = row.structured_data if isinstance(row.structured_data, dict) else {}
    citations = [
        _citation_to_response(item, finding_id=row.finding_id)
        for item in (payload.get("citations", []) or [])
        if isinstance(item, dict)
    ]
    return KGEvidenceFindingResponse(
        finding_id=row.finding_id,
        objective_id=row.objective_id,
        objective_title=row.objective_title,
        title=row.title,
        finding_type=row.finding_type,
        status=row.status,
        impact_level=row.impact_level or "routine",
        review_round=int(row.review_round or 0),
        created_at=row.created_at,
        kg_node_refs=[str(item) for item in (row.kg_nodes_created or [])],
        kg_edge_refs=[str(item) for item in (row.kg_edges_created or [])],
        citations=_dedupe_citation_responses(citations),
    )


def _dedupe_citation_responses(citations) -> list[CitationResponse]:
    seen: dict[str, CitationResponse] = {}
    for citation in citations:
        key = citation.doi.lower() or citation.url.lower() or f"{citation.title.lower()}::{citation.source_name.lower()}"
        existing = seen.get(key)
        if existing is None or (existing.derived and not citation.derived):
            seen[key] = citation
    return list(seen.values())


def _coerce_uuid_list(values) -> list[UUID]:
    uuids: list[UUID] = []
    for value in values or []:
        try:
            uuids.append(UUID(str(value)))
        except (TypeError, ValueError):
            continue
    return uuids


def _coerce_authors(value) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str):
        return [part.strip() for part in value.split(",") if part.strip()]
    return [str(value).strip()] if str(value).strip() else []


def _group_relationships(
    *,
    node_id: UUID,
    edges: list[dict],
    node_lookup: dict[UUID, dict[str, Any]],
) -> dict[str, list[str]]:
    grouped: dict[str, list[str]] = {}
    for edge in edges:
        relation = edge.get("relationship_type", "related_to")
        other_id = edge["target_node_id"] if edge["source_node_id"] == node_id else edge["source_node_id"]
        grouped.setdefault(relation, []).append(
            node_lookup.get(other_id, {}).get("label", str(other_id))
        )
    return grouped
