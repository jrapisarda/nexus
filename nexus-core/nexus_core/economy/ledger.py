"""Append-only economy ledger for NEXUS credit system."""

from decimal import Decimal
from uuid import UUID
from typing import Optional
import sqlalchemy as sa
from nexus_core.models.civilization import objective_incentive_profiles
from nexus_core.models.economy import economy_ledger
from nexus_core.models.instances import agent_instances
from nexus_core.utils.events import emit_event
import structlog

logger = structlog.get_logger(__name__)


def balance_expression(persona_id_column) -> sa.ColumnElement:
    """SQL expression for the current ledger-derived balance of a persona."""
    credits = (
        sa.select(sa.func.coalesce(sa.func.sum(economy_ledger.c.amount), Decimal("0")))
        .where(economy_ledger.c.to_persona_id == persona_id_column)
        .scalar_subquery()
    )
    debits = (
        sa.select(sa.func.coalesce(sa.func.sum(economy_ledger.c.amount), Decimal("0")))
        .where(economy_ledger.c.from_persona_id == persona_id_column)
        .scalar_subquery()
    )
    return sa.type_coerce(credits - debits, sa.Numeric(12, 2))


async def mint_credits(
    conn,
    amount: Decimal,
    to_persona_id: UUID,
    reference_objective_id: UUID | None = None,
    reference_finding_id: UUID | None = None,
    memo: str = "Credit minting",
) -> UUID:
    """Mint new credits (inflationary). from_persona_id is NULL (system mint)."""
    result = await conn.execute(
        economy_ledger.insert().values(
            from_persona_id=None,
            to_persona_id=to_persona_id,
            amount=amount,
            transaction_type="mint",
            reference_objective_id=reference_objective_id,
            reference_finding_id=reference_finding_id,
            memo=memo,
        ).returning(economy_ledger.c.transaction_id)
    )
    tx_id = result.scalar_one()
    await emit_event(conn, "economy_mint", entity_id=to_persona_id, entity_type="persona", payload={"amount": str(amount), "transaction_id": str(tx_id)})
    return tx_id


async def distribute_bounty(
    conn,
    objective_id: UUID,
    finding_id: UUID,
    completer_persona_id: UUID,
    reviewer_persona_ids: list[UUID],
    red_team_persona_ids: list[UUID],
    total_bounty: Decimal,
) -> list[UUID]:
    """Distribute bounty credits with a quality-adjusted 70/30 split.

    Red Team compensation is handled on validated flaw discovery rather than automatic participation.
    The ``red_team_persona_ids`` argument is retained for backward compatibility.
    """
    tx_ids = []

    # 70% to completer
    completer_amount = total_bounty * Decimal("0.70")
    result = await conn.execute(
        economy_ledger.insert().values(
            from_persona_id=None,
            to_persona_id=completer_persona_id,
            amount=completer_amount,
            transaction_type="bounty_claim",
            reference_objective_id=objective_id,
            reference_finding_id=finding_id,
            memo="Primary bounty (70%)",
        ).returning(economy_ledger.c.transaction_id)
    )
    tx_ids.append(result.scalar_one())

    # 30% split among reviewers
    if reviewer_persona_ids:
        reviewer_amount = (total_bounty * Decimal("0.30")) / Decimal(str(len(reviewer_persona_ids)))
        for reviewer_id in reviewer_persona_ids:
            result = await conn.execute(
                economy_ledger.insert().values(
                    from_persona_id=None,
                    to_persona_id=reviewer_id,
                    amount=reviewer_amount,
                    transaction_type="peer_review_fee",
                    reference_objective_id=objective_id,
                    reference_finding_id=finding_id,
                    memo="Peer review bounty (30% split)",
                ).returning(economy_ledger.c.transaction_id)
            )
            tx_ids.append(result.scalar_one())

    await emit_event(conn, "bounty_distributed", entity_id=objective_id, entity_type="objective", payload={"total": str(total_bounty), "transactions": len(tx_ids)})
    return tx_ids


