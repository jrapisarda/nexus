"""Governance voting system for NEXUS — reputation-weighted majority."""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Optional
from uuid import UUID

import sqlalchemy as sa
import structlog

from nexus_core.civilization.service import create_probation_bond_for_persona
from nexus_core.governance.proposals import get_proposal, update_proposal_status
from nexus_core.models.governance import governance_proposals, governance_votes
from nexus_core.models.personas import agent_personas
from nexus_core.utils.events import emit_event

logger = structlog.get_logger(__name__)


@dataclass
class ProposalOutcome:
    """Result of tallying votes for a governance proposal."""

    proposal_id: UUID
    approved: bool
    vote_counts: dict = field(default_factory=dict)  # {"approve": N, "reject": N, "abstain": N}
    weighted_score: float = 0.0
    rationale: str = ""


async def cast_vote(
    conn,
    proposal_id: UUID,
    voter_persona_id: UUID,
    vote: str,
    reasoning: str,
) -> UUID:
    """Record a vote on a governance proposal.

    Args:
        conn: Active database connection.
        proposal_id: The proposal being voted on.
        voter_persona_id: The persona casting the vote.
        vote: One of ``"approve"``, ``"reject"``, ``"abstain"``.
        reasoning: Explanation for the vote.

    Returns:
        The ``vote_id`` of the recorded vote.

    Raises:
        ValueError: If the proposal is not in a voteable state or the vote
            value is invalid.
    """
    if vote not in ("approve", "reject", "abstain"):
        raise ValueError(f"Invalid vote value: {vote!r}. Must be 'approve', 'reject', or 'abstain'.")

    # Verify proposal exists and is in a voteable state
    proposal = await get_proposal(conn, proposal_id)
    if proposal is None:
        raise ValueError(f"Proposal {proposal_id} not found")
    if proposal["status"] not in ("proposed", "voting"):
        raise ValueError(
            f"Proposal {proposal_id} is in state '{proposal['status']}' and cannot accept votes"
        )

    # Check for duplicate vote
    existing_q = await conn.execute(
        sa.select(sa.func.count())
        .select_from(governance_votes)
        .where(
            governance_votes.c.proposal_id == proposal_id,
            governance_votes.c.voter_persona_id == voter_persona_id,
        )
    )
    if existing_q.scalar_one() > 0:
        raise ValueError(
            f"Persona {voter_persona_id} has already voted on proposal {proposal_id}"
        )

    # Snapshot voter's current reputation_score
    rep_q = await conn.execute(
        sa.select(agent_personas.c.reputation_score)
        .where(agent_personas.c.persona_id == voter_persona_id)
    )
    rep_row = rep_q.one_or_none()
    if rep_row is None:
        raise ValueError(f"Voter persona {voter_persona_id} not found")

    reputation_weight = rep_row.reputation_score or Decimal("0.500")

    result = await conn.execute(
        governance_votes.insert().values(
            proposal_id=proposal_id,
            voter_persona_id=voter_persona_id,
            vote=vote,
            reasoning=reasoning,
            voter_reputation_weight=reputation_weight,
        ).returning(governance_votes.c.vote_id)
    )
    vote_id = result.scalar_one()

    # Transition proposal to "voting" if still "proposed"
    if proposal["status"] == "proposed":
        await update_proposal_status(conn, proposal_id, "voting")

    await emit_event(
        conn, "governance_vote_cast",
        entity_id=proposal_id, entity_type="proposal",
        payload={
            "vote_id": str(vote_id),
            "voter_persona_id": str(voter_persona_id),
            "vote": vote,
        },
    )

    logger.info(
        "governance_vote_cast",
        proposal_id=str(proposal_id),
        voter_persona_id=str(voter_persona_id),
        vote=vote,
    )
    return vote_id


