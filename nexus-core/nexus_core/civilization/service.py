"""Shared civilization incentive and health services."""

from __future__ import annotations

from collections import Counter
from datetime import UTC, datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP
from typing import Any
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncConnection

from nexus_core.config import NexusSettings
from nexus_core.economy.ledger import get_all_balances, mint_credits
from nexus_core.models.civilization import (
    circuit_breaker_incidents,
    circuit_breaker_rules,
    civilization_bonds,
    civilization_challenges,
    civilization_quality_holdbacks,
    evolution_metric_snapshots,
    objective_incentive_profiles,
    persona_capability_scores,
    scout_source_health,
)
from nexus_core.models.market import market_instruments, market_orders, market_trades
from nexus_core.models.findings import findings
from nexus_core.models.instances import agent_instances
from nexus_core.models.objectives import objectives
from nexus_core.models.peer_reviews import peer_reviews
from nexus_core.models.personas import agent_personas
from nexus_core.utils.events import emit_event


CAPABILITIES = ("research", "review", "red_team", "scout", "governance", "market")
CAPABILITY_WEIGHTS = {
    "research": Decimal("1.20"),
    "review": Decimal("1.00"),
    "red_team": Decimal("1.00"),
    "scout": Decimal("0.90"),
    "governance": Decimal("0.80"),
    "market": Decimal("0.70"),
}
UNIT_QUANT = Decimal("0.001")
MONEY_QUANT = Decimal("0.01")
DEFAULT_BREAKER_RULES: tuple[dict[str, Any], ...] = (
    {
        "rule_code": "wealth_concentration",
        "description": "Top-balance share suggests capital is concentrating in too few personas.",
        "threshold_value": Decimal("0.38"),
        "window_minutes": 60,
        "action_type": "delay_payouts",
    },
    {
        "rule_code": "role_concentration",
        "description": "Too many active personas are clustered in one role class.",
        "threshold_value": Decimal("0.34"),
        "window_minutes": 60,
        "action_type": "pause_mutations",
    },
    {
        "rule_code": "review_overturn_rate",
        "description": "Validated findings are being challenged too often.",
        "threshold_value": Decimal("0.22"),
        "window_minutes": 240,
        "action_type": "increase_review_quorum",
    },
    {
        "rule_code": "mutation_regression_rate",
        "description": "Recent mutation candidates are regressing faster than they improve.",
        "threshold_value": Decimal("0.55"),
        "window_minutes": 240,
        "action_type": "throttle_mutation",
    },
    {
        "rule_code": "scout_coverage_failure",
        "description": "Scout source coverage is degraded or over-dependent on a single path.",
        "threshold_value": Decimal("1.00"),
        "window_minutes": 120,
        "action_type": "spawn_scout_capacity",
    },
    {
        "rule_code": "market_illiquidity",
        "description": "Exchange liquidity is too thin relative to listed instruments.",
        "threshold_value": Decimal("0.70"),
        "window_minutes": 180,
        "action_type": "freeze_instrument_issuance",
    },
    {
        "rule_code": "backlog_pressure",
        "description": "Review and objective backlog is accumulating faster than the system can close it.",
        "threshold_value": Decimal("12.00"),
        "window_minutes": 180,
        "action_type": "force_additional_review",
    },
)


def _now() -> datetime:
    return datetime.now(UTC)


def _money(value: Decimal | int | float | str | None) -> Decimal:
    if value is None:
        return Decimal("0.00")
    raw = value if isinstance(value, Decimal) else Decimal(str(value))
    return raw.quantize(MONEY_QUANT, rounding=ROUND_HALF_UP)


def _unit(value: Decimal | int | float | str | None) -> Decimal:
    if value is None:
        return Decimal("0.000")
    raw = value if isinstance(value, Decimal) else Decimal(str(value))
    return max(Decimal("0.000"), min(raw, Decimal("1.000"))).quantize(
        UNIT_QUANT,
        rounding=ROUND_HALF_UP,
    )


def capability_rollup_subquery() -> sa.Subquery:
    weighted = (
        persona_capability_scores.c.active_score * Decimal("0.65")
        + persona_capability_scores.c.persistent_score * Decimal("0.35")
    ) * sa.case(
        *[
            (persona_capability_scores.c.capability == capability, weight)
            for capability, weight in CAPABILITY_WEIGHTS.items()
        ],
        else_=Decimal("1.00"),
    )
    return (
        sa.select(
            persona_capability_scores.c.persona_id,
            (
                sa.func.sum(weighted)
                / sa.func.nullif(
                    sa.func.sum(
                        sa.case(
                            *[
                                (persona_capability_scores.c.capability == capability, weight)
                                for capability, weight in CAPABILITY_WEIGHTS.items()
                            ],
                            else_=Decimal("1.00"),
                        )
                    ),
                    0,
                )
            ).label("capability_score"),
            sa.func.avg(persona_capability_scores.c.active_score).label("avg_active_score"),
            sa.func.avg(persona_capability_scores.c.persistent_score).label("avg_persistent_score"),
        )
        .group_by(persona_capability_scores.c.persona_id)
        .subquery()
    )