def _get_rent_tier_rate(
    balance: Decimal,
    *,
    exempt_below: Decimal = Decimal("20.00"),
    rate_low: Decimal = Decimal("0.03"),
    rate_mid: Decimal = Decimal("0.05"),
    rate_high: Decimal = Decimal("0.08"),
    high_above: Decimal = Decimal("300.00"),
) -> Decimal:
    """Determine the tiered rent decay rate based on balance bracket."""
    if balance < exempt_below:
        return Decimal("0")
    if balance < Decimal("100"):
        return rate_low
    if balance <= high_above:
        return rate_mid
    return rate_high


async def apply_rent_decay(
    conn,
    decay_rate: Decimal = Decimal("0.05"),
    *,
    exempt_below: Decimal = Decimal("20.00"),
    rate_low: Decimal = Decimal("0.03"),
    rate_mid: Decimal = Decimal("0.05"),
    rate_high: Decimal = Decimal("0.08"),
    high_above: Decimal = Decimal("300.00"),
    welfare_redirect_ratio: Decimal = Decimal("0.50"),
    welfare_persona_id: UUID | None = None,
) -> int:
    """Apply tiered rent decay to all active personas.

    Progressive rates by balance bracket:
    - Below ``exempt_below``: 0% (survival floor)
    - 20–100 credits: ``rate_low`` (default 3%)
    - 100–300 credits: ``rate_mid`` (default 5%)
    - Above ``high_above``: ``rate_high`` (default 8%), with 50% redirected to welfare

    Returns count of personas affected.
    """
    from nexus_core.economy.welfare import WELFARE_PERSONA_ID
    from nexus_core.models.personas import agent_personas

    _welfare_id = welfare_persona_id or WELFARE_PERSONA_ID

    # Exclude system personas from rent
    system_q = await conn.execute(
        sa.select(agent_personas.c.persona_id)
        .where(agent_personas.c.role_class == "system")
    )
    system_ids = {row.persona_id for row in system_q}

    balances = await get_all_balances(conn)
    count = 0

    for persona_id, balance in balances.items():
        if balance <= Decimal("0"):
            continue
        if persona_id in system_ids:
            continue

        tier_rate = _get_rent_tier_rate(
            balance,
            exempt_below=exempt_below,
            rate_low=rate_low,
            rate_mid=rate_mid,
            rate_high=rate_high,
            high_above=high_above,
        )
        if tier_rate == Decimal("0"):
            continue

        # Get profile multiplier (existing behavior)
        profile = (
            await conn.execute(
                sa.select(objective_incentive_profiles.c.rent_multiplier)
                .select_from(
                    agent_instances.join(
                        objective_incentive_profiles,
                        agent_instances.c.objective_id == objective_incentive_profiles.c.objective_id,
                    )
                )
                .where(
                    agent_instances.c.persona_id == persona_id,
                    agent_instances.c.status.in_(["running", "pending"]),
                )
                .order_by(
                    sa.case((agent_instances.c.status == "running", 0), else_=1),
                    agent_instances.c.started_at.desc(),
                )
                .limit(1)
            )
        ).first()
        multiplier = Decimal(str(getattr(profile, "rent_multiplier", Decimal("1.00")) or 1))
        rent_amount = (balance * tier_rate * multiplier).quantize(Decimal("0.01"))
        if rent_amount < Decimal("0.01"):
            rent_amount = Decimal("0.01")

        # High-tier: split between welfare redirect and burn
        if balance > high_above and welfare_redirect_ratio > Decimal("0"):
            welfare_amount = (rent_amount * welfare_redirect_ratio).quantize(Decimal("0.01"))
            burn_amount = rent_amount - welfare_amount

            if welfare_amount > Decimal("0"):
                await conn.execute(
                    economy_ledger.insert().values(
                        from_persona_id=persona_id,
                        to_persona_id=_welfare_id,
                        amount=welfare_amount,
                        transaction_type="welfare_redirect",
                        memo=f"Rent welfare redirect ({tier_rate*multiplier*100:.1f}% rate, {welfare_redirect_ratio*100:.0f}% to welfare)",
                    )
                )
            if burn_amount > Decimal("0"):
                await conn.execute(
                    economy_ledger.insert().values(
                        from_persona_id=persona_id,
                        to_persona_id=None,
                        amount=burn_amount,
                        transaction_type="rent_payment",
                        memo=f"Rent decay burn ({tier_rate*multiplier*100:.1f}% rate, {(1-welfare_redirect_ratio)*100:.0f}% burned)",
                    )
                )
        else:
            await conn.execute(
                economy_ledger.insert().values(
                    from_persona_id=persona_id,
                    to_persona_id=None,
                    amount=rent_amount,
                    transaction_type="rent_payment",
                    memo=f"Rent decay ({tier_rate*multiplier*100:.1f}% effective rate)",
                )
            )
        count += 1

    if count > 0:
        await emit_event(conn, "rent_decay_applied", payload={"personas_affected": count, "tiered": True})

    return count


