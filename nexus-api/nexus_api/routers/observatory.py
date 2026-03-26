"""Aggregated observability endpoints for the NEXUS dashboard."""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID

import sqlalchemy as sa
from fastapi import APIRouter, Query

from nexus_core.config import get_settings
from nexus_core.database import get_connection
from nexus_core.models.events import events
from nexus_core.models.findings import findings
from nexus_core.models.instances import agent_instances
from nexus_core.models.objectives import objectives
from nexus_core.models.peer_reviews import peer_reviews
from nexus_core.models.personas import agent_personas
from nexus_core.models.telemetry import agent_telemetry

from nexus_api.schemas import (
    AlertFeedResponse,
    AlertItemResponse,
    ObjectiveRadarItemResponse,
    ObjectiveRadarResponse,
    ObservatoryOverviewResponse,
    PersonaWorkloadItemResponse,
    PersonaWorkloadResponse,
    ReviewIntelResponse,
    ReviewOutcomeSummaryResponse,
)

router = APIRouter(prefix="/api/observatory", tags=["observatory"])

SEVERITY_ORDER = {"critical": 0, "warning": 1, "info": 2}
ACTIVE_OBJECTIVE_STATUSES = {
    "proposed",
    "approved",
    "active",
    "in_progress",
    "revision_requested",
    "synthesizing",
}
ACTIVE_INSTANCE_STATUSES = {"pending", "running"}


def _to_float(value: Any) -> float:
    if value is None:
        return 0.0
    if isinstance(value, Decimal):
        return float(value)
    return float(value)