async def ensure_civilization_state(conn: AsyncConnection) -> None:
    await ensure_capability_rows(conn)
    await ensure_objective_incentive_profiles(conn)
    await ensure_breaker_rules(conn)


async def ensure_capability_rows(conn: AsyncConnection) -> None:
    personas = (
        await conn.execute(
            sa.select(agent_personas.c.persona_id, agent_personas.c.reputation_score).where(
                agent_personas.c.status.in_(["active", "candidate"])
            )
        )
    ).fetchall()
    existing = {
        (row.persona_id, row.capability)
        for row in (
            await conn.execute(
                sa.select(persona_capability_scores.c.persona_id, persona_capability_scores.c.capability)
            )
        ).fetchall()
    }
    for persona in personas:
        baseline = _unit(getattr(persona, "reputation_score", None) or Decimal("0.500"))
        for capability in CAPABILITIES:
            if (persona.persona_id, capability) in existing:
                continue
            await conn.execute(
                persona_capability_scores.insert().values(
                    persona_id=persona.persona_id,
                    capability=capability,
                    active_score=baseline,
                    persistent_score=baseline,
                )
            )


async def ensure_objective_incentive_profiles(conn: AsyncConnection) -> None:
    existing_ids = {
        row.objective_id
        for row in (await conn.execute(sa.select(objective_incentive_profiles.c.objective_id))).fetchall()
    }
    rows = (
        await conn.execute(
            sa.select(
                objectives.c.objective_id,
                objectives.c.objective_type,
                objectives.c.impact_level,
                objectives.c.priority,
                objectives.c.output_type,
            )
        )
    ).fetchall()
    for row in rows:
        if row.objective_id in existing_ids:
            continue
        slow_science = (
            row.objective_type in {"research", "exploratory"}
            or (row.impact_level == "high-impact" and row.objective_type != "market")
        ) and row.output_type != "market_runtime"
        reserve_ratio = Decimal("0.20") if row.impact_level == "high-impact" else Decimal("0.00")
        challenge_window_minutes = 30 if row.impact_level == "high-impact" else 0
        uncertainty = "high" if slow_science and row.priority >= 7 else "standard"
        await conn.execute(
            objective_incentive_profiles.insert().values(
                objective_id=row.objective_id,
                slow_science_enabled=slow_science,
                uncertainty_level=uncertainty,
                rent_multiplier=Decimal("0.35") if slow_science else Decimal("1.00"),
                reserve_ratio=reserve_ratio,
                challenge_window_minutes=challenge_window_minutes,
                shadow_policy_json={
                    "priority": row.priority,
                    "impact_level": row.impact_level,
                    "objective_type": row.objective_type,
                },
            )
        )
        if slow_science:
            await emit_event(
                conn,
                "slow_objective_registered",
                entity_id=row.objective_id,
                entity_type="objective",
                payload={
                    "objective_id": str(row.objective_id),
                    "uncertainty_level": uncertainty,
                    "rent_multiplier": "0.35",
                    "reserve_ratio": str(reserve_ratio),
                },
            )


async def ensure_breaker_rules(conn: AsyncConnection) -> None:
    existing = {
        row.rule_code
        for row in (await conn.execute(sa.select(circuit_breaker_rules.c.rule_code))).fetchall()
    }
    for rule in DEFAULT_BREAKER_RULES:
        if rule["rule_code"] in existing:
            continue
        await conn.execute(circuit_breaker_rules.insert().values(**rule))


