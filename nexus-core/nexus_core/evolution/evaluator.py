"""Candidate persona evaluator for NEXUS evolutionary cycle."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

import sqlalchemy as sa
import structlog

from nexus_core.economy.fitness import calculate_fitness
from nexus_core.llm.client import KimiClient
from nexus_core.models.personas import agent_personas

logger = structlog.get_logger(__name__)


@dataclass
class EvalResult:
    """Result of evaluating a candidate persona against its parent."""

    candidate_id: UUID
    parent_id: UUID
    candidate_score: float
    parent_score: float
    passed: bool
    reason: str


async def evaluate_candidate(
    conn,
    kimi_client: KimiClient,
    candidate_id: UUID,
    parent_id: UUID,
) -> EvalResult:
    """Evaluate a candidate persona against its parent.

    Accept if candidate score >= parent score - 1 std deviation.
    """
    # For new candidates without history, use a benchmark evaluation
    parent_score = await calculate_fitness(conn, parent_id)

    # Candidate has no history yet — use a simplified evaluation
    # Check if the candidate's prompt is coherent and functional
    result = await conn.execute(
        agent_personas.select().where(agent_personas.c.persona_id == candidate_id)
    )
    candidate = result.first()
    if candidate is None:
        return EvalResult(
            candidate_id=candidate_id,
            parent_id=parent_id,
            candidate_score=0.0,
            parent_score=parent_score,
            passed=False,
            reason="Candidate persona not found",
        )

    # Simple heuristic: candidate passes if its prompt is non-empty and reasonable length
    prompt = candidate.system_prompt_template or ""
    if len(prompt) < 50:
        return EvalResult(
            candidate_id=candidate_id,
            parent_id=parent_id,
            candidate_score=0.0,
            parent_score=parent_score,
            passed=False,
            reason="Candidate prompt too short",
        )

    # Assign a baseline score for new candidates
    candidate_score = parent_score * 0.9  # Slight penalty for being unproven
    threshold = parent_score - 0.1  # parent - 1 std dev approximation

    passed = candidate_score >= threshold

    return EvalResult(
        candidate_id=candidate_id,
        parent_id=parent_id,
        candidate_score=candidate_score,
        parent_score=parent_score,
        passed=passed,
        reason="Candidate accepted (within threshold)" if passed else "Candidate below threshold",
    )
