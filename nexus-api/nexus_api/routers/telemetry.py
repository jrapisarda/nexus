"""Telemetry endpoints for the NEXUS Observatory API."""

from __future__ import annotations

from decimal import Decimal

import sqlalchemy as sa
from fastapi import APIRouter

from nexus_core.config import get_settings
from nexus_core.database import get_connection
from nexus_core.models.telemetry import agent_telemetry
from nexus_core.models.personas import agent_personas
from nexus_core.models.objectives import objectives

from nexus_api.schemas import TelemetryCostResponse, TelemetryPerformanceResponse

router = APIRouter(prefix="/api/telemetry", tags=["telemetry"])


@router.get("/cost", response_model=TelemetryCostResponse)
async def telemetry_cost():
    """Cost report: total spend, per-agent breakdown, per-objective breakdown."""
    settings = get_settings()
    budget_ceiling = float(settings.BUDGET_CEILING_USD)

    async with get_connection() as conn:
        # Total spend
        total_q = await conn.execute(
            sa.select(
                sa.func.coalesce(sa.func.sum(agent_telemetry.c.cost_total_usd), Decimal("0"))
            )
        )
        total_spend = float(total_q.scalar_one())

        # Per-agent spend
        per_agent_q = await conn.execute(
            sa.select(
                agent_telemetry.c.persona_id,
                agent_personas.c.persona_name,
                sa.func.sum(agent_telemetry.c.cost_total_usd).label("total_cost"),
                sa.func.count().label("call_count"),
            )
            .join(agent_personas, agent_telemetry.c.persona_id == agent_personas.c.persona_id)
            .group_by(agent_telemetry.c.persona_id, agent_personas.c.persona_name)
            .order_by(sa.desc("total_cost"))
        )
        per_agent = [
            {
                "persona_id": str(row.persona_id),
                "persona_name": row.persona_name,
                "total_cost": float(row.total_cost),
                "call_count": row.call_count,
            }
            for row in per_agent_q
        ]

        # Per-objective spend
        per_obj_q = await conn.execute(
            sa.select(
                agent_telemetry.c.objective_id,
                objectives.c.title.label("objective_title"),
                sa.func.sum(agent_telemetry.c.cost_total_usd).label("total_cost"),
                sa.func.count().label("call_count"),
            )
            .join(objectives, agent_telemetry.c.objective_id == objectives.c.objective_id)
            .group_by(agent_telemetry.c.objective_id, objectives.c.title)
            .order_by(sa.desc("total_cost"))
        )
        per_objective = [
            {
                "objective_id": str(row.objective_id),
                "objective_title": row.objective_title,
                "total_cost": float(row.total_cost),
                "call_count": row.call_count,
            }
            for row in per_obj_q
        ]

    return TelemetryCostResponse(
        total_spend_usd=total_spend,
        per_agent=per_agent,
        per_objective=per_objective,
        budget_ceiling_usd=budget_ceiling,
        budget_remaining_usd=budget_ceiling - total_spend,
    )


@router.get("/performance", response_model=TelemetryPerformanceResponse)
async def telemetry_performance():
    """Performance metrics: total calls, success rate, avg latency, error breakdown."""
    async with get_connection() as conn:
        # Total calls
        total_q = await conn.execute(
            sa.select(sa.func.count()).select_from(agent_telemetry)
        )
        total_calls = total_q.scalar_one()

        # Success count
        success_q = await conn.execute(
            sa.select(sa.func.count()).select_from(agent_telemetry)
            .where(agent_telemetry.c.success.is_(True))
        )
        success_count = success_q.scalar_one()

        success_rate = success_count / max(total_calls, 1)

        # Average latency
        latency_q = await conn.execute(
            sa.select(sa.func.avg(agent_telemetry.c.latency_ms))
        )
        avg_latency = latency_q.scalar_one()

        # Error breakdown
        error_q = await conn.execute(
            sa.select(
                agent_telemetry.c.error_category,
                sa.func.count().label("count"),
            )
            .where(agent_telemetry.c.error_category.isnot(None))
            .group_by(agent_telemetry.c.error_category)
        )
        error_breakdown = {row.error_category: row.count for row in error_q}

    return TelemetryPerformanceResponse(
        total_calls=total_calls,
        success_rate=round(success_rate, 4),
        avg_latency_ms=round(float(avg_latency), 1) if avg_latency else 0.0,
        error_breakdown=error_breakdown,
    )