async def record_capability_signal(
    conn: AsyncConnection,
    *,
    persona_id: UUID,
    capability: str,
    outcome: str,
    magnitude: Decimal | float | int = 1,
) -> None:
    await ensure_capability_rows(conn)
    magnitude_dec = max(Decimal("0.25"), min(Decimal(str(magnitude)), Decimal("2.50")))
    active_delta = Decimal("0.000")
    persistent_delta = Decimal("0.000")
    success_inc = 0
    failure_inc = 0
    if outcome == "success":
        active_delta = Decimal("0.025")
        persistent_delta = Decimal("0.010")
        success_inc = 1
    elif outcome == "failure":
        active_delta = Decimal("-0.030")
        persistent_delta = Decimal("-0.012")
        failure_inc = 1
    elif outcome == "bonus":
        active_delta = Decimal("0.015")
        persistent_delta = Decimal("0.006")

    row = (
        await conn.execute(
            sa.select(persona_capability_scores).where(
                persona_capability_scores.c.persona_id == persona_id,
                persona_capability_scores.c.capability == capability,
            )
        )
    ).first()
    if row is None:
        return

    await conn.execute(
        persona_capability_scores.update()
        .where(persona_capability_scores.c.capability_score_id == row.capability_score_id)
        .values(
            active_score=_unit(Decimal(str(row.active_score)) + (active_delta * magnitude_dec)),
            persistent_score=_unit(Decimal(str(row.persistent_score)) + (persistent_delta * magnitude_dec)),
            success_count=persona_capability_scores.c.success_count + success_inc,
            failure_count=persona_capability_scores.c.failure_count + failure_inc,
            last_signal_at=sa.func.now(),
            updated_at=sa.func.now(),
        )
    )
    await recompute_persona_reputation(conn, persona_id)


async def recompute_persona_reputation(conn: AsyncConnection, persona_id: UUID) -> Decimal:
    rows = (
        await conn.execute(
            sa.select(
                persona_capability_scores.c.capability,
                persona_capability_scores.c.active_score,
                persona_capability_scores.c.persistent_score,
            ).where(persona_capability_scores.c.persona_id == persona_id)
        )
    ).fetchall()
    if not rows:
        return Decimal("0.500")

    total = Decimal("0.000")
    weight_total = Decimal("0.000")
    for row in rows:
        weight = CAPABILITY_WEIGHTS.get(row.capability, Decimal("1.00"))
        total += (
            Decimal(str(row.active_score)) * Decimal("0.65")
            + Decimal(str(row.persistent_score)) * Decimal("0.35")
        ) * weight
        weight_total += weight
    reputation = _unit(total / weight_total)
    await conn.execute(
        agent_personas.update()
        .where(agent_personas.c.persona_id == persona_id)
        .values(reputation_score=reputation)
    )
    return reputation


async def create_bond(
    conn: AsyncConnection,
    *,
    persona_id: UUID,
    bond_type: str,
    amount: Decimal,
    sponsor_persona_id: UUID | None = None,
    reference_objective_id: UUID | None = None,
    reference_finding_id: UUID | None = None,
    reference_contract_id: UUID | None = None,
    reference_order_id: UUID | None = None,
    release_after: datetime | None = None,
    memo: str | None = None,
    metadata_json: dict[str, Any] | None = None,
) -> UUID:
    result = await conn.execute(
        civilization_bonds.insert()
        .values(
            persona_id=persona_id,
            sponsor_persona_id=sponsor_persona_id,
            bond_type=bond_type,
            amount=_money(amount),
            reference_objective_id=reference_objective_id,
            reference_finding_id=reference_finding_id,
            reference_contract_id=reference_contract_id,
            reference_order_id=reference_order_id,
            release_after=release_after,
            memo=memo,
            metadata_json=metadata_json or {},
        )
        .returning(civilization_bonds.c.bond_id)
    )
    bond_id = result.scalar_one()
    await emit_event(
        conn,
        "bond_locked",
        entity_id=bond_id,
        entity_type="bond",
        payload={
            "bond_id": str(bond_id),
            "persona_id": str(persona_id),
            "bond_type": bond_type,
            "amount": str(_money(amount)),
        },
    )
    return bond_id


async def create_probation_bond_for_persona(
    conn: AsyncConnection,
    *,
    persona_id: UUID,
    sponsor_persona_id: UUID | None,
    probation_hours: int = 6,
) -> UUID:
    probation_until = _now() + timedelta(hours=probation_hours)
    await conn.execute(
        agent_personas.update()
        .where(agent_personas.c.persona_id == persona_id)
        .values(
            sponsor_persona_id=sponsor_persona_id,
            probation_until=probation_until,
        )
    )
    return await create_bond(
        conn,
        persona_id=persona_id,
        sponsor_persona_id=sponsor_persona_id,
        bond_type="sponsor",
        amount=Decimal("10.00"),
        release_after=probation_until,
        memo="New persona probation sponsorship bond",
        metadata_json={"probation_until": probation_until.isoformat()},
    )


async def release_due_probation_bonds(conn: AsyncConnection) -> int:
    rows = (
        await conn.execute(
            sa.select(civilization_bonds).where(
                civilization_bonds.c.bond_type == "sponsor",
                civilization_bonds.c.status == "locked",
                civilization_bonds.c.release_after.is_not(None),
                civilization_bonds.c.release_after <= _now(),
            )
        )
    ).fetchall()
    released = 0
    for row in rows:
        await conn.execute(
            agent_personas.update()
            .where(agent_personas.c.persona_id == row.persona_id)
            .values(probation_until=None)
        )
        await conn.execute(
            civilization_bonds.update()
            .where(civilization_bonds.c.bond_id == row.bond_id)
            .values(status="released", released_at=sa.func.now(), resolved_at=sa.func.now())
        )
        await emit_event(
            conn,
            "bond_released",
            entity_id=row.bond_id,
            entity_type="bond",
            payload={
                "bond_id": str(row.bond_id),
                "bond_type": row.bond_type,
                "persona_id": str(row.persona_id),
                "amount": str(_money(row.amount)),
            },
        )
        released += 1
    return released


