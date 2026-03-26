"""Knowledge graph duplicate auditing and repair helpers."""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from nexus_core.knowledge.graph_ops import normalize_canonical_label
from nexus_core.models.findings import findings
from nexus_core.models.knowledge_graph import knowledge_graph_edges, knowledge_graph_nodes
from nexus_core.utils.events import emit_event


@dataclass(slots=True)
class KGDuplicateCluster:
    node_type: str
    canonical_label: str
    primary_node_id: UUID
    primary_label: str
    duplicate_node_ids: list[UUID] = field(default_factory=list)
    duplicate_labels: list[str] = field(default_factory=list)


@dataclass(slots=True)
class KGRepairSummary:
    dry_run: bool
    clusters: list[KGDuplicateCluster] = field(default_factory=list)
    merged_node_count: int = 0
    deleted_node_count: int = 0
    merged_edge_count: int = 0
    deleted_edge_count: int = 0


async def audit_duplicate_node_clusters(conn) -> list[KGDuplicateCluster]:
    """Return deterministic duplicate clusters keyed by node type and canonical label."""
    result = await conn.execute(
        sa.select(
            knowledge_graph_nodes.c.node_type,
            knowledge_graph_nodes.c.canonical_label,
        )
        .where(knowledge_graph_nodes.c.canonical_label != "")
        .group_by(
            knowledge_graph_nodes.c.node_type,
            knowledge_graph_nodes.c.canonical_label,
        )
        .having(sa.func.count() > 1)
        .order_by(
            knowledge_graph_nodes.c.node_type.asc(),
            knowledge_graph_nodes.c.canonical_label.asc(),
        )
    )

    clusters: list[KGDuplicateCluster] = []
    for group in result:
        rows = (
            await conn.execute(
                sa.select(
                    knowledge_graph_nodes.c.node_id,
                    knowledge_graph_nodes.c.label,
                    knowledge_graph_nodes.c.properties,
                    knowledge_graph_nodes.c.validation_count,
                    knowledge_graph_nodes.c.confidence_score,
                    knowledge_graph_nodes.c.first_seen,
                )
                .where(
                    knowledge_graph_nodes.c.node_type == group.node_type,
                    knowledge_graph_nodes.c.canonical_label == group.canonical_label,
                )
                .order_by(
                    knowledge_graph_nodes.c.validation_count.desc(),
                    knowledge_graph_nodes.c.confidence_score.desc(),
                    knowledge_graph_nodes.c.first_seen.asc(),
                    knowledge_graph_nodes.c.node_id.asc(),
                )
            )
        ).fetchall()
        if len(rows) < 2:
            continue
        primary = rows[0]
        duplicates = rows[1:]
        clusters.append(
            KGDuplicateCluster(
                node_type=group.node_type,
                canonical_label=group.canonical_label,
                primary_node_id=primary.node_id,
                primary_label=primary.label,
                duplicate_node_ids=[row.node_id for row in duplicates],
                duplicate_labels=[row.label for row in duplicates],
            )
        )
    return clusters


async def repair_duplicate_nodes(conn, *, dry_run: bool = True) -> KGRepairSummary:
    """Repair duplicate KG nodes by merging refs into canonical primaries."""
    clusters = await audit_duplicate_node_clusters(conn)
    summary = KGRepairSummary(dry_run=dry_run, clusters=clusters)
    if dry_run:
        return summary

    for cluster in clusters:
        primary = await _load_node_row(conn, cluster.primary_node_id)
        if primary is None:
            continue
        duplicate_rows = [
            row
            for duplicate_id in cluster.duplicate_node_ids
            if (row := await _load_node_row(conn, duplicate_id)) is not None
        ]
        if not duplicate_rows:
            continue

        merged_aliases = _collect_aliases([primary, *duplicate_rows])
        merged_properties = dict(primary.properties or {})
        if merged_aliases:
            merged_properties["aliases"] = merged_aliases

        merged_confidence = max(
            [float(primary.confidence_score or 0.0)]
            + [float(row.confidence_score or 0.0) for row in duplicate_rows]
        )
        total_validations = int(primary.validation_count or 0) + sum(
            int(row.validation_count or 0) for row in duplicate_rows
        )
        total_challenges = int(primary.challenge_count or 0) + sum(
            int(row.challenge_count or 0) for row in duplicate_rows
        )
        total_failures = int(primary.challenge_failures or 0) + sum(
            int(row.challenge_failures or 0) for row in duplicate_rows
        )
        last_validated = max(
            [value for value in [primary.last_validated, *[row.last_validated for row in duplicate_rows]] if value],
            default=None,
        )

        await conn.execute(
            knowledge_graph_nodes.update()
            .where(knowledge_graph_nodes.c.node_id == cluster.primary_node_id)
            .values(
                canonical_label=normalize_canonical_label(cluster.primary_label),
                properties=merged_properties,
                confidence_score=Decimal(str(merged_confidence)),
                validation_count=total_validations,
                challenge_count=total_challenges,
                challenge_failures=total_failures,
                last_validated=last_validated,
            )
        )

        for duplicate in duplicate_rows:
            await _rewrite_edge_endpoints(conn, duplicate.node_id, cluster.primary_node_id)
            await _rewrite_finding_node_refs(conn, duplicate.node_id, cluster.primary_node_id)
            await emit_event(
                conn,
                "kg_node_repaired_merge",
                entity_id=cluster.primary_node_id,
                entity_type="kg_node",
                payload={
                    "absorbed_node_id": str(duplicate.node_id),
                    "absorbed_label": duplicate.label,
                    "canonical_label": cluster.canonical_label,
                },
            )
            await conn.execute(
                knowledge_graph_nodes.delete().where(
                    knowledge_graph_nodes.c.node_id == duplicate.node_id
                )
            )
            summary.deleted_node_count += 1

        summary.merged_node_count += len(duplicate_rows)
        collapsed = await _collapse_duplicate_edges(conn)
        summary.merged_edge_count += collapsed["merged_edge_count"]
        summary.deleted_edge_count += collapsed["deleted_edge_count"]

    return summary