async def tally_votes(conn, proposal_id: UUID) -> ProposalOutcome:
    """Tally votes for a proposal using reputation-weighted scoring.

    Weighted score = sum(approve_weights) - sum(reject_weights).
    Approved if weighted_score > 0 (simple reputation-weighted majority).
    Abstentions do not contribute to the score.
    """
    votes_q = await conn.execute(
        governance_votes.select()
        .where(governance_votes.c.proposal_id == proposal_id)
    )
    votes = list(votes_q)

    if not votes:
        return ProposalOutcome(
            proposal_id=proposal_id,
            approved=False,
            vote_counts={"approve": 0, "reject": 0, "abstain": 0},
            weighted_score=0.0,
            rationale="No votes cast",
        )

    approve_weight = Decimal("0")
    reject_weight = Decimal("0")
    counts = {"approve": 0, "reject": 0, "abstain": 0}

    for v in votes:
        w = v.voter_reputation_weight or Decimal("0.500")
        if v.vote == "approve":
            approve_weight += w
            counts["approve"] += 1
        elif v.vote == "reject":
            reject_weight += w
            counts["reject"] += 1
        else:
            counts["abstain"] += 1

    weighted_score = float(approve_weight - reject_weight)
    approved = weighted_score > 0

    # Build rationale summary
    if approved:
        rationale = (
            f"Proposal approved with weighted score {weighted_score:.3f} "
            f"({counts['approve']} approve, {counts['reject']} reject, {counts['abstain']} abstain)"
        )
    else:
        rationale = (
            f"Proposal rejected with weighted score {weighted_score:.3f} "
            f"({counts['approve']} approve, {counts['reject']} reject, {counts['abstain']} abstain)"
        )

    outcome = ProposalOutcome(
        proposal_id=proposal_id,
        approved=approved,
        vote_counts=counts,
        weighted_score=weighted_score,
        rationale=rationale,
    )

    logger.info(
        "governance_votes_tallied",
        proposal_id=str(proposal_id),
        approved=approved,
        weighted_score=weighted_score,
        vote_counts=counts,
    )

    return outcome


async def execute_outcome(
    conn,
    proposal_id: UUID,
    outcome: ProposalOutcome,
) -> None:
    """Execute the result of a governance vote.

    Actions depend on the ``proposal_type``:
    - ``deprecate_persona``: set target persona status to "deprecated"
    - ``activate_persona``: set target persona status to "active"
    - ``rule_change`` / ``parameter_update``: log in institutional memory
    """
    proposal = await get_proposal(conn, proposal_id)
    if proposal is None:
        logger.error("execute_outcome_proposal_not_found", proposal_id=str(proposal_id))
        return

    if not outcome.approved:
        await update_proposal_status(conn, proposal_id, "rejected")
        await emit_event(
            conn, "governance_proposal_rejected",
            entity_id=proposal_id, entity_type="proposal",
            payload={"rationale": outcome.rationale},
        )
        return

    proposal_type = proposal["proposal_type"]
    target_persona_id = proposal.get("target_persona_id")

    if proposal_type == "deprecate_persona" and target_persona_id is not None:
        await conn.execute(
            agent_personas.update()
            .where(agent_personas.c.persona_id == target_persona_id)
            .values(
                status="deprecated",
                deprecated_at=sa.func.now(),
                deprecation_reason=f"Governance proposal {proposal_id}: {proposal['title']}",
            )
        )
        logger.info(
            "governance_persona_deprecated",
            persona_id=str(target_persona_id),
            proposal_id=str(proposal_id),
        )

    elif proposal_type == "activate_persona" and target_persona_id is not None:
        await conn.execute(
            agent_personas.update()
            .where(agent_personas.c.persona_id == target_persona_id)
            .values(
                status="active",
                deprecated_at=None,
                deprecation_reason=None,
            )
        )
        await create_probation_bond_for_persona(
            conn,
            persona_id=target_persona_id,
            sponsor_persona_id=proposal.get("proposed_by_persona_id"),
        )
        logger.info(
            "governance_persona_activated",
            persona_id=str(target_persona_id),
            proposal_id=str(proposal_id),
        )

    elif proposal_type in ("rule_change", "parameter_update"):
        # Log in institutional memory for future reference
        from nexus_core.models.institutional_memory import institutional_memory

        await conn.execute(
            institutional_memory.insert().values(
                memory_type="governance_decision",
                title=f"Governance: {proposal['title']}",
                content=(
                    f"Proposal type: {proposal_type}\n"
                    f"Description: {proposal['description']}\n"
                    f"Rationale: {proposal['rationale']}\n"
                    f"Outcome: {outcome.rationale}"
                ),
                relevance_tags=["governance", proposal_type],
            )
        )
        logger.info(
            "governance_rule_change_logged",
            proposal_id=str(proposal_id),
            proposal_type=proposal_type,
        )

    # Mark proposal as executed
    await update_proposal_status(conn, proposal_id, "executed")

    await emit_event(
        conn, "governance_proposal_executed",
        entity_id=proposal_id, entity_type="proposal",
        payload={
            "proposal_type": proposal_type,
            "target_persona_id": str(target_persona_id) if target_persona_id else None,
            "outcome": outcome.rationale,
        },
    )