async def create_quality_holdbacks(
    conn: AsyncConnection,
    *,
    finding_id: UUID,
    objective_id: UUID,
    author_persona_id: UUID,
    reviewer_persona_ids: list[UUID],
    total_bounty: Decimal,
    reserve_ratio: Decimal,
    release_after: datetime,
) -> int:
    reserve_total = _money(_money(total_bounty) * reserve_ratio)
    if reserve_total <= 0:
        return 0

    author_amount = _money(reserve_total * Decimal("0.70"))
    reviewer_pool = _money(reserve_total - author_amount)
    created = 0

    if author_amount > 0:
        bond_id = await create_bond(
            conn,
            persona_id=author_persona_id,
            bond_type="finding_publish",
            amount=author_amount,
            reference_objective_id=objective_id,
            reference_finding_id=finding_id,
            release_after=release_after,
            memo="Held-back publish reserve pending challenge window",
        )
        await conn.execute(
            civilization_quality_holdbacks.insert().values(
                finding_id=finding_id,
                persona_id=author_persona_id,
                holdback_type="finding_publish",
                amount=author_amount,
                reserve_ratio=reserve_ratio,
                release_after=release_after,
                metadata_json={"bond_id": str(bond_id)},
            )
        )
        created += 1

    if reviewer_persona_ids and reviewer_pool > 0:
        each = _money(reviewer_pool / Decimal(str(len(reviewer_persona_ids))))
        if each > 0:
            for reviewer_persona_id in reviewer_persona_ids:
                bond_id = await create_bond(
                    conn,
                    persona_id=reviewer_persona_id,
                    bond_type="review_vote",
                    amount=each,
                    reference_objective_id=objective_id,
                    reference_finding_id=finding_id,
                    release_after=release_after,
                    memo="Held-back reviewer reserve pending challenge window",
                )
                await conn.execute(
                    civilization_quality_holdbacks.insert().values(
                        finding_id=finding_id,
                        persona_id=reviewer_persona_id,
                        holdback_type="review_vote",
                        amount=each,
                        reserve_ratio=reserve_ratio,
                        release_after=release_after,
                        metadata_json={"bond_id": str(bond_id)},
                    )
                )
                created += 1

    return created


async def release_due_quality_holdbacks(conn: AsyncConnection) -> int:
    rows = (
        await conn.execute(
            sa.select(civilization_quality_holdbacks).where(
                civilization_quality_holdbacks.c.status == "pending",
                civilization_quality_holdbacks.c.release_after.is_not(None),
                civilization_quality_holdbacks.c.release_after <= _now(),
            )
        )
    ).fetchall()
    released = 0
    for row in rows:
        open_challenges = int(
            await conn.scalar(
                sa.select(sa.func.count())
                .select_from(civilization_challenges)
                .where(
                    civilization_challenges.c.finding_id == row.finding_id,
                    civilization_challenges.c.status.in_(["open", "appeal_open"]),
                )
            )
            or 0
        )
        if open_challenges:
            continue

        await mint_credits(
            conn,
            _money(row.amount),
            row.persona_id,
            reference_finding_id=row.finding_id,
            memo=f"Released quality reserve for {row.holdback_type}",
        )
        await conn.execute(
            civilization_quality_holdbacks.update()
            .where(civilization_quality_holdbacks.c.holdback_id == row.holdback_id)
            .values(status="released", released_at=sa.func.now())
        )
        metadata = dict(row.metadata_json or {})
        bond_id = metadata.get("bond_id")
        if bond_id:
            await conn.execute(
                civilization_bonds.update()
                .where(civilization_bonds.c.bond_id == UUID(str(bond_id)))
                .values(status="released", released_at=sa.func.now(), resolved_at=sa.func.now())
            )
            await emit_event(
                conn,
                "bond_released",
                entity_id=UUID(str(bond_id)),
                entity_type="bond",
                payload={
                    "bond_id": str(bond_id),
                    "bond_type": row.holdback_type,
                    "persona_id": str(row.persona_id),
                    "amount": str(_money(row.amount)),
                },
            )
        await record_capability_signal(
            conn,
            persona_id=row.persona_id,
            capability="research" if row.holdback_type == "finding_publish" else "review",
            outcome="success",
            magnitude=Decimal("1.15"),
        )
        released += 1
    return released