async def _load_node_row(conn, node_id: UUID):
    return (
        await conn.execute(
            sa.select(
                knowledge_graph_nodes.c.node_id,
                knowledge_graph_nodes.c.label,
                knowledge_graph_nodes.c.properties,
                knowledge_graph_nodes.c.confidence_score,
                knowledge_graph_nodes.c.validation_count,
                knowledge_graph_nodes.c.challenge_count,
                knowledge_graph_nodes.c.challenge_failures,
                knowledge_graph_nodes.c.last_validated,
            ).where(knowledge_graph_nodes.c.node_id == node_id)
        )
    ).first()


def _collect_aliases(rows: list[Any]) -> list[str]:
    aliases: set[str] = set()
    for row in rows:
        label = str(row.label or "").strip()
        if label:
            aliases.add(label)
        for alias in (row.properties or {}).get("aliases", []):
            text = str(alias).strip()
            if text:
                aliases.add(text)
    return sorted(aliases)


async def _rewrite_edge_endpoints(conn, duplicate_node_id: UUID, primary_node_id: UUID) -> None:
    await conn.execute(
        knowledge_graph_edges.update()
        .where(knowledge_graph_edges.c.source_node_id == duplicate_node_id)
        .values(source_node_id=primary_node_id)
    )
    await conn.execute(
        knowledge_graph_edges.update()
        .where(knowledge_graph_edges.c.target_node_id == duplicate_node_id)
        .values(target_node_id=primary_node_id)
    )


async def _rewrite_finding_node_refs(conn, duplicate_node_id: UUID, primary_node_id: UUID) -> None:
    result = await conn.execute(
        sa.select(findings.c.finding_id, findings.c.kg_nodes_created).where(
            sa.cast(findings.c.kg_nodes_created, JSONB).contains(
                [str(duplicate_node_id)]
            )
        )
    )
    for row in result:
        rewritten = _rewrite_uuid_ref_list(
            row.kg_nodes_created,
            old_id=duplicate_node_id,
            new_id=primary_node_id,
        )
        await conn.execute(
            findings.update()
            .where(findings.c.finding_id == row.finding_id)
            .values(kg_nodes_created=rewritten)
        )


async def _rewrite_finding_edge_refs(conn, duplicate_edge_id: UUID, primary_edge_id: UUID | None) -> None:
    result = await conn.execute(
        sa.select(findings.c.finding_id, findings.c.kg_edges_created).where(
            sa.cast(findings.c.kg_edges_created, JSONB).contains(
                [str(duplicate_edge_id)]
            )
        )
    )
    for row in result:
        rewritten = _rewrite_uuid_ref_list(
            row.kg_edges_created,
            old_id=duplicate_edge_id,
            new_id=primary_edge_id,
        )
        await conn.execute(
            findings.update()
            .where(findings.c.finding_id == row.finding_id)
            .values(kg_edges_created=rewritten)
        )