async def apply_novelty_bonus(
    conn,
    persona_id: UUID,
    bonus_amount: Decimal,
    reference_finding_id: UUID | None = None,
    memo: str = "Novelty bonus for dissimilar KG contribution",
) -> UUID:
    """Award a novelty bonus to a persona."""
    result = await conn.execute(
        economy_ledger.insert().values(
            from_persona_id=None,
            to_persona_id=persona_id,
            amount=bonus_amount,
            transaction_type="novelty_bonus",
            reference_finding_id=reference_finding_id,
            memo=memo,
        ).returning(economy_ledger.c.transaction_id)
    )
    return result.scalar_one()


async def issue_participation_salary(
    conn,
    finding_id: UUID,
    persona_id: UUID,
    objective_budget: Decimal,
    reputation_score: Decimal,
    reference_objective_id: UUID | None = None,
    *,
    salary_budget_rate: Decimal = Decimal("0.12"),
    salary_min: Decimal = Decimal("1.00"),
    salary_max: Decimal = Decimal("5.00"),
) -> UUID | None:
    """Mint participation salary if not already paid for this finding.

    Returns transaction_id or None if already paid.
    """
    # Idempotency guard: check if salary was already issued for this finding
    existing = await conn.execute(
        sa.select(sa.func.count()).select_from(economy_ledger).where(
            economy_ledger.c.reference_finding_id == finding_id,
            economy_ledger.c.transaction_type == "participation_salary",
        )
    )
    if existing.scalar_one() > 0:
        logger.debug("salary_already_issued", finding_id=str(finding_id))
        return None

    # Compute salary amount
    base = max(salary_min, objective_budget * salary_budget_rate)
    # Reputation multiplier: maps [0.0, 1.0] reputation to [0.8, 1.2]
    rep = Decimal(str(reputation_score)) if not isinstance(reputation_score, Decimal) else reputation_score
    reputation_multiplier = Decimal("0.8") + (rep * Decimal("0.4"))
    amount = min(base * reputation_multiplier, salary_max).quantize(Decimal("0.01"))

    tx_id = await mint_credits(
        conn,
        amount=amount,
        to_persona_id=persona_id,
        reference_objective_id=reference_objective_id,
        reference_finding_id=finding_id,
        memo=f"Participation salary ({amount} credits)",
    )
    # Override transaction_type to participation_salary (mint_credits uses "mint")
    await conn.execute(
        economy_ledger.update()
        .where(economy_ledger.c.transaction_id == tx_id)
        .values(transaction_type="participation_salary")
    )

    await emit_event(
        conn, "salary_issued",
        entity_id=persona_id, entity_type="persona",
        payload={
            "amount": str(amount),
            "finding_id": str(finding_id),
            "transaction_id": str(tx_id),
        },
    )
    logger.info(
        "salary_issued",
        persona_id=str(persona_id),
        finding_id=str(finding_id),
        amount=str(amount),
    )
    return tx_id


async def get_balance(conn, persona_id: UUID) -> Decimal:
    """Get current credit balance for a persona (derived from ledger)."""
    result = await conn.execute(
        sa.select(balance_expression(sa.literal(persona_id, type_=sa.Uuid)))
    )
    return Decimal(str(result.scalar_one()))


