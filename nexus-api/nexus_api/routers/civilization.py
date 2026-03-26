"""Civilization health, incentive, and resilience endpoints."""

from __future__ import annotations

from uuid import UUID

import sqlalchemy as sa
from fastapi import APIRouter, Query

from nexus_core.civilization.service import get_concentration_metrics
from nexus_core.database import get_connection
from nexus_core.economy.ledger import balance_expression
from nexus_core.models.civilization import (
    circuit_breaker_incidents,
    circuit_breaker_rules,
    civilization_challenges as civilization_challenge_records,
    civilization_quality_holdbacks as civilization_quality_holdback_records,
    evolution_metric_snapshots,
    objective_incentive_profiles,
    persona_capability_scores,
    scout_source_health,
)
from nexus_core.models.findings import findings
from nexus_core.models.personas import agent_personas

from nexus_api.schemas import (
    BreakerIncidentResponse,
    BreakerRuleResponse,
    BreakerStatusResponse,
    CivilizationCapabilityPersonaResponse,
    CivilizationCapabilityResponse,
    CivilizationChallengeListResponse,
    CivilizationChallengeResponse,
    CivilizationOverviewResponse,
    EvolutionHealthResponse,
    ScoutSourceHealthListResponse,
    ScoutSourceHealthResponse,
)

router = APIRouter(prefix="/api/civilization", tags=["civilization"])


async def _capability_map(conn, persona_ids: list[UUID]) -> dict[str, dict[str, float]]:
    if not persona_ids:
        return {}
    rows = (
        await conn.execute(
            sa.select(
                persona_capability_scores.c.persona_id,
                persona_capability_scores.c.capability,
                persona_capability_scores.c.active_score,
                persona_capability_scores.c.persistent_score,
            ).where(persona_capability_scores.c.persona_id.in_(persona_ids))
        )
    ).fetchall()
    payload: dict[str, dict[str, float]] = {}
    for row in rows:
        payload.setdefault(str(row.persona_id), {})[row.capability] = round(
            float(row.active_score) * 0.65 + float(row.persistent_score) * 0.35,
            3,
        )
    return payload


@router.get("/overview", response_model=CivilizationOverviewResponse)
async def civilization_overview():
    async with get_connection() as conn:
        concentration = await get_concentration_metrics(conn)
        pending_challenges = int(
            await conn.scalar(
                sa.select(sa.func.count())
                .select_from(civilization_challenge_records)
                .where(civilization_challenge_records.c.status == "open")
            )
            or 0
        )
        pending_holdbacks = int(
            await conn.scalar(
                sa.select(sa.func.count())
                .select_from(civilization_quality_holdback_records)
                .where(civilization_quality_holdback_records.c.status == "pending")
            )
            or 0
        )
        slow_science_objectives = int(
            await conn.scalar(
                sa.select(sa.func.count())
                .select_from(objective_incentive_profiles)
                .where(objective_incentive_profiles.c.slow_science_enabled == sa.true())
            )
            or 0
        )
        degraded_scout_sources = int(
            await conn.scalar(
                sa.select(sa.func.count())
                .select_from(scout_source_health)
                .where(scout_source_health.c.health_status.in_(["degraded", "critical"]))
            )
            or 0
        )
        open_breaker_incidents = int(
            await conn.scalar(
                sa.select(sa.func.count())
                .select_from(circuit_breaker_incidents)
                .where(circuit_breaker_incidents.c.status == "open")
            )
            or 0
        )
    return CivilizationOverviewResponse(
        wealth_gini=concentration["wealth_gini"],
        top_balance_share=concentration["top_balance_share"],
        role_concentration=concentration["role_concentration"],
        pending_challenges=pending_challenges,
        pending_holdbacks=pending_holdbacks,
        slow_science_objectives=slow_science_objectives,
        degraded_scout_sources=degraded_scout_sources,
        open_breaker_incidents=open_breaker_incidents,
    )


@router.get("/capabilities", response_model=CivilizationCapabilityResponse)
async def civilization_capabilities(limit: int = Query(18, ge=1, le=100)):
    async with get_connection() as conn:
        rows = (
            await conn.execute(
                sa.select(
                    agent_personas.c.persona_id,
                    agent_personas.c.persona_name,
                    agent_personas.c.role_class,
                    agent_personas.c.reputation_score,
                    balance_expression(agent_personas.c.persona_id).label("credit_balance"),
                )
                .where(agent_personas.c.status == "active")
                .order_by(agent_personas.c.reputation_score.desc(), sa.text("credit_balance DESC"))
                .limit(limit)
            )
        ).fetchall()
        capability_map = await _capability_map(conn, [row.persona_id for row in rows])
    return CivilizationCapabilityResponse(
        items=[
            CivilizationCapabilityPersonaResponse(
                persona_id=row.persona_id,
                persona_name=row.persona_name,
                role_class=row.role_class,
                reputation_score=float(row.reputation_score or 0),
                credit_balance=float(row.credit_balance or 0),
                capability_scores=capability_map.get(str(row.persona_id), {}),
            )
            for row in rows
        ],
        count=len(rows),
    )


