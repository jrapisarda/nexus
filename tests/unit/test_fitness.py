from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest

from nexus_core.economy.fitness import PersonaFitnessSnapshot, _build_snapshots, calculate_fitness


@pytest.mark.asyncio
async def test_calculate_fitness_uses_ranked_snapshot_score():
    persona_id = uuid4()

    with patch(
        "nexus_core.economy.fitness.rank_personas_with_snapshots",
        new=AsyncMock(
            return_value=[
                PersonaFitnessSnapshot(
                    persona_id=persona_id,
                    role_class="researcher",
                    generation=0,
                    capability_score=0.81,
                    balance_score=0.24,
                    diversity_score=0.55,
                    novelty_score=0.35,
                    recovery_score=0.25,
                    composite_score=0.6234,
                    experimental_niche=False,
                    probationary=False,
                )
            ]
        ),
    ):
        fitness = await calculate_fitness(AsyncMock(), persona_id)

    assert fitness == pytest.approx(0.6234)


def test_build_snapshots_clamps_negative_balance_and_marks_probation():
    now = datetime.now(UTC)
    snapshots = _build_snapshots(
        [
            SimpleNamespace(
                persona_id=uuid4(),
                role_class="scout",
                generation=1,
                capability_score=Decimal("0.700"),
                credit_balance=Decimal("-10.00"),
                created_at=now,
                probation_until=now + timedelta(hours=1),
            )
        ]
    )

    assert len(snapshots) == 1
    snapshot = snapshots[0]
    assert snapshot.balance_score == 0.0
    assert snapshot.probationary is True
    assert snapshot.experimental_niche is True
    assert snapshot.composite_score > 0.0
