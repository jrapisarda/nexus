import asyncio

from nexus_core.llm.client import KimiClient
from nexus_core.llm.prompt_builder import PromptBuilder
from nexus_core.llm.response_parser import ResponseParser
from nexus_core.knowledge.query import get_kg_stats, get_recent_nodes
from nexus_core.models.objectives import objectives
from nexus_core.models.institutional_memory import institutional_memory
import structlog

logger = structlog.get_logger(__name__)


async def run_dream_cycle(engine, kimi_client: KimiClient):
    """Run the Dream Cycle -- consolidate recent KG activity and propose new research directions."""
    logger.info("dream_cycle_starting")

    async with engine.begin() as conn:
        stats = await get_kg_stats(conn)
        recent = await get_recent_nodes(conn, limit=50)

    if stats.node_count == 0:
        logger.info("dream_cycle_skipped_empty_kg")
        return

    # Build KG summary from recent nodes
    recent_dicts = [dict(r) if not isinstance(r, dict) else r for r in recent]
    recent_summary = "\n".join(
        [
            f"- [{n.get('node_type', '?')}] {n.get('label', '?')} "
            f"(confidence: {n.get('confidence_score', 0):.2f})"
            for n in recent_dicts[:30]
        ]
    )

    system_prompt, user_prompt = PromptBuilder.build_dream_cycle_prompt(
        recent_kg_summary=recent_summary,
        kg_stats={
            "node_count": stats.node_count,
            "edge_count": stats.edge_count,
            "avg_confidence": stats.avg_confidence,
        },
    )

    # Use instant mode (cheaper for consolidation)
    response = await kimi_client.call_instant(system_prompt, user_prompt)
    dream_data = ResponseParser.parse_dream_cycle(response.content)

    # Store results
    async with engine.begin() as conn:
        # Write consolidation to institutional memory
        await conn.execute(
            institutional_memory.insert().values(
                memory_type="successful_pattern",
                title="Dream Cycle Consolidation",
                content=response.content,
                relevance_tags=[
                    p.get("description", "")[:50]
                    for p in dream_data.patterns_identified[:5]
                ],
            )
        )

        # Create exploratory objectives from proposals
        for proposal in dream_data.proposed_objectives:
            await conn.execute(
                objectives.insert().values(
                    title=proposal.get("title", "Exploratory Objective"),
                    description=proposal.get("description", ""),
                    objective_type="exploratory",
                    impact_level="routine",
                    priority=3,
                    status="proposed",
                    proposed_by_type="agent",
                    acceptance_criteria=proposal.get("rationale", ""),
                )
            )

    logger.info(
        "dream_cycle_complete",
        patterns=len(dream_data.patterns_identified),
        proposals=len(dream_data.proposed_objectives),
    )