def _minutes_since(timestamp: datetime | None, now: datetime) -> int:
    if timestamp is None:
        return 0
    return max(int((now - timestamp).total_seconds() // 60), 0)


def _alert(
    *,
    alert_id: str,
    severity: str,
    category: str,
    title: str,
    summary: str,
    detected_at: datetime,
    metric_label: str | None = None,
    metric_value: float | int | None = None,
    entity_id: UUID | None = None,
    entity_type: str | None = None,
) -> dict[str, Any]:
    return {
        "alert_id": alert_id,
        "severity": severity,
        "category": category,
        "title": title,
        "summary": summary,
        "metric_label": metric_label,
        "metric_value": metric_value,
        "entity_id": entity_id,
        "entity_type": entity_type,
        "detected_at": detected_at,
    }


def build_alerts(
    *,
    instance_rows,
    finding_rows,
    objective_rows,
    total_spend_usd: float,
    budget_ceiling_usd: float,
    now: datetime,
) -> list[dict[str, Any]]:
    alerts: list[dict[str, Any]] = []
    budget_utilization = (
        (total_spend_usd / budget_ceiling_usd) * 100
        if budget_ceiling_usd > 0
        else 0.0
    )

    if budget_utilization >= 90:
        alerts.append(
            _alert(
                alert_id="budget-critical",
                severity="critical",
                category="budget",
                title="Budget nearly exhausted",
                summary=f"Compute spend is at {budget_utilization:.1f}% of the ceiling.",
                metric_label="Budget %",
                metric_value=round(budget_utilization, 1),
                detected_at=now,
            )
        )
    elif budget_utilization >= 75:
        alerts.append(
            _alert(
                alert_id="budget-warning",
                severity="warning",
                category="budget",
                title="Budget burn elevated",
                summary=f"Compute spend is at {budget_utilization:.1f}% of the ceiling.",
                metric_label="Budget %",
                metric_value=round(budget_utilization, 1),
                detected_at=now,
            )
        )

    for row in instance_rows:
        age_minutes = _minutes_since(getattr(row, "started_at", None), now)
        if row.status == "running" and age_minutes >= 45:
            alerts.append(
                _alert(
                    alert_id=f"instance-stalled-{row.instance_id}",
                    severity="critical",
                    category="instances",
                    title=f"Stalled instance: {row.persona_name}",
                    summary=f"{row.persona_name} has been running on {row.objective_title} for {age_minutes} minutes.",
                    metric_label="Age min",
                    metric_value=age_minutes,
                    entity_id=row.instance_id,
                    entity_type="instance",
                    detected_at=row.started_at,
                )
            )
        elif row.status == "running" and age_minutes >= 20:
            alerts.append(
                _alert(
                    alert_id=f"instance-slow-{row.instance_id}",
                    severity="warning",
                    category="instances",
                    title=f"Slow instance: {row.persona_name}",
                    summary=f"{row.persona_name} has been running on {row.objective_title} for {age_minutes} minutes.",
                    metric_label="Age min",
                    metric_value=age_minutes,
                    entity_id=row.instance_id,
                    entity_type="instance",
                    detected_at=row.started_at,
                )
            )
        elif row.status == "pending" and age_minutes >= 10:
            alerts.append(
                _alert(
                    alert_id=f"instance-queued-{row.instance_id}",
                    severity="warning",
                    category="instances",
                    title=f"Queued instance waiting: {row.persona_name}",
                    summary=f"{row.persona_name} has been pending on {row.objective_title} for {age_minutes} minutes.",
                    metric_label="Age min",
                    metric_value=age_minutes,
                    entity_id=row.instance_id,
                    entity_type="instance",
                    detected_at=row.started_at,
                )
            )
        elif row.status == "failed":
            alerts.append(
                _alert(
                    alert_id=f"instance-failed-{row.instance_id}",
                    severity="critical",
                    category="instances",
                    title=f"Failed instance: {row.persona_name}",
                    summary=row.error_message or f"{row.persona_name} failed while working on {row.objective_title}.",
                    entity_id=row.instance_id,
                    entity_type="instance",
                    detected_at=row.started_at or now,
                )
            )

    for row in finding_rows:
        age_minutes = _minutes_since(row.created_at, now)
        if row.status == "escalated":
            alerts.append(
                _alert(
                    alert_id=f"finding-escalated-{row.finding_id}",
                    severity="critical",
                    category="reviews",
                    title="Finding escalated",
                    summary=f"{row.title} escalated out of peer review.",
                    entity_id=row.finding_id,
                    entity_type="finding",
                    detected_at=row.created_at,
                )
            )
        elif row.status == "pending_review" and age_minutes >= 20:
            severity = "critical" if row.impact_level == "high-impact" else "warning"
            alerts.append(
                _alert(
                    alert_id=f"finding-pending-{row.finding_id}",
                    severity=severity,
                    category="reviews",
                    title="Review queue aging",
                    summary=f"{row.title} has been pending review for {age_minutes} minutes.",
                    metric_label="Age min",
                    metric_value=age_minutes,
                    entity_id=row.finding_id,
                    entity_type="finding",
                    detected_at=row.created_at,
                )
            )

    for row in objective_rows:
        detected_at = row.escalated_at or row.created_at or now
        if row.status in {"escalated", "failed"}:
            alerts.append(
                _alert(
                    alert_id=f"objective-escalated-{row.objective_id}",
                    severity="critical",
                    category="objectives",
                    title="Objective escalated",
                    summary=f"{row.title} is {row.status}.",
                    metric_label="Priority",
                    metric_value=row.priority,
                    entity_id=row.objective_id,
                    entity_type="objective",
                    detected_at=detected_at,
                )
            )
        elif row.status == "revision_requested":
            alerts.append(
                _alert(
                    alert_id=f"objective-revision-{row.objective_id}",
                    severity="warning",
                    category="objectives",
                    title="Objective revision requested",
                    summary=f"{row.title} is waiting on another revision pass.",
                    metric_label="Priority",
                    metric_value=row.priority,
                    entity_id=row.objective_id,
                    entity_type="objective",
                    detected_at=detected_at,
                )
            )

    return sorted(
        alerts,
        key=lambda item: (
            SEVERITY_ORDER.get(item["severity"], 99),
            -(float(item["metric_value"]) if item["metric_value"] is not None else 0.0),
            item["detected_at"],
        ),
    )


def build_persona_workload(
    *,
    persona_rows,
    instance_rows,
    objective_title_map: dict[UUID, str],
    telemetry_rows,
    now: datetime,
    window_hours: int,
) -> list[dict[str, Any]]:
    cutoff = now - timedelta(hours=window_hours)
    instances_by_persona: dict[UUID, list[Any]] = defaultdict(list)
    for row in instance_rows:
        instances_by_persona[row.persona_id].append(row)

    telemetry_by_persona: dict[UUID, list[Any]] = defaultdict(list)
    for row in telemetry_rows:
        telemetry_by_persona[row.persona_id].append(row)

    items: list[dict[str, Any]] = []
    for persona in persona_rows:
        persona_instances = instances_by_persona.get(persona.persona_id, [])
        persona_telemetry = telemetry_by_persona.get(persona.persona_id, [])
        running_instances = sum(1 for row in persona_instances if row.status == "running")
        pending_instances = sum(1 for row in persona_instances if row.status == "pending")
        completed_24h = sum(
            1
            for row in persona_instances
            if row.status in {"completed", "integrated"}
            and (row.completed_at or row.started_at) is not None
            and (row.completed_at or row.started_at) >= cutoff
        )
        failed_24h = sum(
            1
            for row in persona_instances
            if row.status == "failed"
            and (row.completed_at or row.started_at) is not None
            and (row.completed_at or row.started_at) >= cutoff
        )
        spend_24h = round(sum(_to_float(row.cost_total_usd) for row in persona_telemetry), 4)
        avg_latency_ms = round(
            sum(row.latency_ms for row in persona_telemetry) / len(persona_telemetry),
            1,
        ) if persona_telemetry else 0.0
        success_rate = round(
            sum(1 for row in persona_telemetry if row.success) / len(persona_telemetry),
            3,
        ) if persona_telemetry else 0.0

        ranked_assignments = sorted(
            persona_instances,
            key=lambda row: (
                0 if row.status == "running" else 1 if row.status == "pending" else 2,
                row.started_at or datetime.min.replace(tzinfo=UTC),
            ),
            reverse=False,
        )
        current_assignment = ranked_assignments[0] if ranked_assignments else None

        items.append(
            {
                "persona_id": persona.persona_id,
                "persona_name": persona.persona_name,
                "role_class": persona.role_class,
                "status": persona.status,
                "current_assignment": (
                    objective_title_map.get(current_assignment.objective_id)
                    if current_assignment is not None
                    else None
                ),
                "current_assignment_status": current_assignment.status if current_assignment is not None else None,
                "running_instances": running_instances,
                "pending_instances": pending_instances,
                "completed_24h": completed_24h,
                "failed_24h": failed_24h,
                "avg_latency_ms_24h": avg_latency_ms,
                "success_rate_24h": success_rate,
                "spend_24h": spend_24h,
            }
        )

    return sorted(
        items,
        key=lambda item: (
            -item["running_instances"],
            -item["pending_instances"],
            -item["completed_24h"],
            -item["spend_24h"],
            item["persona_name"],
        ),
    )


def build_objective_radar(
    *,
    objective_rows,
    instance_rows,
    finding_rows,
    telemetry_rows,
    now: datetime,
    limit: int,
) -> list[dict[str, Any]]:
    objective_map = {row.objective_id: row for row in objective_rows}
    children_map: dict[UUID, list[UUID]] = defaultdict(list)
    for row in objective_rows:
        if row.parent_objective_id is not None:
            children_map[row.parent_objective_id].append(row.objective_id)

    instances_by_objective: dict[UUID, list[Any]] = defaultdict(list)
    for row in instance_rows:
        instances_by_objective[row.objective_id].append(row)

    findings_by_objective: dict[UUID, list[Any]] = defaultdict(list)
    for row in finding_rows:
        findings_by_objective[row.objective_id].append(row)

    telemetry_by_objective: dict[UUID, list[Any]] = defaultdict(list)
    for row in telemetry_rows:
        telemetry_by_objective[row.objective_id].append(row)

    def subtree_ids(root_id: UUID) -> list[UUID]:
        ordered: list[UUID] = []
        stack = [root_id]
        while stack:
            current = stack.pop()
            ordered.append(current)
            stack.extend(children_map.get(current, []))
        return ordered

    items: list[dict[str, Any]] = []
    roots = [row for row in objective_rows if row.parent_objective_id is None]
    for root in roots:
        subtree = subtree_ids(root.objective_id)
        subtree_objectives = [objective_map[obj_id] for obj_id in subtree if obj_id in objective_map]
        subtree_children = [row for row in subtree_objectives if row.objective_id != root.objective_id]

        subtree_instances = [item for obj_id in subtree for item in instances_by_objective.get(obj_id, [])]
        subtree_findings = [item for obj_id in subtree for item in findings_by_objective.get(obj_id, [])]
        subtree_telemetry = [item for obj_id in subtree for item in telemetry_by_objective.get(obj_id, [])]

        active_instances = sum(1 for row in subtree_instances if row.status in ACTIVE_INSTANCE_STATUSES)
        completed_instances = sum(1 for row in subtree_instances if row.status in {"completed", "integrated"})
        findings_total = len(subtree_findings)
        validated_findings = sum(1 for row in subtree_findings if row.status == "validated")
        pending_reviews = sum(1 for row in subtree_findings if row.status in {"pending_review", "revision_requested"})
        subtree_objective_count = len(subtree_children)
        subtree_completed_count = sum(1 for row in subtree_children if row.status == "completed")
        progress_pct = round(
            (
                (subtree_completed_count / subtree_objective_count) * 100
                if subtree_objective_count
                else (100.0 if root.status == "completed" else 0.0)
            ),
            1,
        )
        total_cost_usd = round(sum(_to_float(row.cost_total_usd) for row in subtree_telemetry), 4)
        timestamps = [root.created_at]
        timestamps.extend(row.completed_at for row in subtree_objectives if getattr(row, "completed_at", None))
        timestamps.extend(row.started_at for row in subtree_instances if getattr(row, "started_at", None))
        timestamps.extend(row.completed_at for row in subtree_instances if getattr(row, "completed_at", None))
        timestamps.extend(row.created_at for row in subtree_findings if getattr(row, "created_at", None))
        timestamps.extend(row.api_call_timestamp for row in subtree_telemetry if getattr(row, "api_call_timestamp", None))
        last_activity_at = max(ts for ts in timestamps if ts is not None)
        age_minutes = _minutes_since(root.created_at, now)
        needs_attention = root.status in {"revision_requested", "escalated", "failed"} or any(
            row.status in {"revision_requested", "escalated", "failed"} for row in subtree_children
        )
        attention_score = round(
            (root.priority * 2.0)
            + (active_instances * 4.0)
            + (pending_reviews * 2.5)
            + (5.0 if needs_attention else 0.0)
            + min(findings_total, 5),
            1,
        )

        items.append(
            {
                "objective_id": root.objective_id,
                "title": root.title,
                "status": root.status,
                "objective_type": root.objective_type,
                "impact_level": root.impact_level,
                "priority": root.priority,
                "active_instances": active_instances,
                "completed_instances": completed_instances,
                "findings_total": findings_total,
                "validated_findings": validated_findings,
                "pending_reviews": pending_reviews,
                "subtree_objective_count": subtree_objective_count,
                "subtree_completed_count": subtree_completed_count,
                "progress_pct": progress_pct,
                "total_cost_usd": total_cost_usd,
                "age_minutes": age_minutes,
                "last_activity_at": last_activity_at,
                "attention_score": attention_score,
            }
        )

    items.sort(
        key=lambda item: (
            0 if item["status"] in {"revision_requested", "escalated", "failed"} else 1,
            -item["attention_score"],
            -item["active_instances"],
            item["last_activity_at"],
        ),
    )
    return items[:limit]


def build_review_intel(
    *,
    review_rows,
    finding_rows,
    review_event_rows,
    finding_map: dict[UUID, Any],
) -> dict[str, Any]:
    reviewer_verdict_counts = Counter(row.verdict for row in review_rows)
    outcome_counts = Counter(str((row.payload or {}).get("verdict", "reviewed")) for row in review_event_rows)
    finding_status_counts = Counter(row.status for row in finding_rows)
    mean_confidence = round(
        sum(_to_float(row.confidence_rating) for row in review_rows) / len(review_rows),
        3,
    ) if review_rows else 0.0
    approval_rate = round(
        outcome_counts.get("approved", 0) / max(len(review_event_rows), 1),
        3,
    ) if review_event_rows else 0.0

    recent_outcomes = []
    for row in sorted(review_event_rows, key=lambda item: item.created_at, reverse=True)[:6]:
        payload = dict(row.payload or {})
        finding = finding_map.get(row.entity_id)
        recent_outcomes.append(
            {
                "finding_id": row.entity_id,
                "title": finding.title if finding is not None else "Untitled finding",
                "status": payload.get("finding_status", getattr(finding, "status", "unknown")),
                "impact_level": payload.get("impact_level", getattr(finding, "impact_level", "routine")),
                "review_round": int(payload.get("review_round", getattr(finding, "review_round", 0)) or 0),
                "mean_confidence": round(_to_float(payload.get("mean_review_confidence")), 3),
                "approval_count": int(payload.get("approval_count", 0) or 0),
                "support_count": int(payload.get("support_count", 0) or 0),
                "reviewer_count": int(payload.get("reviewer_count", 0) or 0),
                "verdict": str(payload.get("verdict", "reviewed")),
                "reviewed_at": row.created_at,
            }
        )

    high_impact_pending_count = sum(
        1
        for row in finding_rows
        if row.impact_level == "high-impact" and row.status in {"pending_review", "revision_requested"}
    )

    return {
        "total_reviews_24h": len(review_rows),
        "finding_outcomes_24h": len(review_event_rows),
        "mean_review_confidence_24h": mean_confidence,
        "approval_rate_24h": approval_rate,
        "outcome_counts": dict(outcome_counts),
        "reviewer_verdict_counts": dict(reviewer_verdict_counts),
        "finding_status_counts": dict(finding_status_counts),
        "high_impact_pending_count": high_impact_pending_count,
        "recent_outcomes": recent_outcomes,
    }


@router.get("/overview", response_model=ObservatoryOverviewResponse)
async def observatory_overview():
    """High-level mission-control summary metrics."""
    now = datetime.now(UTC)
    cutoff_24h = now - timedelta(hours=24)
    settings = get_settings()
    budget_ceiling = float(settings.BUDGET_CEILING_USD)

    async with get_connection() as conn:
        active_personas = int(
            await conn.scalar(
                sa.select(sa.func.count())
                .select_from(agent_personas)
                .where(agent_personas.c.status == "active")
            )
            or 0
        )
        active_objectives = int(
            await conn.scalar(
                sa.select(sa.func.count())
                .select_from(objectives)
                .where(
                    objectives.c.status.in_(ACTIVE_OBJECTIVE_STATUSES),
                    objectives.c.objective_type != "market",
                )
            )
            or 0
        )
        running_instances = int(
            await conn.scalar(
                sa.select(sa.func.count())
                .select_from(agent_instances)
                .join(objectives, agent_instances.c.objective_id == objectives.c.objective_id)
                .where(
                    agent_instances.c.status.in_(list(ACTIVE_INSTANCE_STATUSES)),
                    objectives.c.objective_type != "market",
                )
            )
            or 0
        )
        pending_reviews = int(
            await conn.scalar(
                sa.select(sa.func.count())
                .select_from(findings)
                .join(objectives, findings.c.objective_id == objectives.c.objective_id)
                .where(
                    findings.c.status.in_(["pending_review", "revision_requested"]),
                    objectives.c.objective_type != "market",
                )
            )
            or 0
        )
        escalated_objectives = int(
            await conn.scalar(
                sa.select(sa.func.count())
                .select_from(objectives)
                .where(
                    objectives.c.status.in_(["escalated", "failed"]),
                    objectives.c.objective_type != "market",
                )
            )
            or 0
        )
        objectives_completed_24h = int(
            await conn.scalar(
                sa.select(sa.func.count())
                .select_from(objectives)
                .where(
                    objectives.c.completed_at.isnot(None),
                    objectives.c.completed_at >= cutoff_24h,
                    objectives.c.objective_type != "market",
                )
            )
            or 0
        )
        total_spend_usd = _to_float(
            await conn.scalar(
                sa.select(sa.func.coalesce(sa.func.sum(agent_telemetry.c.cost_total_usd), Decimal("0")))
            )
        )
        review_rows = (
            await conn.execute(
                sa.select(peer_reviews.c.confidence_rating)
                .where(peer_reviews.c.created_at >= cutoff_24h)
            )
        ).fetchall()
        telemetry_rows = (
            await conn.execute(
                sa.select(agent_telemetry.c.success)
                .where(agent_telemetry.c.api_call_timestamp >= cutoff_24h)
            )
        ).fetchall()
        outcome_event_rows = (
            await conn.execute(
                sa.select(events.c.payload)
                .where(events.c.event_type == "finding_reviewed", events.c.created_at >= cutoff_24h)
            )
        ).fetchall()

    findings_validated_24h = sum(
        1
        for row in outcome_event_rows
        if str((row.payload or {}).get("finding_status")) == "validated"
    )
    mean_review_confidence_24h = round(
        sum(_to_float(row.confidence_rating) for row in review_rows) / len(review_rows),
        3,
    ) if review_rows else 0.0
    total_calls_24h = len(telemetry_rows)
    success_rate_24h = round(
        sum(1 for row in telemetry_rows if row.success) / max(total_calls_24h, 1),
        3,
    ) if telemetry_rows else 0.0
    budget_utilization_pct = round(
        (total_spend_usd / budget_ceiling) * 100,
        2,
    ) if budget_ceiling > 0 else 0.0

    return ObservatoryOverviewResponse(
        active_personas=active_personas,
        active_objectives=active_objectives,
        running_instances=running_instances,
        pending_reviews=pending_reviews,
        escalated_objectives=escalated_objectives,
        objectives_completed_24h=objectives_completed_24h,
        findings_validated_24h=findings_validated_24h,
        mean_review_confidence_24h=mean_review_confidence_24h,
        total_spend_usd=round(total_spend_usd, 4),
        budget_remaining_usd=round(budget_ceiling - total_spend_usd, 4),
        budget_utilization_pct=budget_utilization_pct,
        success_rate_24h=success_rate_24h,
        total_calls_24h=total_calls_24h,
    )


@router.get("/alerts", response_model=AlertFeedResponse)
async def observatory_alerts(limit: int = Query(8, ge=1, le=20)):
    """Derived operational alerts for stalled work and pressure points."""
    now = datetime.now(UTC)
    settings = get_settings()
    budget_ceiling = float(settings.BUDGET_CEILING_USD)

    async with get_connection() as conn:
        instance_rows = (
            await conn.execute(
                sa.select(
                    agent_instances.c.instance_id,
                    agent_instances.c.status,
                    agent_instances.c.started_at,
                    agent_instances.c.error_message,
                    agent_personas.c.persona_name,
                    objectives.c.title.label("objective_title"),
                )
                .join(agent_personas, agent_instances.c.persona_id == agent_personas.c.persona_id)
                .join(objectives, agent_instances.c.objective_id == objectives.c.objective_id)
                .where(
                    agent_instances.c.status.in_(["running", "pending", "failed"]),
                    objectives.c.objective_type != "market",
                )
            )
        ).fetchall()
        finding_rows = (
            await conn.execute(
                sa.select(
                    findings.c.finding_id,
                    findings.c.status,
                    findings.c.title,
                    findings.c.impact_level,
                    findings.c.created_at,
                )
                .join(objectives, findings.c.objective_id == objectives.c.objective_id)
                .where(
                    findings.c.status.in_(["pending_review", "escalated"]),
                    objectives.c.objective_type != "market",
                )
            )
        ).fetchall()
        objective_rows = (
            await conn.execute(
                sa.select(
                    objectives.c.objective_id,
                    objectives.c.title,
                    objectives.c.status,
                    objectives.c.priority,
                    objectives.c.created_at,
                    objectives.c.escalated_at,
                )
                .where(
                    objectives.c.status.in_(["revision_requested", "escalated", "failed"]),
                    objectives.c.objective_type != "market",
                )
            )
        ).fetchall()
        total_spend_usd = _to_float(
            await conn.scalar(
                sa.select(sa.func.coalesce(sa.func.sum(agent_telemetry.c.cost_total_usd), Decimal("0")))
            )
        )

    alerts = build_alerts(
        instance_rows=instance_rows,
        finding_rows=finding_rows,
        objective_rows=objective_rows,
        total_spend_usd=total_spend_usd,
        budget_ceiling_usd=budget_ceiling,
        now=now,
    )[:limit]

    return AlertFeedResponse(
        alerts=[AlertItemResponse(**alert) for alert in alerts],
        count=len(alerts),
    )


@router.get("/reviews", response_model=ReviewIntelResponse)
async def observatory_reviews():
    """Peer-review and validation intelligence for the last 24 hours."""
    cutoff_24h = datetime.now(UTC) - timedelta(hours=24)

    async with get_connection() as conn:
        review_rows = (
            await conn.execute(
                sa.select(
                    peer_reviews.c.finding_id,
                    peer_reviews.c.verdict,
                    peer_reviews.c.confidence_rating,
                    peer_reviews.c.created_at,
                )
                .where(peer_reviews.c.created_at >= cutoff_24h)
            )
        ).fetchall()
        finding_rows = (await conn.execute(sa.select(findings))).fetchall()
        review_event_rows = (
            await conn.execute(
                sa.select(
                    events.c.entity_id,
                    events.c.payload,
                    events.c.created_at,
                )
                .where(events.c.event_type == "finding_reviewed", events.c.created_at >= cutoff_24h)
                .order_by(events.c.created_at.desc())
            )
        ).fetchall()

    finding_map = {row.finding_id: row for row in finding_rows}
    payload = build_review_intel(
        review_rows=review_rows,
        finding_rows=finding_rows,
        review_event_rows=review_event_rows,
        finding_map=finding_map,
    )
    payload["recent_outcomes"] = [
        ReviewOutcomeSummaryResponse(**item) for item in payload["recent_outcomes"]
    ]
    return ReviewIntelResponse(**payload)


@router.get("/workload", response_model=PersonaWorkloadResponse)
async def observatory_workload(
    limit: int = Query(10, ge=1, le=30),
    window_hours: int = Query(24, ge=1, le=168),
):
    """Current workload and recent throughput by persona."""
    now = datetime.now(UTC)
    cutoff = now - timedelta(hours=window_hours)

    async with get_connection() as conn:
        persona_rows = (
            await conn.execute(
                sa.select(
                    agent_personas.c.persona_id,
                    agent_personas.c.persona_name,
                    agent_personas.c.role_class,
                    agent_personas.c.status,
                )
                .where(agent_personas.c.status == "active")
            )
        ).fetchall()
        instance_rows = (
            await conn.execute(
                sa.select(
                    agent_instances.c.instance_id,
                    agent_instances.c.persona_id,
                    agent_instances.c.objective_id,
                    agent_instances.c.status,
                    agent_instances.c.started_at,
                    agent_instances.c.completed_at,
                )
                .join(objectives, agent_instances.c.objective_id == objectives.c.objective_id)
                .where(
                    sa.or_(
                        agent_instances.c.status.in_(list(ACTIVE_INSTANCE_STATUSES)),
                        agent_instances.c.started_at >= cutoff,
                        agent_instances.c.completed_at >= cutoff,
                    ),
                    objectives.c.objective_type != "market",
                )
            )
        ).fetchall()
        objective_rows = (
            await conn.execute(
                sa.select(objectives.c.objective_id, objectives.c.title).where(
                    objectives.c.objective_type != "market"
                )
            )
        ).fetchall()
        telemetry_rows = (
            await conn.execute(
                sa.select(
                    agent_telemetry.c.persona_id,
                    agent_telemetry.c.cost_total_usd,
                    agent_telemetry.c.latency_ms,
                    agent_telemetry.c.success,
                )
                .where(agent_telemetry.c.api_call_timestamp >= cutoff)
            )
        ).fetchall()

    objective_title_map = {row.objective_id: row.title for row in objective_rows}
    items = build_persona_workload(
        persona_rows=persona_rows,
        instance_rows=instance_rows,
        objective_title_map=objective_title_map,
        telemetry_rows=telemetry_rows,
        now=now,
        window_hours=window_hours,
    )[:limit]

    return PersonaWorkloadResponse(
        items=[PersonaWorkloadItemResponse(**item) for item in items],
        count=len(items),
        window_hours=window_hours,
    )


@router.get("/objectives", response_model=ObjectiveRadarResponse)
async def observatory_objective_radar(limit: int = Query(6, ge=1, le=20)):
    """Top-level objective radar with subtree progress and spend."""
    now = datetime.now(UTC)

    async with get_connection() as conn:
        objective_rows = (
            await conn.execute(
                sa.select(objectives).where(objectives.c.objective_type != "market")
            )
        ).fetchall()
        instance_rows = (
            await conn.execute(
                sa.select(
                    agent_instances.c.objective_id,
                    agent_instances.c.status,
                    agent_instances.c.started_at,
                    agent_instances.c.completed_at,
                )
                .join(objectives, agent_instances.c.objective_id == objectives.c.objective_id)
                .where(objectives.c.objective_type != "market")
            )
        ).fetchall()
        finding_rows = (
            await conn.execute(
                sa.select(
                    findings.c.objective_id,
                    findings.c.status,
                    findings.c.created_at,
                )
                .join(objectives, findings.c.objective_id == objectives.c.objective_id)
                .where(objectives.c.objective_type != "market")
            )
        ).fetchall()
        telemetry_rows = (
            await conn.execute(
                sa.select(
                    agent_telemetry.c.objective_id,
                    agent_telemetry.c.cost_total_usd,
                    agent_telemetry.c.api_call_timestamp,
                )
                .join(objectives, agent_telemetry.c.objective_id == objectives.c.objective_id)
                .where(objectives.c.objective_type != "market")
            )
        ).fetchall()

    items = build_objective_radar(
        objective_rows=objective_rows,
        instance_rows=instance_rows,
        finding_rows=finding_rows,
        telemetry_rows=telemetry_rows,
        now=now,
        limit=limit,
    )
    return ObjectiveRadarResponse(
        items=[ObjectiveRadarItemResponse(**item) for item in items],
        count=len(items),
    )
