"""Composite persona fitness scoring for NEXUS."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID

import sqlalchemy as sa

from nexus_core.civilization.service import capability_rollup_subquery
from nexus_core.economy.ledger import balance_expression


FITNESS_FULL_BALANCE = Decimal("200.00")
NICHE_PROTECTION_WINDOW = timedelta(hours=8)


@dataclass
class PersonaFitnessSnapshot:
    persona_id: UUID
    role_class: str
    generation: int
    capability_score: float
    balance_score: float
    diversity_score: float
    novelty_score: float
    recovery_score: float
    composite_score: float
    experimental_niche: bool
    probationary: bool


def _scarcity_score(role_count: int) -> float:
    if role_count <= 1:
        return 1.0
    if role_count == 2:
        return 0.9
    if role_count == 3:
        return 0.75
    if role_count == 4:
        return 0.55
    return 0.4


def _build_snapshots(rows) -> list[PersonaFitnessSnapshot]:
    now = datetime.now(UTC)
    role_counts: dict[str, int] = {}
    for row in rows:
        role_counts[row.role_class] = role_counts.get(row.role_class, 0) + 1

    snapshots: list[PersonaFitnessSnapshot] = []
    for row in rows:
        capability = float(row.capability_score or 0.5)
        balance = Decimal(str(row.credit_balance or 0))
        balance_score = max(0.0, min(float(balance / FITNESS_FULL_BALANCE), 1.0))
        diversity_score = _scarcity_score(role_counts.get(row.role_class, 1))
        probationary = row.probation_until is not None and row.probation_until >= now
        recent_mutant = (
            row.generation > 0
            and row.created_at is not None
            and row.created_at >= now - NICHE_PROTECTION_WINDOW
        )
        novelty_score = 0.9 if recent_mutant else (0.65 if row.generation > 0 else 0.35)
        recovery_score = 0.8 if balance_score < 0.15 and capability >= 0.55 else 0.25
        experimental_niche = probationary or recent_mutant
        composite = min(
            1.0,
            (
                capability * 0.48
                + balance_score * 0.14
                + diversity_score * 0.18
                + novelty_score * 0.10
                + recovery_score * 0.10
                + (0.03 if experimental_niche else 0.0)
            ),
        )
        snapshots.append(
            PersonaFitnessSnapshot(
                persona_id=row.persona_id,
                role_class=row.role_class,
                generation=row.generation or 0,
                capability_score=round(capability, 4),
                balance_score=round(balance_score, 4),
                diversity_score=round(diversity_score, 4),
                novelty_score=round(novelty_score, 4),
                recovery_score=round(recovery_score, 4),
                composite_score=round(composite, 4),
                experimental_niche=experimental_niche,
                probationary=probationary,
            )
        )
    snapshots.sort(key=lambda item: item.composite_score, reverse=True)
    return snapshots


async def rank_personas_with_snapshots(
    conn,
    status: str = "active",
) -> list[PersonaFitnessSnapshot]:
    """Rank personas using capability, liquidity, scarcity, novelty, and recovery."""
    from nexus_core.models.personas import agent_personas

    capability_rollup = capability_rollup_subquery()
    result = await conn.execute(
        sa.select(
            agent_personas.c.persona_id,
            agent_personas.c.role_class,
            agent_personas.c.generation,
            agent_personas.c.created_at,
            agent_personas.c.probation_until,
            balance_expression(agent_personas.c.persona_id).label("credit_balance"),
            capability_rollup.c.capability_score,
        )
        .select_from(
            agent_personas.outerjoin(
                capability_rollup,
                capability_rollup.c.persona_id == agent_personas.c.persona_id,
            )
        )
        .where(
            agent_personas.c.status == status,
            agent_personas.c.role_class != "system",
        )
    )
    return _build_snapshots(result.fetchall())


async def calculate_fitness(conn, persona_id: UUID) -> float:
    """Calculate composite fitness for a single persona."""
    rankings = await rank_personas_with_snapshots(conn)
    for row in rankings:
        if row.persona_id == persona_id:
            return row.composite_score
    return 0.0


async def rank_personas(
    conn,
    status: str = "active",
) -> list[tuple[UUID, float]]:
    """Rank personas by composite civilization fitness."""
    return [
        (row.persona_id, row.composite_score)
        for row in await rank_personas_with_snapshots(conn, status)
    ]


async def get_bottom_performers(
    conn,
    count: int = 5,
    status: str = "active",
) -> list[tuple[UUID, float]]:
    rankings = await rank_personas(conn, status)
    return rankings[-count:] if len(rankings) >= count else rankings


async def get_top_performers(
    conn,
    count: int = 5,
    status: str = "active",
) -> list[tuple[UUID, float]]:
    rankings = await rank_personas(conn, status)
    return rankings[:count]