@router.get("/challenges", response_model=CivilizationChallengeListResponse)
async def civilization_challenges_view(limit: int = Query(20, ge=1, le=100)):
    async with get_connection() as conn:
        rows = (
            await conn.execute(
                sa.select(
                    civilization_challenge_records.c.challenge_id,
                    civilization_challenge_records.c.finding_id,
                    findings.c.title.label("finding_title"),
                    civilization_challenge_records.c.challenger_persona_id,
                    agent_personas.c.persona_name.label("challenger_name"),
                    civilization_challenge_records.c.flaw_type,
                    civilization_challenge_records.c.severity,
                    civilization_challenge_records.c.status,
                    civilization_challenge_records.c.summary,
                    civilization_challenge_records.c.opened_at,
                    civilization_challenge_records.c.resolution_due_at,
                    civilization_challenge_records.c.resolved_at,
                )
                .join(findings, findings.c.finding_id == civilization_challenge_records.c.finding_id)
                .join(agent_personas, agent_personas.c.persona_id == civilization_challenge_records.c.challenger_persona_id)
                .order_by(civilization_challenge_records.c.opened_at.desc())
                .limit(limit)
            )
        ).fetchall()
    return CivilizationChallengeListResponse(
        items=[CivilizationChallengeResponse(**row._mapping) for row in rows],
        count=len(rows),
    )


@router.get("/scout-health", response_model=ScoutSourceHealthListResponse)
async def civilization_scout_health():
    async with get_connection() as conn:
        rows = (
            await conn.execute(
                sa.select(scout_source_health)
                .order_by(
                    sa.case((scout_source_health.c.health_status == "critical", 0), (scout_source_health.c.health_status == "degraded", 1), else_=2),
                    scout_source_health.c.source_name.asc(),
                )
            )
        ).fetchall()
    return ScoutSourceHealthListResponse(
        items=[ScoutSourceHealthResponse(**row._mapping) for row in rows],
        count=len(rows),
    )


@router.get("/evolution", response_model=EvolutionHealthResponse)
async def civilization_evolution_health():
    async with get_connection() as conn:
        row = (
            await conn.execute(
                sa.select(evolution_metric_snapshots)
                .order_by(evolution_metric_snapshots.c.created_at.desc())
                .limit(1)
            )
        ).first()
    if row is None:
        return EvolutionHealthResponse(
            concentration_score=0.0,
            role_diversity_score=0.0,
            novelty_score=0.0,
            stagnation_score=0.0,
            explorer_pressure_score=0.0,
            exploration_pulse_triggered=False,
            metrics_json={},
        )
    return EvolutionHealthResponse(
        snapshot_id=row.snapshot_id,
        concentration_score=float(row.concentration_score or 0),
        role_diversity_score=float(row.role_diversity_score or 0),
        novelty_score=float(row.novelty_score or 0),
        stagnation_score=float(row.stagnation_score or 0),
        explorer_pressure_score=float(row.explorer_pressure_score or 0),
        exploration_pulse_triggered=bool(row.exploration_pulse_triggered),
        created_at=row.created_at,
        metrics_json=dict(row.metrics_json or {}),
    )


@router.get("/breakers", response_model=BreakerStatusResponse)
async def civilization_breakers(limit: int = Query(20, ge=1, le=100)):
    async with get_connection() as conn:
        rule_rows = (
            await conn.execute(sa.select(circuit_breaker_rules).order_by(circuit_breaker_rules.c.rule_code.asc()))
        ).fetchall()
        incident_rows = (
            await conn.execute(
                sa.select(
                    circuit_breaker_incidents.c.incident_id,
                    circuit_breaker_rules.c.rule_code,
                    circuit_breaker_incidents.c.mode,
                    circuit_breaker_incidents.c.severity,
                    circuit_breaker_incidents.c.status,
                    circuit_breaker_incidents.c.observed_value,
                    circuit_breaker_incidents.c.threshold_value,
                    circuit_breaker_incidents.c.payload,
                    circuit_breaker_incidents.c.created_at,
                    circuit_breaker_incidents.c.resolved_at,
                )
                .join(circuit_breaker_rules, circuit_breaker_rules.c.rule_id == circuit_breaker_incidents.c.rule_id)
                .order_by(circuit_breaker_incidents.c.created_at.desc())
                .limit(limit)
            )
        ).fetchall()
        open_count = int(
            await conn.scalar(
                sa.select(sa.func.count())
                .select_from(circuit_breaker_incidents)
                .where(circuit_breaker_incidents.c.status == "open")
            )
            or 0
        )
    return BreakerStatusResponse(
        rules=[
            BreakerRuleResponse(
                rule_id=row.rule_id,
                rule_code=row.rule_code,
                description=row.description,
                mode=row.mode,
                threshold_value=float(row.threshold_value or 0),
                window_minutes=row.window_minutes,
                action_type=row.action_type,
                enabled=bool(row.enabled),
                shadow_only=bool(row.shadow_only),
            )
            for row in rule_rows
        ],
        incidents=[
            BreakerIncidentResponse(
                incident_id=row.incident_id,
                rule_code=row.rule_code,
                mode=row.mode,
                severity=row.severity,
                status=row.status,
                observed_value=float(row.observed_value or 0),
                threshold_value=float(row.threshold_value or 0),
                payload=dict(row.payload or {}),
                created_at=row.created_at,
                resolved_at=row.resolved_at,
            )
            for row in incident_rows
        ],
        open_count=open_count,
    )
