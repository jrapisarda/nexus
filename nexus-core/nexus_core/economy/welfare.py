"""Welfare pool distribution for NEXUS economy."""

from decimal import Decimal
from uuid import UUID

import sqlalchemy as sa
import structlog

from nexus_core.economy.ledger import get_all_balances, get_balance
from nexus_core.models.economy import economy_ledger
from nexus_core.models.personas import agent_personas
from nexus_core.utils.events import emit_event

logger = structlog.get_logger(__name__)

WELFARE_PERSONA_ID = UUID("00000000-0000-0000-0000-000000000001")


async def get_welfare_balance(conn) -> Decimal:
    """Get the current balance of the welfare pool persona."""
    return await get_balance(conn, WELFARE_PERSONA_ID)


async def distribute_welfare(
    conn,
    floor: Decimal = Decimal("30.00"),
) -> int:
    """Distribute welfare pool credits to agents below the floor.

    Each qualifying agent receives min(floor - balance, equal_share) to bring
    them closer to the floor. Returns the count of recipients.
    """
    pool_balance = await get_welfare_balance(conn)
    if pool_balance <= Decimal("0"):
        logger.debug("welfare_pool_empty")
        return 0

    # Get all active non-system personas and their balances
    all_balances = await get_all_balances(conn)

    # Get system persona IDs to exclude
    system_q = await conn.execute(
        sa.select(agent_personas.c.persona_id)
        .where(agent_personas.c.role_class == "system")
    )
    system_ids = {row.persona_id for row in system_q}

    # Find personas below the floor
    recipients: list[tuple[UUID, Decimal]] = []
    for pid, balance in all_balances.items():
        if pid in system_ids:
            continue
        if balance < floor:
            deficit = floor - balance
            recipients.append((pid, deficit))

    if not recipients:
        logger.debug("welfare_no_qualifying_recipients")
        return 0

    # Calculate equal share from pool, capped at each recipient's deficit
    total_deficit = sum(d for _, d in recipients)
    distributable = min(pool_balance, total_deficit)
    equal_share = distributable / Decimal(str(len(recipients)))

    distributed_count = 0
    total_distributed = Decimal("0")

    for pid, deficit in recipients:
        amount = min(equal_share, deficit).quantize(Decimal("0.01"))
        if amount < Decimal("0.01"):
            continue

        # Transfer from welfare persona to recipient
        await conn.execute(
            economy_ledger.insert().values(
                from_persona_id=WELFARE_PERSONA_ID,
                to_persona_id=pid,
                amount=amount,
                transaction_type="welfare_distribution",
                memo=f"Welfare top-up toward {floor} credit floor",
            )
        )
        distributed_count += 1
        total_distributed += amount

    if distributed_count > 0:
        await emit_event(
            conn, "welfare_distributed",
            payload={
                "recipients": distributed_count,
                "total_distributed": str(total_distributed),
                "pool_remaining": str(pool_balance - total_distributed),
            },
        )
        logger.info(
            "welfare_distributed",
            recipients=distributed_count,
            total_distributed=str(total_distributed),
            pool_remaining=str(pool_balance - total_distributed),
        )

    return distributed_count