async def open_challenge_case(
    conn: AsyncConnection,
    *,
    finding_id: UUID,
    challenger_persona_id: UUID,
    flaw_type: str | None,
    severity: str | None,
    summary: str | None,
    resolution_due_minutes: int = 90,
) -> UUID:
    severity_bonus = {
        "minor": Decimal("3.00"),
        "major": Decimal("6.00"),
        "critical": Decimal("10.00"),
    }.get(severity or "major", Decimal("6.00"))
    release_after = _now() + timedelta(minutes=resolution_due_minutes)
    bond_id = await create_bond(
        conn,
        persona_id=challenger_persona_id,
        bond_type="challenge_appeal",
        amount=severity_bonus,
        reference_finding_id=finding_id,
        release_after=release_after,
        memo="Challenge window bond pending final resolution",
        metadata_json={"severity": severity or "major"},
    )
    result = await conn.execute(
        civilization_challenges.insert()
        .values(
            finding_id=finding_id,
            challenger_persona_id=challenger_persona_id,
            flaw_type=flaw_type,
            severity=severity,
            summary=summary,
            bond_id=bond_id,
            resolution_due_at=release_after,
            metadata_json={"opened_from_red_team": True},
        )
        .returning(civilization_challenges.c.challenge_id)
    )
    challenge_id = result.scalar_one()
    await emit_event(
        conn,
        "finding_challenged",
        entity_id=finding_id,
        entity_type="finding",
        payload={
            "challenge_id": str(challenge_id),
            "challenger_persona_id": str(challenger_persona_id),
            "severity": severity,
            "flaw_type": flaw_type,
        },
    )
    await emit_event(
        conn,
        "appeal_opened",
        entity_id=challenge_id,
        entity_type="challenge",
        payload={
            "challenge_id": str(challenge_id),
            "finding_id": str(finding_id),
            "resolution_due_at": release_after.isoformat(),
        },
    )
    return challenge_id


async def _reward_contrarian_reviewers(
    conn: AsyncConnection,
    *,
    finding_id: UUID,
    severity: str | None,
    challenge_id: UUID,
) -> int:
    reward = {
        "minor": Decimal("2.00"),
        "major": Decimal("4.00"),
        "critical": Decimal("6.00"),
    }.get(severity or "major", Decimal("4.00"))
    rows = (
        await conn.execute(
            sa.select(peer_reviews.c.reviewer_persona_id, peer_reviews.c.verdict).where(
                peer_reviews.c.finding_id == finding_id
            )
        )
    ).fetchall()
    rewarded = 0
    for row in rows:
        if row.verdict not in {"revise", "reject"}:
            continue
        await mint_credits(
            conn,
            reward,
            row.reviewer_persona_id,
            reference_finding_id=finding_id,
            memo="Contrarian review reward after challenge vindication",
        )
        await record_capability_signal(
            conn,
            persona_id=row.reviewer_persona_id,
            capability="review",
            outcome="success",
            magnitude=Decimal("1.30"),
        )
        await emit_event(
            conn,
            "contrarian_reward_paid",
            entity_id=row.reviewer_persona_id,
            entity_type="persona",
            payload={
                "finding_id": str(finding_id),
                "challenge_id": str(challenge_id),
                "amount": str(reward),
            },
        )
        rewarded += 1
    return rewarded


async def _resolve_holdbacks_for_challenge(
    conn: AsyncConnection,
    *,
    finding_id: UUID,
    challenge_id: UUID,
    severity: str | None,
) -> int:
    ratio = {
        "minor": Decimal("0.40"),
        "major": Decimal("0.75"),
        "critical": Decimal("1.00"),
    }.get(severity or "major", Decimal("0.75"))
    rows = (
        await conn.execute(
            sa.select(civilization_quality_holdbacks).where(
                civilization_quality_holdbacks.c.finding_id == finding_id,
                civilization_quality_holdbacks.c.status == "pending",
            )
        )
    ).fetchall()
    resolved = 0
    for row in rows:
        amount = _money(row.amount)
        slash_amount = _money(amount * ratio)
        release_amount = _money(amount - slash_amount)
        metadata = dict(row.metadata_json or {})
        bond_id = metadata.get("bond_id")
        values: dict[str, Any] = {
            "challenge_id": challenge_id,
            "slashed_at": sa.func.now(),
            "status": "slashed" if release_amount == 0 else "released",
        }
        if release_amount > 0:
            await mint_credits(
                conn,
                release_amount,
                row.persona_id,
                reference_finding_id=finding_id,
                memo="Residual quality reserve released after challenge resolution",
            )
            values["released_at"] = sa.func.now()
        await conn.execute(
            civilization_quality_holdbacks.update()
            .where(civilization_quality_holdbacks.c.holdback_id == row.holdback_id)
            .values(**values)
        )
        if bond_id:
            await conn.execute(
                civilization_bonds.update()
                .where(civilization_bonds.c.bond_id == UUID(str(bond_id)))
                .values(
                    status="slashed" if release_amount == 0 else "released",
                    slashed_amount=slash_amount,
                    released_at=sa.func.now() if release_amount > 0 else None,
                    resolved_at=sa.func.now(),
                )
            )
            await emit_event(
                conn,
                "bond_slashed",
                entity_id=UUID(str(bond_id)),
                entity_type="bond",
                payload={
                    "bond_id": str(bond_id),
                    "persona_id": str(row.persona_id),
                    "finding_id": str(finding_id),
                    "slashed_amount": str(slash_amount),
                    "released_amount": str(release_amount),
                },
            )
        await record_capability_signal(
            conn,
            persona_id=row.persona_id,
            capability="research" if row.holdback_type == "finding_publish" else "review",
            outcome="failure" if slash_amount > 0 else "success",
            magnitude=Decimal("1.40") if slash_amount > 0 else Decimal("0.80"),
        )
        resolved += 1
    return resolved


