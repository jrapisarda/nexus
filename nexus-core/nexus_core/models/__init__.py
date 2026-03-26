"""NEXUS SQLAlchemy Core table definitions.

All tables are registered against a single shared :data:`metadata` instance.
"""

from sqlalchemy import MetaData

metadata = MetaData()

# Import all table modules so they register their Table objects with *metadata*.
from nexus_core.models.personas import agent_personas  # noqa: E402, F401
from nexus_core.models.objectives import objectives  # noqa: E402, F401
from nexus_core.models.instances import agent_instances  # noqa: E402, F401
from nexus_core.models.decomposition import objective_decomposition  # noqa: E402, F401
from nexus_core.models.knowledge_graph import knowledge_graph_nodes, knowledge_graph_edges  # noqa: E402, F401
from nexus_core.models.findings import findings  # noqa: E402, F401
from nexus_core.models.peer_reviews import peer_reviews  # noqa: E402, F401
from nexus_core.models.economy import economy_ledger  # noqa: E402, F401
from nexus_core.models.market import (
    persona_market_profiles,
    market_templates,
    market_assets,
    marketplace_listings,
    service_contracts,
    market_instruments,
    market_orders,
    market_trades,
    market_positions,
    market_price_history,
    market_reservations,
    kg_node_bids,
)  # noqa: E402, F401
from nexus_core.models.civilization import (
    persona_capability_scores,
    civilization_bonds,
    civilization_challenges,
    civilization_quality_holdbacks,
    objective_incentive_profiles,
    scout_source_health,
    evolution_metric_snapshots,
    circuit_breaker_rules,
    circuit_breaker_incidents,
)  # noqa: E402, F401
from nexus_core.models.governance import governance_proposals, governance_votes  # noqa: E402, F401
from nexus_core.models.messages import messages  # noqa: E402, F401
from nexus_core.models.institutional_memory import institutional_memory  # noqa: E402, F401
from nexus_core.models.tool_registry import tool_registry  # noqa: E402, F401
from nexus_core.models.telemetry import agent_telemetry  # noqa: E402, F401
from nexus_core.models.events import events  # noqa: E402, F401
from nexus_core.models.attachments import objective_attachments  # noqa: E402, F401
from nexus_core.models.citation import citation_verifications, template_craft_cycle_counts  # noqa: E402, F401

__all__ = [
    "metadata",
    "agent_personas",
    "objectives",
    "agent_instances",
    "objective_decomposition",
    "knowledge_graph_nodes",
    "knowledge_graph_edges",
    "findings",
    "peer_reviews",
    "economy_ledger",
    "persona_market_profiles",
    "market_templates",
    "market_assets",
    "marketplace_listings",
    "service_contracts",
    "market_instruments",
    "market_orders",
    "market_trades",
    "market_positions",
    "market_price_history",
    "market_reservations",
    "kg_node_bids",
    "persona_capability_scores",
    "civilization_bonds",
    "civilization_challenges",
    "civilization_quality_holdbacks",
    "objective_incentive_profiles",
    "scout_source_health",
    "evolution_metric_snapshots",
    "circuit_breaker_rules",
    "circuit_breaker_incidents",
    "governance_proposals",
    "governance_votes",
    "messages",
    "institutional_memory",
    "tool_registry",
    "agent_telemetry",
    "events",
    "objective_attachments",
    "citation_verifications",
    "template_craft_cycle_counts",
]
