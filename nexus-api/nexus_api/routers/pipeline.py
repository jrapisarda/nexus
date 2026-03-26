"""Pipeline status endpoint — real-time visibility into finding workflow stages."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import sqlalchemy as sa
from fastapi import APIRouter

from nexus_core.database import get_connection
from nexus_core.models.findings import findings
from nexus_core.models.instances import agent_instances
from nexus_core.models.objectives import objectives
from nexus_core.models.personas import agent_personas
from nexus_core.models.peer_reviews import peer_reviews

router = APIRouter(prefix="/api/pipeline", tags=["pipeline"])


@router.get("/status")
async def get_pipeline_status() -> dict[str, Any]:
    """Return a snapshot of the current finding pipeline.

    Shows every finding currently in-flight and what stage it's at,
    plus which persona is working on it.
    """
    async with get_connection() as conn:
        # 1. Active findings in the pipeline (not terminal states)
        active_statuses = [
            "pending_review", "citation_checking", "revision_requested",
        ]
        result = await conn.execute(
            sa.select(
                findings.c.finding_id,
                findings.c.title,
                findings.c.status,
                findings.c.impact_level,
                findings.c.review_round,
                findings.c.citation_confidence_score,
                findings.c.citation_check_started_at,
                findings.c.created_at,
                findings.c.objective_id,
                findings.c.instance_id,
            )
            .where(findings.c.status.in_(active_statuses))
            .order_by(findings.c.created_at.desc())
            .limit(30)
        )
        active_findings = result.fetchall()

        # 2. Recently completed findings (last 10 validated/rejected in past hour)
        result = await conn.execute(
            sa.select(
                findings.c.finding_id,
                findings.c.title,
                findings.c.status,
                findings.c.impact_level,
                findings.c.citation_confidence_score,
                findings.c.created_at,
            )
            .where(
                findings.c.status.in_(["validated", "challenged", "escalated"]),
                findings.c.created_at >= sa.func.now() - sa.text("INTERVAL '2 hours'"),
            )
            .order_by(findings.c.created_at.desc())
            .limit(10)
        )
        recent_findings = result.fetchall()

        # 3. Running/pending instances (agents actively working)
        result = await conn.execute(
            sa.select(
                agent_instances.c.instance_id,
                agent_instances.c.persona_id,
                agent_instances.c.objective_id,
                agent_instances.c.status,
                agent_instances.c.spawn_reason,
                agent_instances.c.started_at,
                agent_personas.c.persona_name,
                agent_personas.c.role_class,
            )
            .select_from(
                agent_instances.join(
                    agent_personas,
                    agent_instances.c.persona_id == agent_personas.c.persona_id,
                )
            )
            .where(agent_instances.c.status.in_(["running", "pending"]))
            .order_by(agent_instances.c.started_at.desc())
            .limit(20)
        )
        running_instances = result.fetchall()

        # 4. Completed instances awaiting integration
        result = await conn.execute(
            sa.select(sa.func.count())
            .select_from(agent_instances)
            .where(agent_instances.c.status == "completed")
        )
        pending_integration = result.scalar_one()

        # 5. Gather objective titles for context
        obj_ids = set()
        for f in active_findings:
            obj_ids.add(f.objective_id)
        for inst in running_instances:
            obj_ids.add(inst.objective_id)

        obj_map: dict = {}
        if obj_ids:
            result = await conn.execute(
                sa.select(
                    objectives.c.objective_id,
                    objectives.c.title,
                    objectives.c.objective_type,
                )
                .where(objectives.c.objective_id.in_(list(obj_ids)))
            )
            for row in result:
                obj_map[str(row.objective_id)] = {
                    "title": row.title,
                    "type": row.objective_type,
                }

        # 6. Gather author persona names for findings
        instance_ids = [f.instance_id for f in active_findings]
        author_map: dict = {}
        if instance_ids:
            result = await conn.execute(
                sa.select(
                    agent_instances.c.instance_id,
                    agent_personas.c.persona_name,
                    agent_personas.c.role_class,
                )
                .select_from(
                    agent_instances.join(
                        agent_personas,
                        agent_instances.c.persona_id == agent_personas.c.persona_id,
                    )
                )
                .where(agent_instances.c.instance_id.in_(instance_ids))
            )
            for row in result:
                author_map[str(row.instance_id)] = {
                    "name": row.persona_name,
                    "role": row.role_class,
                }

        # 7. Count reviews per finding
        finding_ids = [f.finding_id for f in active_findings]
        review_counts: dict = {}
        if finding_ids:
            result = await conn.execute(
                sa.select(
                    peer_reviews.c.finding_id,
                    sa.func.count().label("count"),
                )
                .where(peer_reviews.c.finding_id.in_(finding_ids))
                .group_by(peer_reviews.c.finding_id)
            )
            for row in result:
                review_counts[str(row.finding_id)] = row.count

        # 8. Pipeline stage counts
        result = await conn.execute(
            sa.select(
                findings.c.status,
                sa.func.count().label("count"),
            )
            .where(findings.c.status.in_(active_statuses))
            .group_by(findings.c.status)
        )
        stage_counts = {row.status: row.count for row in result}

    now = datetime.now(UTC)

    # Build response
    pipeline_items = []
    for f in active_findings:
        author = author_map.get(str(f.instance_id), {})
        obj = obj_map.get(str(f.objective_id), {})
        age_secs = (now - f.created_at.replace(tzinfo=UTC)).total_seconds() if f.created_at else 0

        # Determine detailed stage
        stage = f.status
        if f.status == "citation_checking":
            stage = "citation_checking"
        elif f.status == "pending_review":
            reviews_done = review_counts.get(str(f.finding_id), 0)
            if reviews_done > 0:
                stage = "reviewing"
            else:
                stage = "awaiting_review"

        pipeline_items.append({
            "finding_id": str(f.finding_id),
            "title": f.title[:80] if f.title else "Untitled",
            "stage": stage,
            "status": f.status,
            "impact_level": f.impact_level,
            "review_round": f.review_round or 0,
            "citation_score": float(f.citation_confidence_score) if f.citation_confidence_score is not None else None,
            "age_seconds": int(age_secs),
            "author_name": author.get("name"),
            "author_role": author.get("role"),
            "objective_title": obj.get("title", "")[:60],
            "objective_type": obj.get("type"),
            "reviews_completed": review_counts.get(str(f.finding_id), 0),
        })

    active_agents = []
    for inst in running_instances:
        obj = obj_map.get(str(inst.objective_id), {})
        age_secs = (now - inst.started_at.replace(tzinfo=UTC)).total_seconds() if inst.started_at else 0
        active_agents.append({
            "instance_id": str(inst.instance_id),
            "persona_name": inst.persona_name,
            "role_class": inst.role_class,
            "spawn_reason": inst.spawn_reason,
            "status": inst.status,
            "objective_title": obj.get("title", "")[:60],
            "age_seconds": int(age_secs),
        })

    recent = []
    for f in recent_findings:
        recent.append({
            "finding_id": str(f.finding_id),
            "title": f.title[:80] if f.title else "Untitled",
            "status": f.status,
            "impact_level": f.impact_level,
            "citation_score": float(f.citation_confidence_score) if f.citation_confidence_score is not None else None,
        })

    return {
        "pipeline": pipeline_items,
        "active_agents": active_agents,
        "recent_completed": recent,
        "pending_integration": pending_integration,
        "stage_counts": {
            "citation_checking": stage_counts.get("citation_checking", 0),
            "pending_review": stage_counts.get("pending_review", 0),
            "revision_requested": stage_counts.get("revision_requested", 0),
        },
        "timestamp": now.isoformat(),
    }