def _rewrite_uuid_ref_list(values, *, old_id: UUID, new_id: UUID | None) -> list[str]:
    rewritten: list[str] = []
    seen: set[str] = set()
    old_text = str(old_id)
    new_text = str(new_id) if new_id is not None else None
    for value in values or []:
        text = str(value)
        if text == old_text:
            text = new_text
        if not text or text in seen:
            continue
        seen.add(text)
        rewritten.append(text)
    return rewritten


async def _collapse_duplicate_edges(conn) -> dict[str, int]:
    duplicate_groups = (
        await conn.execute(
            sa.select(
                knowledge_graph_edges.c.source_node_id,
                knowledge_graph_edges.c.target_node_id,
                knowledge_graph_edges.c.relationship_type,
            )
            .group_by(
                knowledge_graph_edges.c.source_node_id,
                knowledge_graph_edges.c.target_node_id,
                knowledge_graph_edges.c.relationship_type,
            )
            .having(sa.func.count() > 1)
        )
    ).fetchall()

    merged_edge_count = 0
    deleted_edge_count = 0
    for group in duplicate_groups:
        rows = (
            await conn.execute(
                sa.select(
                    knowledge_graph_edges.c.edge_id,
                    knowledge_graph_edges.c.source_node_id,
                    knowledge_graph_edges.c.target_node_id,
                    knowledge_graph_edges.c.relationship_type,
                    knowledge_graph_edges.c.weight,
                    knowledge_graph_edges.c.confidence_score,
                    knowledge_graph_edges.c.evidence_ids,
                    knowledge_graph_edges.c.challenged_by_objective_ids,
                    knowledge_graph_edges.c.properties,
                    knowledge_graph_edges.c.created_at,
                )
                .where(
                    knowledge_graph_edges.c.source_node_id == group.source_node_id,
                    knowledge_graph_edges.c.target_node_id == group.target_node_id,
                    knowledge_graph_edges.c.relationship_type == group.relationship_type,
                )
                .order_by(
                    knowledge_graph_edges.c.confidence_score.desc(),
                    knowledge_graph_edges.c.weight.desc(),
                    knowledge_graph_edges.c.created_at.asc(),
                )
            )
        ).fetchall()
        if not rows:
            continue

        primary = rows[0]
        duplicates = rows[1:]
        if primary.source_node_id == primary.target_node_id:
            await _rewrite_finding_edge_refs(conn, primary.edge_id, None)
            await conn.execute(
                knowledge_graph_edges.delete().where(
                    knowledge_graph_edges.c.edge_id == primary.edge_id
                )
            )
            deleted_edge_count += 1
            for duplicate in duplicates:
                await _rewrite_finding_edge_refs(conn, duplicate.edge_id, None)
                await conn.execute(
                    knowledge_graph_edges.delete().where(
                        knowledge_graph_edges.c.edge_id == duplicate.edge_id
                    )
                )
                deleted_edge_count += 1
            continue

        evidence_ids = _merge_string_list(
            *[row.evidence_ids for row in rows]
        )
        challenged_ids = _merge_string_list(
            *[row.challenged_by_objective_ids for row in rows]
        )
        merged_properties = {}
        for row in rows:
            if isinstance(row.properties, dict):
                merged_properties.update(row.properties)

        await conn.execute(
            knowledge_graph_edges.update()
            .where(knowledge_graph_edges.c.edge_id == primary.edge_id)
            .values(
                weight=Decimal(str(max(float(row.weight or 0.0) for row in rows))),
                confidence_score=Decimal(
                    str(max(float(row.confidence_score or 0.0) for row in rows))
                ),
                evidence_ids=evidence_ids,
                challenged_by_objective_ids=challenged_ids,
                properties=merged_properties,
            )
        )

        for duplicate in duplicates:
            await _rewrite_finding_edge_refs(conn, duplicate.edge_id, primary.edge_id)
            await emit_event(
                conn,
                "kg_edge_repaired_merge",
                entity_id=primary.edge_id,
                entity_type="kg_edge",
                payload={
                    "absorbed_edge_id": str(duplicate.edge_id),
                    "relationship_type": primary.relationship_type,
                },
            )
            await conn.execute(
                knowledge_graph_edges.delete().where(
                    knowledge_graph_edges.c.edge_id == duplicate.edge_id
                )
            )
            merged_edge_count += 1
            deleted_edge_count += 1

    return {
        "merged_edge_count": merged_edge_count,
        "deleted_edge_count": deleted_edge_count,
    }


def _merge_string_list(*value_sets) -> list[str]:
    merged: list[str] = []
    seen: set[str] = set()
    for values in value_sets:
        for value in values or []:
            text = str(value).strip()
            if not text or text in seen:
                continue
            seen.add(text)
            merged.append(text)
    return merged
