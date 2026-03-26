"""Population pruning and full evolution cycle for NEXUS."""

from __future__ import annotations

from decimal import Decimal
from uuid import UUID

import sqlalchemy as sa
import structlog

from nexus_core.civilization.service import capture_evolution_snapshot, get_concentration_metrics
from nexus_core.config import NexusSettings
from nexus_core.economy.diversity import check_role_class_minimums
from nexus_core.economy.fitness import PersonaFitnessSnapshot, rank_personas_with_snapshots
from nexus_core.economy.ledger import mint_credits
from nexus_core.evolution.evaluator import evaluate_candidate
from nexus_core.evolution.mutator import generate_mutation
from nexus_core.llm.client import KimiClient
from nexus_core.models.personas import agent_personas
from nexus_core.utils.events import emit_event

logger = structlog.get_logger(__name__)


def _unique_append(
    rows: list[PersonaFitnessSnapshot],
    selected: list[PersonaFitnessSnapshot],
    seen: set[UUID],
    key,
) -> None:
    if not rows:
        return
    candidate = max(rows, key=key)
    if candidate.persona_id in seen:
        return
    selected.append(candidate)
    seen.add(candidate.persona_id)


def _select_breeder_candidates(
    snapshots: list[PersonaFitnessSnapshot],
    *,
    exploration_pulse: bool,
) -> list[PersonaFitnessSnapshot]:
    selected: list[PersonaFitnessSnapshot] = []
    seen: set[UUID] = set()

    _unique_append(snapshots, selected, seen, key=lambda row: row.composite_score)
    _unique_append(snapshots, selected, seen, key=lambda row: row.capability_score)
    _unique_append(
        [row for row in snapshots if row.experimental_niche],
        selected,
        seen,
        key=lambda row: row.novelty_score,
    )
    _unique_append(snapshots, selected, seen, key=lambda row: row.diversity_score)
    _unique_append(
        [row for row in snapshots if row.recovery_score >= 0.75],
        selected,
        seen,
        key=lambda row: row.recovery_score + row.capability_score,
    )

    if exploration_pulse:
        _unique_append(
            [row for row in snapshots if row.generation == 0],
            selected,
            seen,
            key=lambda row: row.diversity_score + row.capability_score,
        )

    return selected[: (5 if exploration_pulse else 3)]


def _compute_evolution_metrics(
    snapshots: list[PersonaFitnessSnapshot],
    concentration: dict[str, float],
    exploration_pulse: bool,
) -> dict[str, float]:
    if not snapshots:
        return {
            "concentration_score": 0.0,
            "role_diversity_score": 0.0,
            "novelty_score": 0.0,
            "stagnation_score": 0.0,
            "explorer_pressure_score": 0.0,
        }
    avg_diversity = sum(row.diversity_score for row in snapshots) / len(snapshots)
    avg_novelty = sum(row.novelty_score for row in snapshots) / len(snapshots)
    avg_recovery = sum(row.recovery_score for row in snapshots) / len(snapshots)
    avg_capability = sum(row.capability_score for row in snapshots) / len(snapshots)
    return {
        "concentration_score": round(concentration["top_balance_share"], 4),
        "role_diversity_score": round(avg_diversity, 4),
        "novelty_score": round(avg_novelty, 4),
        "stagnation_score": round(max(0.0, 1 - avg_capability), 4),
        "explorer_pressure_score": round(avg_recovery + (0.1 if exploration_pulse else 0.0), 4),
    }


async def prune_population(
    conn,
    max_active: int = 20,
    min_per_class: int = 2,
    protected_persona_ids: set[UUID] | None = None,
) -> list[UUID]:
    """Prune the persona population, respecting role minimums and protected niches."""
    snapshots = await rank_personas_with_snapshots(conn)
    if len(snapshots) <= max_active:
        return []

    below_minimum = await check_role_class_minimums(conn, min_per_class)
    protected_ids = protected_persona_ids or {
        snapshot.persona_id for snapshot in snapshots if snapshot.experimental_niche
    }

    deprecated_ids: list[UUID] = []
    excess = len(snapshots) - max_active
    for snapshot in reversed(snapshots):
        if excess <= 0:
            break
        if snapshot.persona_id in protected_ids:
            continue

        role_class = snapshot.role_class
        if role_class in below_minimum:
            continue

        remaining = int(
            await conn.scalar(
                sa.select(sa.func.count())
                .select_from(agent_personas)
                .where(
                    agent_personas.c.role_class == role_class,
                    agent_personas.c.status == "active",
                    agent_personas.c.persona_id.notin_(deprecated_ids),
                )
            )
            or 0
        )
        if remaining <= min_per_class:
            continue

        await conn.execute(
            agent_personas.update()
            .where(agent_personas.c.persona_id == snapshot.persona_id)
            .values(
                status="deprecated",
                deprecated_at=sa.func.now(),
                deprecation_reason=(
                    "Pruned: repeated low composite contribution across quality, scarcity, and novelty metrics "
                    f"(fitness {snapshot.composite_score:.4f})"
                ),
            )
        )
        deprecated_ids.append(snapshot.persona_id)
        excess -= 1
        await emit_event(
            conn,
            "persona_deprecated",
            entity_id=snapshot.persona_id,
            entity_type="persona",
            payload={"fitness": snapshot.composite_score, "reason": "evolutionary_pruning"},
        )

    if deprecated_ids:
        logger.info("population_pruned", deprecated=len(deprecated_ids))
    return deprecated_ids


