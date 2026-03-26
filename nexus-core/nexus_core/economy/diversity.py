"""Diversity and economy health metrics for NEXUS."""

from decimal import Decimal
from uuid import UUID
import numpy as np
import sqlalchemy as sa
from nexus_core.models.personas import agent_personas

import structlog
logger = structlog.get_logger(__name__)


def calculate_gini(balances: list[Decimal]) -> float:
    """Calculate Gini coefficient of agent wealth distribution.

    Returns: float in [0, 1] where 0 = perfect equality, 1 = perfect inequality.
    """
    arr = np.array([float(b) for b in balances], dtype=float)
    arr = arr[arr >= 0]  # Exclude negative balances
    if len(arr) == 0 or np.sum(arr) == 0:
        return 0.0
    arr = np.sort(arr)
    n = len(arr)
    index = np.arange(1, n + 1)
    return float((2 * np.sum(index * arr) - (n + 1) * np.sum(arr)) / (n * np.sum(arr)))


async def check_role_class_minimums(
    conn,
    min_per_class: int = 2,
) -> list[str]:
    """Check which role classes are below the minimum persona count.

    Returns: list of role_class names that are below minimum.
    """
    result = await conn.execute(
        sa.select(
            agent_personas.c.role_class,
            sa.func.count().label("count"),
        )
        .where(agent_personas.c.status == "active")
        .group_by(agent_personas.c.role_class)
    )

    below_minimum = []
    for row in result:
        if row.count < min_per_class:
            below_minimum.append(row.role_class)

    return below_minimum


async def get_role_class_counts(conn) -> dict[str, int]:
    """Get the count of active personas per role class."""
    result = await conn.execute(
        sa.select(
            agent_personas.c.role_class,
            sa.func.count().label("count"),
        )
        .where(agent_personas.c.status == "active")
        .group_by(agent_personas.c.role_class)
    )
    return {row.role_class: row.count for row in result}


async def calculate_novelty_bonus(
    conn,
    persona_id: UUID,
    recent_node_properties: list[dict],
    embedding_service=None,
) -> float:
    """Calculate novelty bonus based on how dissimilar a persona's contributions
    are from recent KG additions.

    Returns a multiplier in [0.0, 2.0] where >1.0 means novel contribution.
    """
    if not recent_node_properties or embedding_service is None:
        return 1.0  # Neutral bonus

    # Get the persona's recent contributions
    from nexus_core.models.knowledge_graph import knowledge_graph_nodes
    from nexus_core.models.instances import agent_instances

    persona_nodes_q = (
        sa.select(knowledge_graph_nodes.c.properties)
        .join(agent_instances, knowledge_graph_nodes.c.discovered_by_instance_id == agent_instances.c.instance_id)
        .where(agent_instances.c.persona_id == persona_id)
        .order_by(knowledge_graph_nodes.c.first_seen.desc())
        .limit(10)
    )
    result = await conn.execute(persona_nodes_q)
    persona_properties = [dict(row._mapping)["properties"] for row in result]

    if not persona_properties:
        return 1.0

    # Compute average dissimilarity
    persona_texts = [str(p) for p in persona_properties]
    recent_texts = [str(p) for p in recent_node_properties]

    persona_embeddings = embedding_service.batch_encode(persona_texts)
    recent_embeddings = embedding_service.batch_encode(recent_texts)

    # Average cosine distance between persona's contributions and recent KG additions
    total_distance = 0.0
    count = 0
    for p_emb in persona_embeddings:
        for r_emb in recent_embeddings:
            total_distance += 1.0 - embedding_service.cosine_similarity(p_emb, r_emb)
            count += 1

    avg_distance = total_distance / max(count, 1)

    # Map distance to bonus multiplier: 0 distance = 0.5x, 0.5 distance = 1.0x, 1.0 distance = 2.0x
    bonus = 0.5 + (avg_distance * 1.5)
    return min(max(bonus, 0.0), 2.0)


async def get_economy_summary(conn) -> dict:
    """Get economy health metrics."""
    from nexus_core.economy.ledger import get_all_balances

    balances = await get_all_balances(conn)

    # Exclude system personas (e.g., welfare pool) from economic metrics
    system_q = await conn.execute(
        sa.select(agent_personas.c.persona_id)
        .where(agent_personas.c.role_class == "system")
    )
    system_ids = {row.persona_id for row in system_q}
    balances = {pid: bal for pid, bal in balances.items() if pid not in system_ids}

    balance_list = list(balances.values())

    # Total credits in system
    from nexus_core.models.economy import economy_ledger
    total_minted_q = await conn.execute(
        sa.select(sa.func.coalesce(sa.func.sum(economy_ledger.c.amount), Decimal("0")))
        .where(economy_ledger.c.transaction_type == "mint")
    )
    total_minted = total_minted_q.scalar_one()

    total_rent_q = await conn.execute(
        sa.select(sa.func.coalesce(sa.func.sum(economy_ledger.c.amount), Decimal("0")))
        .where(economy_ledger.c.transaction_type == "rent_payment")
    )
    total_rent = total_rent_q.scalar_one()

    return {
        "total_personas": len(balances),
        "total_credits_minted": float(total_minted),
        "total_rent_collected": float(total_rent),
        "net_credits_in_system": float(sum(balance_list)) if balance_list else 0.0,
        "gini_coefficient": calculate_gini([Decimal(str(b)) for b in balance_list]),
        "top_balance": float(max(balance_list)) if balance_list else 0.0,
        "bottom_balance": float(min(balance_list)) if balance_list else 0.0,
        "mean_balance": float(np.mean([float(b) for b in balance_list])) if balance_list else 0.0,
    }