async def resolve_due_challenges(conn: AsyncConnection) -> int:
    rows = (
        await conn.execute(
            sa.select(civilization_challenges).where(
                civilization_challenges.c.status == "open",
                civilization_challenges.c.resolution_due_at.is_not(None),
                civilization_challenges.c.resolution_due_at <= _now(),
            )
        )
    ).fetchall()
    resolved = 0
    for row in rows:
        await _resolve_holdbacks_for_challenge(
            conn,
            finding_id=row.finding_id,
            challenge_id=row.challenge_id,
            severity=row.severity,
        )
        await _reward_contrarian_reviewers(
            conn,
            finding_id=row.finding_id,
            severity=row.severity,
            challenge_id=row.challenge_id,
        )
        if row.bond_id is not None:
            bond_row = (
                await conn.execute(
                    sa.select(civilization_bonds.c.amount, civilization_bonds.c.persona_id).where(
                        civilization_bonds.c.bond_id == row.bond_id
                    )
                )
            ).first()
            if bond_row is not None:
                await mint_credits(
                    conn,
                    _money(bond_row.amount),
                    bond_row.persona_id,
                    reference_finding_id=row.finding_id,
                    memo="Challenge bond released after vindicated finding challenge",
                )
                await conn.execute(
                    civilization_bonds.update()
                    .where(civilization_bonds.c.bond_id == row.bond_id)
                    .values(status="released", released_at=sa.func.now(), resolved_at=sa.func.now())
                )
                await emit_event(
                    conn,
                    "bond_released",
                    entity_id=row.bond_id,
                    entity_type="bond",
                    payload={
                        "bond_id": str(row.bond_id),
                        "bond_type": "challenge_appeal",
                        "persona_id": str(bond_row.persona_id),
                        "amount": str(_money(bond_row.amount)),
                    },
                )
        await conn.execute(
            civilization_challenges.update()
            .where(civilization_challenges.c.challenge_id == row.challenge_id)
            .values(
                status="resolved",
                resolution_kind="confirmed",
                resolution_notes="Challenge window elapsed without override; quality reserve resolved.",
                resolved_at=sa.func.now(),
            )
        )
        await record_capability_signal(
            conn,
            persona_id=row.challenger_persona_id,
            capability="red_team",
            outcome="success",
            magnitude=Decimal("1.40"),
        )
        author_persona_id = await conn.scalar(
            sa.select(agent_instances.c.persona_id)
            .join(findings, findings.c.instance_id == agent_instances.c.instance_id)
            .where(findings.c.finding_id == row.finding_id)
        )
        if author_persona_id is not None:
            await record_capability_signal(
                conn,
                persona_id=author_persona_id,
                capability="research",
                outcome="failure",
                magnitude=Decimal("1.10"),
            )
        resolved += 1
    return resolved


