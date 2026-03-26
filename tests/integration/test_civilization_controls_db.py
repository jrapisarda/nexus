from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
import sqlalchemy as sa

from nexus_core.civilization.service import (
    CAPABILITIES,
    create_quality_holdbacks,
    ensure_civilization_state,
    release_due_quality_holdbacks,
)
from nexus_core.economy.ledger import get_balance
from nexus_core.models.civilization import (
    circuit_breaker_rules,
    civilization_bonds,
    civilization_quality_holdbacks,
    persona_capability_scores,
)
from nexus_core.models.findings import findings
from nexus_core.models.instances import agent_instances
from nexus_core.models.objectives import objectives
from nexus_core.models.personas import agent_personas


async def _seed_persona(conn, *, name: str, role_class: str, reputation: str):
    return (
        await conn.execute(
            agent_personas.insert()
            .values(
                persona_name=name,
                role_class=role_class,
                system_prompt_template=f"You are {name}.",
                status="active",
                reputation_score=Decimal(reputation),
            )
            .returning(agent_personas.c.persona_id)
        )
    ).scalar_one()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_ensure_civilization_state_bootstraps_capabilities_from_reputation(clean_database):
    async with clean_database.begin() as conn:
        persona_id = await _seed_persona(
            conn,
            name="Capability Bootstrapper",
            role_class="researcher",
            reputation="0.820",
        )

        await ensure_civilization_state(conn)

        capability_rows = (
            await conn.execute(
                sa.select(
                    persona_capability_scores.c.capability,
                    persona_capability_scores.c.active_score,
                    persona_capability_scores.c.persistent_score,
                ).where(persona_capability_scores.c.persona_id == persona_id)
            )
        ).fetchall()
        breaker_count = int(
            await conn.scalar(sa.select(sa.func.count()).select_from(circuit_breaker_rules)) or 0
        )

    assert len(capability_rows) == len(CAPABILITIES)
    assert {row.capability for row in capability_rows} == set(CAPABILITIES)
    assert all(Decimal(str(row.active_score)) == Decimal("0.820") for row in capability_rows)
    assert all(Decimal(str(row.persistent_score)) == Decimal("0.820") for row in capability_rows)
    assert breaker_count >= 1


@pytest.mark.integration
@pytest.mark.asyncio
async def test_quality_holdbacks_release_to_bonds_and_reputation(clean_database):
    async with clean_database.begin() as conn:
        author_id = await _seed_persona(
            conn,
            name="Holdback Author",
            role_class="researcher",
            reputation="0.700",
        )
        reviewer_id = await _seed_persona(
            conn,
            name="Holdback Reviewer",
            role_class="critic",
            reputation="0.650",
        )
        objective_id = (
            await conn.execute(
                objectives.insert()
                .values(
                    objective_id=uuid4(),
                    title="Delayed quality settlement objective",
                    description="Validate holdback release after the challenge window.",
                    objective_type="research",
                    impact_level="high-impact",
                    priority=8,
                    status="active",
                    proposed_by_type="human",
                    approved_by_type="system",
                    output_type="report",
                )
                .returning(objectives.c.objective_id)
            )
        ).scalar_one()
        instance_id = (
            await conn.execute(
                agent_instances.insert()
                .values(
                    persona_id=author_id,
                    objective_id=objective_id,
                    input_prompt="Produce a finding.",
                    output_content="Structured finding output.",
                    status="completed",
                    spawn_reason="test",
                    completed_at=sa.func.now(),
                )
                .returning(agent_instances.c.instance_id)
            )
        ).scalar_one()
        finding_id = (
            await conn.execute(
                findings.insert()
                .values(
                    objective_id=objective_id,
                    instance_id=instance_id,
                    finding_type="research",
                    title="Held-back finding",
                    content="Finding content",
                    structured_data={"confidence": 0.8, "citations": []},
                    status="validated",
                    impact_level="high-impact",
                )
                .returning(findings.c.finding_id)
            )
        ).scalar_one()

        await ensure_civilization_state(conn)
        created = await create_quality_holdbacks(
            conn,
            finding_id=finding_id,
            objective_id=objective_id,
            author_persona_id=author_id,
            reviewer_persona_ids=[reviewer_id],
            total_bounty=Decimal("100.00"),
            reserve_ratio=Decimal("0.20"),
            release_after=datetime.now(UTC) - timedelta(minutes=1),
        )
        released = await release_due_quality_holdbacks(conn)

        holdback_rows = (
            await conn.execute(
                sa.select(
                    civilization_quality_holdbacks.c.persona_id,
                    civilization_quality_holdbacks.c.amount,
                    civilization_quality_holdbacks.c.status,
                ).where(civilization_quality_holdbacks.c.finding_id == finding_id)
            )
        ).fetchall()
        bond_rows = (
            await conn.execute(
                sa.select(civilization_bonds.c.status).where(
                    civilization_bonds.c.reference_finding_id == finding_id
                )
            )
        ).fetchall()
        author_balance = await get_balance(conn, author_id)
        reviewer_balance = await get_balance(conn, reviewer_id)
        author_reputation = await conn.scalar(
            sa.select(agent_personas.c.reputation_score).where(agent_personas.c.persona_id == author_id)
        )
        reviewer_reputation = await conn.scalar(
            sa.select(agent_personas.c.reputation_score).where(agent_personas.c.persona_id == reviewer_id)
        )

    assert created == 2
    assert released == 2
    assert {(row.persona_id, Decimal(str(row.amount)), row.status) for row in holdback_rows} == {
        (author_id, Decimal("14.00"), "released"),
        (reviewer_id, Decimal("6.00"), "released"),
    }
    assert all(row.status == "released" for row in bond_rows)
    assert author_balance == Decimal("14.00")
    assert reviewer_balance == Decimal("6.00")
    assert Decimal(str(author_reputation)) > Decimal("0.700")
    assert Decimal(str(reviewer_reputation)) > Decimal("0.650")