async def run_evolution_cycle(
    engine,
    kimi_client: KimiClient,
    settings: NexusSettings,
) -> None:
    """Run a full evolution cycle with multi-front breeder selection."""
    logger.info("evolution_cycle_starting")

    async with engine.begin() as conn:
        snapshots = await rank_personas_with_snapshots(conn)
        if not snapshots:
            logger.info("evolution_skipped_no_personas")
            return

        concentration = await get_concentration_metrics(conn)
        avg_diversity = sum(row.diversity_score for row in snapshots) / len(snapshots)
        avg_novelty = sum(row.novelty_score for row in snapshots) / len(snapshots)
        exploration_pulse = (
            concentration["top_balance_share"] >= 0.38
            or avg_diversity <= 0.58
            or avg_novelty <= 0.45
        )
        breeders = _select_breeder_candidates(
            snapshots,
            exploration_pulse=exploration_pulse,
        )

        mutations_created = 0
        donor_rows = [row for row in snapshots if row.persona_id not in {b.persona_id for b in breeders}]
        for index, breeder in enumerate(breeders):
            donor = donor_rows[index % len(donor_rows)] if exploration_pulse and donor_rows else None
            try:
                mutation = await generate_mutation(
                    conn,
                    kimi_client,
                    breeder.persona_id,
                    donor_persona_id=donor.persona_id if donor else None,
                )
                if mutation is None:
                    continue

                parent_row = (
                    await conn.execute(
                        sa.select(agent_personas.c.role_class, agent_personas.c.generation).where(
                            agent_personas.c.persona_id == breeder.persona_id
                        )
                    )
                ).first()
                if parent_row is None:
                    continue

                result = await conn.execute(
                    agent_personas.insert()
                    .values(
                        persona_name=f"Mutant of {breeder.persona_id}",
                        role_class=parent_row.role_class,
                        system_prompt_template=mutation.mutated_prompt,
                        parent_persona_id=breeder.persona_id,
                        sponsor_persona_id=donor.persona_id if donor else None,
                        generation=parent_row.generation + 1,
                        status="candidate",
                        mutation_diff={
                            "type": mutation.mutation_type,
                            "changes": mutation.changes_description,
                            "expected_improvement": mutation.expected_improvement,
                            "exploration_pulse": exploration_pulse,
                            "horizontal_transfer_from": str(donor.persona_id) if donor else None,
                        },
                    )
                    .returning(agent_personas.c.persona_id)
                )
                candidate_id = result.scalar_one()
                await mint_credits(
                    conn,
                    Decimal("50.00"),
                    candidate_id,
                    memo="Initial candidate persona balance",
                )

                eval_result = await evaluate_candidate(conn, kimi_client, candidate_id, breeder.persona_id)
                if eval_result.passed:
                    await conn.execute(
                        agent_personas.update()
                        .where(agent_personas.c.persona_id == candidate_id)
                        .values(status="active")
                    )
                    mutations_created += 1
                    logger.info("mutation_activated", candidate=str(candidate_id), parent=str(breeder.persona_id))
                else:
                    await conn.execute(
                        agent_personas.update()
                        .where(agent_personas.c.persona_id == candidate_id)
                        .values(status="deprecated", deprecation_reason=eval_result.reason)
                    )
                    logger.info("mutation_rejected", candidate=str(candidate_id), reason=eval_result.reason)
            except Exception as exc:  # pragma: no cover - defensive logging
                logger.error("mutation_failed", persona_id=str(breeder.persona_id), error=str(exc))

        deprecated = await prune_population(
            conn,
            settings.MAX_ACTIVE_PERSONAS,
            settings.MIN_PERSONAS_PER_ROLE_CLASS,
            protected_persona_ids={row.persona_id for row in snapshots if row.experimental_niche},
        )
        metrics = _compute_evolution_metrics(snapshots, concentration, exploration_pulse)
        await capture_evolution_snapshot(
            conn,
            metrics_json=metrics,
            exploration_pulse_triggered=exploration_pulse,
        )

    logger.info(
        "evolution_cycle_complete",
        mutations_created=mutations_created,
        personas_pruned=len(deprecated) if deprecated else 0,
        exploration_pulse=exploration_pulse,
    )