async def register_scout_source_run(
    conn: AsyncConnection,
    *,
    source_name: str,
    succeeded: bool,
    findings_ingested: int = 0,
    objectives_proposed: int = 0,
) -> None:
    row = (
        await conn.execute(
            sa.select(scout_source_health).where(scout_source_health.c.source_name == source_name)
        )
    ).first()
    now = _now()
    if row is None:
        await conn.execute(
            scout_source_health.insert().values(
                source_name=source_name,
                health_status="healthy" if succeeded else "degraded",
                consecutive_failures=0 if succeeded else 1,
                total_runs=1,
                total_successes=1 if succeeded else 0,
                findings_ingested=findings_ingested,
                objectives_proposed=objectives_proposed,
                last_run_at=now,
                last_success_at=now if succeeded else None,
            )
        )
        return

    failures = 0 if succeeded else row.consecutive_failures + 1
    status = "healthy" if succeeded else ("critical" if failures >= 3 else "degraded")
    await conn.execute(
        scout_source_health.update()
        .where(scout_source_health.c.source_name == source_name)
        .values(
            health_status=status,
            consecutive_failures=failures,
            total_runs=row.total_runs + 1,
            total_successes=row.total_successes + (1 if succeeded else 0),
            findings_ingested=row.findings_ingested + findings_ingested,
            objectives_proposed=row.objectives_proposed + objectives_proposed,
            last_run_at=now,
            last_success_at=now if succeeded else row.last_success_at,
            updated_at=sa.func.now(),
        )
    )
    if not succeeded and failures >= 2:
        await emit_event(
            conn,
            "scout_coverage_gap",
            entity_id=None,
            entity_type="scout_source",
            payload={
                "source_name": source_name,
                "consecutive_failures": failures,
                "health_status": status,
            },
        )


async def get_concentration_metrics(conn: AsyncConnection) -> dict[str, float]:
    balances = await get_all_balances(conn)
    active_balances = [float(max(balance, Decimal("0.00"))) for balance in balances.values()]
    total_balance = sum(active_balances)
    top_share = (max(active_balances) / total_balance) if total_balance and active_balances else 0.0

    gini = 0.0
    if active_balances:
        ordered = sorted(active_balances)
        total = sum(ordered)
        if total > 0:
            n = len(ordered)
            cumulative = 0.0
            for index, value in enumerate(ordered, start=1):
                cumulative += index * value
            gini = (2 * cumulative) / (n * total) - (n + 1) / n

    role_rows = (
        await conn.execute(
            sa.select(agent_personas.c.role_class).where(agent_personas.c.status == "active")
        )
    ).fetchall()
    role_counts = Counter(row.role_class for row in role_rows)
    role_concentration = (
        max(role_counts.values()) / max(sum(role_counts.values()), 1)
        if role_counts
        else 0.0
    )
    return {
        "top_balance_share": round(top_share, 4),
        "wealth_gini": round(gini, 4),
        "role_concentration": round(role_concentration, 4),
    }


async def capture_evolution_snapshot(
    conn: AsyncConnection,
    *,
    metrics_json: dict[str, Any],
    exploration_pulse_triggered: bool,
) -> UUID:
    result = await conn.execute(
        evolution_metric_snapshots.insert().values(
            concentration_score=Decimal(str(metrics_json.get("concentration_score", 0))),
            role_diversity_score=Decimal(str(metrics_json.get("role_diversity_score", 0))),
            novelty_score=Decimal(str(metrics_json.get("novelty_score", 0))),
            stagnation_score=Decimal(str(metrics_json.get("stagnation_score", 0))),
            explorer_pressure_score=Decimal(str(metrics_json.get("explorer_pressure_score", 0))),
            exploration_pulse_triggered=exploration_pulse_triggered,
            metrics_json=metrics_json,
        ).returning(evolution_metric_snapshots.c.snapshot_id)
    )
    snapshot_id = result.scalar_one()
    if exploration_pulse_triggered:
        await emit_event(
            conn,
            "exploration_pulse_triggered",
            entity_id=snapshot_id,
            entity_type="evolution_snapshot",
            payload=metrics_json,
        )
    return snapshot_id


