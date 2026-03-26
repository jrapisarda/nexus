"""Evolutionary mutation engine for NEXUS agent personas."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

import structlog

from nexus_core.economy.ledger import get_balance
from nexus_core.llm.client import KimiClient
from nexus_core.llm.prompt_builder import PromptBuilder
from nexus_core.llm.response_parser import ResponseParser
from nexus_core.models.personas import agent_personas

import sqlalchemy as sa

logger = structlog.get_logger(__name__)


@dataclass
class MutationProposal:
    """A proposed mutation to an agent persona's system prompt."""

    parent_persona_id: UUID
    mutated_prompt: str
    changes_description: str
    expected_improvement: str
    mutation_type: str  # prompt_edit, role_expansion, constraint_tightening, temperature_shift, tool_addition


async def generate_mutation(
    conn,
    kimi_client: KimiClient,
    persona_id: UUID,
    donor_persona_id: UUID | None = None,
) -> MutationProposal | None:
    """Generate a mutation proposal for a persona using Kimi K2.5 instant mode."""
    # Get current persona
    result = await conn.execute(
        agent_personas.select().where(agent_personas.c.persona_id == persona_id)
    )
    persona = result.first()
    if persona is None:
        return None

    ledger_balance = await get_balance(conn, persona_id)
    donor_excerpt = None
    if donor_persona_id is not None:
        donor_result = await conn.execute(
            sa.select(agent_personas.c.system_prompt_template).where(
                agent_personas.c.persona_id == donor_persona_id
            )
        )
        donor_row = donor_result.first()
        if donor_row is not None:
            donor_excerpt = donor_row.system_prompt_template[:400]

    # Build performance summary from telemetry (simplified)
    performance = (
        f"Current ledger-derived credit balance: {ledger_balance}. "
        f"Reputation: {persona.reputation_score}."
    )

    system_prompt, user_prompt = PromptBuilder.build_mutation_prompt(
        current_prompt=persona.system_prompt_template,
        performance_summary=performance,
        mutation_type="prompt_edit",
        donor_prompt_excerpt=donor_excerpt,
    )

    response = await kimi_client.call_instant(system_prompt, user_prompt)
    mutation_data = ResponseParser.parse_mutation(response.content)

    if not mutation_data.mutated_prompt:
        return None

    # Validate edit distance
    edit_distance_ratio = _levenshtein_ratio(persona.system_prompt_template, mutation_data.mutated_prompt)
    if edit_distance_ratio > 0.30:
        logger.warning(
            "mutation_too_large",
            persona_id=str(persona_id),
            edit_ratio=edit_distance_ratio,
        )
        return None

    return MutationProposal(
        parent_persona_id=persona_id,
        mutated_prompt=mutation_data.mutated_prompt,
        changes_description=mutation_data.changes_description,
        expected_improvement=mutation_data.expected_improvement,
        mutation_type="horizontal_transfer" if donor_excerpt else "prompt_edit",
    )


def _levenshtein_ratio(s1: str, s2: str) -> float:
    """Compute edit distance ratio (0=identical, 1=completely different).

    Uses a word-level Jaccard distance approximation for speed.
    """
    if not s1 and not s2:
        return 0.0
    max_len = max(len(s1), len(s2))
    if max_len == 0:
        return 0.0
    # Simple word-level edit distance approximation
    words1 = set(s1.lower().split())
    words2 = set(s2.lower().split())
    if not words1 and not words2:
        return 0.0
    union = words1 | words2
    intersection = words1 & words2
    return 1.0 - (len(intersection) / len(union))