async def get_all_balances(conn) -> dict[UUID, Decimal]:
    """Get credit balances for all personas with transactions."""
    # Get all credits
    credits_q = (
        sa.select(
            economy_ledger.c.to_persona_id.label("persona_id"),
            sa.func.sum(economy_ledger.c.amount).label("total_credits"),
        )
        .where(economy_ledger.c.to_persona_id.isnot(None))
        .group_by(economy_ledger.c.to_persona_id)
    )
    credits_result = await conn.execute(credits_q)
    credits_map: dict[UUID, Decimal] = {}
    for row in credits_result:
        credits_map[row.persona_id] = Decimal(str(row.total_credits))

    # Get all debits
    debits_q = (
        sa.select(
            economy_ledger.c.from_persona_id.label("persona_id"),
            sa.func.sum(economy_ledger.c.amount).label("total_debits"),
        )
        .where(economy_ledger.c.from_persona_id.isnot(None))
        .group_by(economy_ledger.c.from_persona_id)
    )
    debits_result = await conn.execute(debits_q)
    debits_map: dict[UUID, Decimal] = {}
    for row in debits_result:
        debits_map[row.persona_id] = Decimal(str(row.total_debits))

    # Combine all persona IDs
    all_ids = set(credits_map.keys()) | set(debits_map.keys())
    balances = {}
    for pid in all_ids:
        balances[pid] = credits_map.get(pid, Decimal("0")) - debits_map.get(pid, Decimal("0"))

    return balances


async def get_ledger_entries(
    conn,
    persona_id: UUID | None = None,
    transaction_type: str | None = None,
    limit: int = 100,
) -> list[dict]:
    """Get ledger entries with optional filters."""
    query = economy_ledger.select().order_by(economy_ledger.c.created_at.desc()).limit(limit)

    if persona_id:
        query = query.where(
            sa.or_(
                economy_ledger.c.from_persona_id == persona_id,
                economy_ledger.c.to_persona_id == persona_id,
            )
        )

    if transaction_type:
        query = query.where(economy_ledger.c.transaction_type == transaction_type)

    result = await conn.execute(query)
    return [dict(row._mapping) for row in result]


async def get_personas_below_threshold(
    conn,
    threshold: Decimal,
) -> list[UUID]:
    """Get persona IDs whose balance is below the survival threshold."""
    balances = await get_all_balances(conn)
    return [pid for pid, balance in balances.items() if balance < threshold]


async def apply_wealth_tax(
    conn,
    *,
    top_rate: Decimal = Decimal("0.015"),
    mid_rate: Decimal = Decimal("0.005"),
    welfare_persona_id: UUID | None = None,
) -> int:
    """Apply wealth tax on top quartile agents by liquid balance.

    Top quartile (by balance): tax = top_rate × (balance - median)
    Upper-mid quartile: tax = mid_rate × (balance - median)
    Bottom half: exempt.

    Tax proceeds go to the welfare persona.
    Returns count of agents taxed.
    """
    from nexus_core.economy.welfare import WELFARE_PERSONA_ID
    from nexus_core.models.personas import agent_personas

    _welfare_id = welfare_persona_id or WELFARE_PERSONA_ID

    # Exclude system personas
    system_q = await conn.execute(
        sa.select(agent_personas.c.persona_id)
        .where(agent_personas.c.role_class == "system")
    )
    system_ids = {row.persona_id for row in system_q}

    balances = await get_all_balances(conn)
    agent_balances = [
        (pid, bal) for pid, bal in balances.items()
        if pid not in system_ids and bal > Decimal("0")
    ]

    if len(agent_balances) < 4:
        return 0  # Need at least 4 agents for quartile calculation

    sorted_balances = sorted(agent_balances, key=lambda x: x[1])
    values = [bal for _, bal in sorted_balances]
    median_idx = len(values) // 2
    median_balance = values[median_idx]
    q3_idx = len(values) * 3 // 4

    taxed = 0
    total_tax = Decimal("0")

    for i, (pid, balance) in enumerate(sorted_balances):
        if balance <= median_balance:
            continue  # Bottom half exempt

        excess = balance - median_balance
        if i >= q3_idx:
            tax = (excess * top_rate).quantize(Decimal("0.01"))
        else:
            tax = (excess * mid_rate).quantize(Decimal("0.01"))

        if tax < Decimal("0.01"):
            continue

        await conn.execute(
            economy_ledger.insert().values(
                from_persona_id=pid,
                to_persona_id=_welfare_id,
                amount=tax,
                transaction_type="wealth_tax",
                memo=f"Wealth tax on excess balance above median ({median_balance:.0f})",
            )
        )
        taxed += 1
        total_tax += tax

    if taxed > 0:
        await emit_event(
            conn, "wealth_tax_applied",
            payload={
                "agents_taxed": taxed,
                "total_collected": str(total_tax),
                "median_balance": str(median_balance),
            },
        )

    return taxed