async def _observe_breaker_value(
    conn: AsyncConnection,
    *,
    rule_code: str,
) -> tuple[Decimal, dict[str, Any]]:
    concentration = await get_concentration_metrics(conn)
    now = _now()
    if rule_code == "wealth_concentration":
        return Decimal(str(concentration["top_balance_share"])), concentration
    if rule_code == "role_concentration":
        return Decimal(str(concentration["role_concentration"])), concentration
    if rule_code == "review_overturn_rate":
        cutoff = now - timedelta(hours=24)
        challenged = int(
            await conn.scalar(
                sa.select(sa.func.count())
                .select_from(civilization_challenges)
                .where(civilization_challenges.c.opened_at >= cutoff)
            )
            or 0
        )
        validated = int(
            await conn.scalar(
                sa.select(sa.func.count())
                .select_from(civilization_quality_holdbacks)
                .where(civilization_quality_holdbacks.c.created_at >= cutoff)
            )
            or 0
        )
        return Decimal(str(challenged / max(validated, 1))), {
            "challenged": challenged,
            "validated_with_holdback": validated,
        }
    if rule_code == "mutation_regression_rate":
        cutoff = now - timedelta(hours=24)
        candidates = (
            await conn.execute(
                sa.select(agent_personas.c.status, agent_personas.c.deprecation_reason)
                .where(
                    agent_personas.c.generation > 0,
                    agent_personas.c.created_at >= cutoff,
                )
            )
        ).fetchall()
        total = len(candidates)
        regressed = sum(
            1
            for row in candidates
            if row.status == "deprecated" and (row.deprecation_reason or "").lower().startswith("candidate")
        )
        return Decimal(str(regressed / max(total, 1))), {"total_candidates": total, "regressed": regressed}
    if rule_code == "scout_coverage_failure":
        degraded = int(
            await conn.scalar(
                sa.select(sa.func.count())
                .select_from(scout_source_health)
                .where(scout_source_health.c.health_status.in_(["degraded", "critical"]))
            )
            or 0
        )
        return Decimal(str(degraded)), {"degraded_sources": degraded}
    if rule_code == "market_illiquidity":
        cutoff = now - timedelta(hours=3)
        instruments = int(await conn.scalar(sa.select(sa.func.count()).select_from(market_instruments)) or 0)
        trades = int(
            await conn.scalar(
                sa.select(sa.func.count())
                .select_from(market_trades)
                .where(market_trades.c.created_at >= cutoff)
            )
            or 0
        )
        open_orders = int(
            await conn.scalar(
                sa.select(sa.func.count())
                .select_from(market_orders)
                .where(market_orders.c.status == "open")
            )
            or 0
        )
        value = Decimal(str(1 - min((trades + open_orders) / max(instruments * 3, 1), 1.0)))
        return value, {"instrument_count": instruments, "recent_trades": trades, "open_orders": open_orders}
    if rule_code == "backlog_pressure":
        pending_reviews = int(
            await conn.scalar(sa.text("SELECT count(*) FROM findings WHERE status = 'pending_review'")) or 0
        )
        active_objectives = int(
            await conn.scalar(
                sa.select(sa.func.count())
                .select_from(objectives)
                .where(objectives.c.status.in_(["active", "approved", "revision_requested", "synthesizing"]))
            )
            or 0
        )
        return Decimal(str(pending_reviews + active_objectives)), {
            "pending_reviews": pending_reviews,
            "active_objectives": active_objectives,
        }
    return Decimal("0"), {}


async def evaluate_shadow_breakers(conn: AsyncConnection) -> int:
    rules = (
        await conn.execute(sa.select(circuit_breaker_rules).where(circuit_breaker_rules.c.enabled == sa.true()))
    ).fetchall()
    triggered = 0
    for rule in rules:
        observed_value, payload = await _observe_breaker_value(conn, rule_code=rule.rule_code)
        threshold = Decimal(str(rule.threshold_value))
        open_incident = (
            await conn.execute(
                sa.select(circuit_breaker_incidents).where(
                    circuit_breaker_incidents.c.rule_id == rule.rule_id,
                    circuit_breaker_incidents.c.status == "open",
                )
            )
        ).first()
        if observed_value >= threshold:
            if open_incident is None:
                severity = "critical" if observed_value >= threshold * Decimal("1.25") else "warning"
                result = await conn.execute(
                    circuit_breaker_incidents.insert().values(
                        rule_id=rule.rule_id,
                        mode=rule.mode,
                        severity=severity,
                        observed_value=observed_value,
                        threshold_value=threshold,
                        payload=payload,
                    ).returning(circuit_breaker_incidents.c.incident_id)
                )
                incident_id = result.scalar_one()
                await emit_event(
                    conn,
                    "circuit_breaker_triggered",
                    entity_id=incident_id,
                    entity_type="breaker_incident",
                    payload={
                        "rule_code": rule.rule_code,
                        "mode": rule.mode,
                        "severity": severity,
                        "observed_value": str(observed_value),
                        "threshold_value": str(threshold),
                        "action_type": rule.action_type,
                    },
                )
                triggered += 1
        elif open_incident is not None:
            await conn.execute(
                circuit_breaker_incidents.update()
                .where(circuit_breaker_incidents.c.incident_id == open_incident.incident_id)
                .values(status="resolved", resolved_at=sa.func.now())
            )
    return triggered


async def run_civilization_shadow_cycle(
    conn: AsyncConnection,
    settings: NexusSettings | None = None,
) -> dict[str, int]:
    await ensure_civilization_state(conn)
    released_holdbacks = await release_due_quality_holdbacks(conn)
    resolved_challenges = await resolve_due_challenges(conn)
    released_probation = await release_due_probation_bonds(conn)
    breaker_incidents = await evaluate_shadow_breakers(conn)
    return {
        "released_holdbacks": released_holdbacks,
        "resolved_challenges": resolved_challenges,
        "released_probation_bonds": released_probation,
        "breaker_incidents": breaker_incidents,
    }
